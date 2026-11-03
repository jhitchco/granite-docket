"""New construction data for NH towns -> housing.db

  python housing.py fetch      # Census BPS (annual 2018+, monthly 2022-01+) and OPD housing supply CSV
  python housing.py projects   # multifamily project mentions from planning/zoning records in nh_meetings.db
Sources and caveats: housing_sources.md
"""
import csv, datetime as dt, io, json, os, re, sqlite3, sys, time
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
HDB = os.path.join(ROOT, "housing.db")
BPS = "https://www2.census.gov/econ/bps/Place/Northeast%20Region/"
OPD = "https://www.nheconomy.com/getmedia/10c857cf-d7df-44e2-b7c2-8ad38c515a4a/hse2020-2025-Analysis-Share_1.csv"
UA = {"User-Agent": "granite-docket/0.1 (NH municipal research)"}
CLASSES = ["1", "2", "34", "5"]  # 1-unit, 2-unit, 3-4 unit, 5+ unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS permits(town TEXT, mcd TEXT, period TEXT, kind TEXT, reported INTEGER,
  b1 INT,u1 INT,v1 INT, b2 INT,u2 INT,v2 INT, b34 INT,u34 INT,v34 INT, b5 INT,u5 INT,v5 INT,
  PRIMARY KEY(mcd, period, kind));
CREATE TABLE IF NOT EXISTS opd(town TEXT, cousub TEXT, year INT, sf INT, f2 INT, conv INT, u34 INT, u5 INT, mh INT, total INT,
  PRIMARY KEY(cousub, year));
CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY, town TEXT, doc_id INT, date TEXT, board TEXT, doc_type TEXT,
  units INT, kind TEXT, location TEXT, url TEXT, title TEXT, snippet TEXT);
CREATE TABLE IF NOT EXISTS dra(town TEXT, year INT, net_valuation REAL, res_buildings REAL, equalized REAL, ratio REAL,
  total_rate REAL, municipal_rate REAL, school_rate REAL, state_ed_rate REAL, county_rate REAL, PRIMARY KEY(town, year));
"""


def norm_name(s):
    s = re.sub(r"\s+(town|city|township)$", "", s.strip(), flags=re.I)
    return {"Hart's Location": "Hart's Location"}.get(s, s)


def get(url):
    for k in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            if r.status_code == 200: return r.text
            if r.status_code == 404: return None
        except Exception:
            pass
        time.sleep(2 * (k + 1))
    return None


def parse_bps(text, kind):
    """Yield dicts for NH rows. kind: 'year' (annual a-file) or 'month' (c-file)."""
    rows = list(csv.reader(io.StringIO(text)))[3:]
    for r in rows:
        r = [x.strip() for x in r]
        if len(r) < 29 or r[1] != "33": continue
        period = r[0]
        if kind == "year":
            reported = int(r[15] or 0); name = r[16]; nums = r[17:29]
        else:
            period = f"{period[:4]}-{period[4:6]}"
            reported = 0 if r[15] == "5" else 1  # source code 5 = imputed, no report that month
            name = r[16]; nums = r[17:29]
        n = [int(float(x or 0)) for x in nums]
        yield dict(town=norm_name(name), mcd=r[6], period=period, kind=kind, reported=reported,
                   b1=n[0], u1=n[1], v1=n[2], b2=n[3], u2=n[4], v2=n[5], b34=n[6], u34=n[7], v34=n[8], b5=n[9], u5=n[10], v5=n[11])


def fetch(conn):
    today = dt.date.today()
    n = 0
    for y in range(2018, today.year + 1):
        t = get(f"{BPS}ne{y}a.txt")
        if not t: continue
        for d in parse_bps(t, "year"):
            conn.execute("INSERT OR REPLACE INTO permits VALUES(:town,:mcd,:period,:kind,:reported,:b1,:u1,:v1,:b2,:u2,:v2,:b34,:u34,:v34,:b5,:u5,:v5)", d); n += 1
    y, m = 2022, 1
    while (y, m) <= (today.year, today.month):
        t = get(f"{BPS}ne{y % 100:02d}{m:02d}c.txt")
        if t:
            for d in parse_bps(t, "month"):
                conn.execute("INSERT OR REPLACE INTO permits VALUES(:town,:mcd,:period,:kind,:reported,:b1,:u1,:v1,:b2,:u2,:v2,:b34,:u34,:v34,:b5,:u5,:v5)", d); n += 1
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    conn.commit()
    print(f"BPS rows: {n}")
    t = get(OPD)
    if t:
        rows = list(csv.reader(io.StringIO(t)))
        heads, groups = [h.strip().lstrip("﻿") for h in rows[0]], rows[1]
        num = lambda x: int(float(x.replace(",", ""))) if re.match(r"^-?[\d,\.]+$", x.strip() or "x") else 0
        # each permit year is a block of columns whose group label (row 0, forward-filled) names the year
        lab, filled = "", []
        for g in groups: lab = g.strip() or lab; filled.append(lab)
        icou = heads.index("cousub") if "cousub" in heads else 0
        itown = next(i for i, h in enumerate(heads) if h.strip().lower() == "town")
        for r in rows[2:]:
            if len(r) <= itown or not r[itown].strip(): continue
            for year in range(2020, 2026):
                cols = {heads[i].strip(): r[i] for i in range(len(r)) if str(year) in filled[i] and "ermit" in filled[i]}
                if not cols: continue
                g = lambda k: num(cols.get(k, "0"))
                conn.execute("INSERT OR REPLACE INTO opd VALUES(?,?,?,?,?,?,?,?,?,?)",
                             (norm_name(r[itown]), r[icou], year, g("SF"), g("2F"), g("Convert"), g("3or4"), g("5+"), g("MH"), g("Total")))
        conn.commit()
        print("OPD rows:", conn.execute("SELECT count(*) FROM opd").fetchone()[0])


UNIT_RX = re.compile(r"(?<![\d,$])(\d{1,3}(?:,\d{3})?|[a-z\-]+ \(\d+\))[\s-]*(?:residential |dwelling |new |rental |market[- ]rate |workforce |affordable |senior |age[- ]restricted )*"
                     r"(?:unit|apartment|condominium|condo|dwelling)s?\b", re.I)
KIND_RX = re.compile(r"multi-?\s?family|apartment|garden[- ]style|townhouse|townhome|condominium|mixed[- ]use|workforce housing|elderly housing|age[- ]restricted|55\+", re.I)
LOC_RX = re.compile(r"(\d{1,5}\s+(?:[A-Z][a-zA-Z]+\s){1,3}(?:Road|Rd|Street|St|Avenue|Ave|Drive|Dr|Lane|Ln|Highway|Hwy|Way|Boulevard|Blvd|Turnpike|Pike|Route|Circle|Parkway|Pkwy)\.?)|(?:Map|Tax Map)\s*\d+[A-Z]?,?\s*(?:Lot\s*[\d\-A-Z]+)|(?:Route|Rt\.?)\s*\d+[A-Z]?")


def projects(conn):
    src = sqlite3.connect(os.path.join(ROOT, "nh_meetings.db"), timeout=60)
    q = """SELECT d.id,d.town,d.meeting_date,d.board,d.doc_type,d.url,d.title,t.text FROM doc_fts f
           JOIN documents d ON d.id=f.rowid JOIN doc_text t ON t.id=d.id
           WHERE doc_fts MATCH '(multifamily OR "multi family" OR apartment OR apartments OR "garden style" OR townhouse OR townhomes) AND (unit OR units)'
             AND d.board IN ('planning','zoning','select_board','town_meeting','other') AND d.meeting_date >= '2022-01-01'"""
    conn.execute("DELETE FROM projects")
    n = 0
    for doc_id, town, date, board, dtype, url, title, text in src.execute(q):
        seen = set()
        for m in UNIT_RX.finditer(text):
            raw = re.sub(r"\D", "", m.group(1))
            if not raw: continue
            units = int(raw)
            if units < 5 or units > 2000: continue
            a, b = max(0, m.start() - 350), min(len(text), m.end() + 350)
            win = text[a:b]
            if not KIND_RX.search(win): continue
            if re.search(r"accessory dwelling|ADU\b|per acre|density of|maximum of|no more than|up to \d+ units per", win, re.I): continue
            loc = LOC_RX.search(win)
            key = (units, loc.group(0) if loc else "")
            if key in seen: continue
            seen.add(key)
            kind = KIND_RX.search(win).group(0).lower()
            snip = re.sub(r"\s+", " ", text[max(0, m.start() - 220):m.end() + 220])
            conn.execute("INSERT INTO projects(town,doc_id,date,board,doc_type,units,kind,location,url,title,snippet) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (town, doc_id, date, board, dtype, units, kind, loc.group(0).strip() if loc else None, url, title, snip))
            n += 1
    conn.commit()
    print(f"project mentions: {n}")
    for r in conn.execute("SELECT town,count(*),sum(units) FROM projects GROUP BY town ORDER BY 2 DESC LIMIT 15"): print(r)


if __name__ == "__main__":
    conn = sqlite3.connect(HDB); conn.executescript(SCHEMA)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if cmd == "fetch": fetch(conn)
    elif cmd == "projects": projects(conn)
