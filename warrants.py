"""Town meeting warrant guide: every article in a town's posted warrant, with cost, recommendations and vote rule.

  docs/civic/warrants/index.html          every town with a parsed warrant for the season
  docs/civic/warrants/<town>/index.html   the article-by-article guide

Season: the March town meeting year. From December on, the guide looks for next year's warrants and falls back to
the current year's until a town posts one. Everything is parsed from the posted PDF text, so each page links the
source and says the reading is automatic. Called from site.py.

  python warrants.py Bow     # print the parse for one town (debugging)
"""
import datetime as dt, json, os, re, sqlite3, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NOISE = re.compile(r"overvote|undervote|election results|accounts payable|check warrant|payroll|manifest|capital improvement plan|newsletter|sample ballot|results of|MS[- ]?(636|737|DTB)", re.I)
SCHOOL = re.compile(r"school district|school board|cooperative school", re.I)
ART = re.compile(r"(?:^|\n)[ \t]*(?:SPECIAL[ \t]+)?(?:WARRANT[ \t]+)?ARTICLE[ \t]*(?:#[ \t]*|NO\.?[ \t]*)?(\d{1,3}|[IVXL]{1,6})\b[ \t]*[.:\-–—]*[ \t]*", re.I)
NUM = re.compile(r"(?:^|\n)[ \t]*(\d{1,2})\.\s+(?=(?:To see if|To choose|To hear|To transact|To raise|Shall|Are you in favor|By petition))", re.I)
MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\s,\d{3})*(?:\.\d{2})?)")
PAREN = re.compile(r"dollars\s*\(\s*\$\s?([\d,]{3,}(?:\.\d{2})?)\s*\)", re.I)
TOTAL = re.compile(r"totaling\D{0,10}\$\s?(\d[\d,]*(?:\s,\d{3})*(?:\.\d{2})?)", re.I)
SUM = re.compile(r"(?:sum of|totaling|total of|amount of|appropriate)\D{0,40}?\$\s?(\d[\d,]*(?:\s,\d{3})*(?:\.\d{2})?)", re.I)
DEFAULT = re.compile(r"default budget shall be\D{0,10}\$\s?(\d[\d,]*(?:\s,\d{3})*(?:\.\d{2})?)", re.I)
REC = re.compile(r"\(?\s*(not\s+)?recommended\s+by\s+(?:the\s+)?(select\s*board|board\s+of\s+selectmen|selectmen|select\s+board|town\s+council|budget\s+committee|planning\s+board|school\s+board)[^)\n\d]{0,40}(\d{1,2}\s*-\s*\d{1,2}(?:\s*-\s*\d{1,2})?)?", re.I)
REC2 = re.compile(r"(?:the\s+)?(select\s*board|board\s+of\s+selectmen|selectmen|town\s+council|budget\s+committee|planning\s+board)\s+(recommends|does\s+not\s+recommend)[^.\n\d]{0,40}(\d{1,2}\s*-\s*\d{1,2}(?:\s*-\s*\d{1,2})?)?", re.I)
VOTE = re.compile(r"\(?\s*(majority|2\s*/\s*3|two[- ]thirds|3\s*/\s*5|three[- ]fifths)[^)\n]{0,30}vote\s+required\s*\)?", re.I)
PETITION = re.compile(r"\bby\s+petition\b|\bpetitioned\s+article\b|\bsubmitted\s+by\s+petition\b", re.I)
DATE = re.compile(r"(January|February|March|April|May|June)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)", re.I)
TAGS = [("Operating budget", r"as an operating budget|(raise and appropriate|appropriate).{0,60}(operating budget|general municipal operations)"), ("Zoning", r"zoning (ordinance|amendment)|amend(ment)?\s+(to\s+)?the\s+(zoning|land use)|are you in favor of the adoption of amendment"),
        ("Bond or loan", r"\bbonds?\b|\bnotes?\b in accordance with the provisions of the municipal finance act|borrow"),
        ("Capital reserve", r"capital reserve|expendable trust"), ("Contract", r"collective bargaining|cost items"),
        ("Energy", r"\bsolar\b|energy|electric vehicle|battery"), ("Data center", r"data cent(er|re)"), ("Housing", r"housing|dwelling unit"),
        ("Officers", r"to choose all necessary|necessary town officers")]
ROLE = {"select": "Select board", "selectmen": "Select board", "board of selectmen": "Select board", "town council": "Town council",
        "budget committee": "Budget committee", "planning board": "Planning board", "school board": "School board"}


def money(s):
    return float(re.sub(r"[\s,]", "", s))


def role(s):
    s = re.sub(r"\s+", " ", s.lower())
    for k, v in ROLE.items():
        if s.startswith(k): return v
    return s.title()


def split_articles(text):
    marks = [(m.start(), m.end(), m.group(1)) for m in ART.finditer(text)]
    if sum(n.isdigit() for _, _, n in marks) >= 3:
        marks = [mk for mk in marks if mk[2].isdigit()]  # roman numerals here are ordinance sections quoted inside an article
    if len(marks) < 3:
        marks = [(m.start(), m.end(), m.group(1)) for m in NUM.finditer(text)]
    out = []
    for i, (s, e, n) in enumerate(marks):
        body = text[e:marks[i + 1][0] if i + 1 < len(marks) else min(len(text), e + 3000)]
        out.append((n, body.strip()))
    # keep the first run of each article number (tables of contents and recaps repeat them)
    seen, res = set(), []
    for n, b in out:
        if n.upper() in seen or len(b) < 25: continue
        seen.add(n.upper()); res.append((n, b))
    return res


def parse_article(n, body):
    flat = re.sub(r"\s+", " ", body).strip()
    lines = [l.strip() for l in body.split("\n") if l.strip()]
    head = lines[0] if lines and len(lines[0]) < 70 and not re.match(r"(to see|shall|are you|to choose|to hear|to raise)", lines[0], re.I) else ""
    start = flat[len(head):].strip() if head else flat
    m = re.search(r"(To see if|Shall|Are you in favor|To choose|To hear|To transact|To raise)[^?]{0,600}?[?.](?=\s|$)", start, re.I)
    question = (m.group(0) if m else start[:400]).strip()
    approp = re.search(r"appropriat|operating budget", flat[:1500], re.I)  # a tax credit or fee amount is not a cost
    s = (TOTAL.search(flat[:1500]) or PAREN.search(flat[:1500]) or SUM.search(flat[:1500]) or MONEY.search(flat[:1500])) if approp else None
    recs = []
    for r in REC.finditer(flat):
        recs.append((role(r.group(2)), "Not recommended" if r.group(1) else "Recommended", re.sub(r"\s", "", r.group(3) or "")))
    for r in REC2.finditer(flat):
        recs.append((role(r.group(1)), "Not recommended" if "not" in r.group(2).lower() else "Recommended", re.sub(r"\s", "", r.group(3) or "")))
    uniq = []
    for rc in recs:
        if rc[0] not in [u[0] for u in uniq]: uniq.append(rc)
    v = VOTE.search(flat)
    tags = [t for t, rx in TAGS if re.search(rx, flat[:700], re.I)]
    d = DEFAULT.search(flat)
    return dict(n=n, head=head[:80], question=question[:600], amount=money(s.group(1)) if s else None,
                default=money(d.group(1)) if d else None, recs=uniq, vote=(v.group(1).replace(" ", "") + " vote") if v else "",
                petition=bool(PETITION.search(flat)), tags=tags)


def season_year(today):
    return today.year + 1 if today.month >= 12 else today.year


def pick(conn, town, year):
    """The fullest town (not school) warrant posted for the season."""
    best = None
    for doc_id, date, title, url, text in conn.execute("""SELECT d.id,d.meeting_date,d.title,d.url,x.text FROM documents d JOIN doc_text x ON x.id=d.id
            WHERE d.town=? AND d.doc_type='warrant' AND d.meeting_date BETWEEN ? AND ? AND d.error IS NULL AND length(x.text)>1500""",
                                                       (town, f"{year - 1}-11-01", f"{year}-06-30")):
        if NOISE.search(title or "") or NOISE.search(text[:400]) or SCHOOL.search(text[:1200]): continue
        arts = split_articles(text)
        if len(arts) < 3 or len(re.findall(r"to see if|shall the|are you in favor", text, re.I)) < 3: continue
        key = (len(arts), date or "", "revised" in (title or "").lower() or "deliberative" in (title or "").lower())
        if not best or key > best[0]: best = (key, doc_id, date, title, url, text, arts)
    if not best: return None
    _, doc_id, date, title, url, text, arts = best
    dates = sorted({dt.date(int(y), ["january", "february", "march", "april", "may", "june"].index(mo.lower()) + 1, int(d))
                    for mo, d, y in DATE.findall(text[:6000]) if int(y) == year and 1 <= int(d) <= 31 and mo.lower() in ("january", "february", "march", "april", "may")})
    return dict(town=town, year=year, doc_id=doc_id, date=date, title=title, url=url, dates=[f"{d:%B} {d.day}" for d in dates][:4],
                articles=[parse_article(n, b) for n, b in arts])


def guides(conn, today=None):
    today = today or dt.date.today()
    year = season_year(today)
    towns = [r[0] for r in conn.execute("SELECT DISTINCT town FROM documents WHERE doc_type='warrant' ORDER BY 1")]
    out = []
    for t in towns:
        g = pick(conn, t, year) or (pick(conn, t, year - 1) if year > today.year or today.month < 4 else None)
        if g: out.append(g)
    return out, year


def fmt(x):
    return f"${x:,.0f}" if x is not None else ""


def build(conn, page, write, slug, e):
    gs, year = guides(conn)
    rows = []
    for g in gs:
        arts = g["articles"]
        total = None
        ops = [a for a in arts if "Operating budget" in a["tags"] and a["amount"]]
        op = next((a for a in ops if not re.search(r"sewer|water|light|electric|enterprise|recreation|ambulance", a["head"] + a["question"][:160], re.I)), None)
        nums = [int(a["n"]) for a in arts if a["n"].isdigit()]
        partial = (nums and len(arts) < 0.6 * max(nums)) or not any(a["amount"] for a in arts)
        total = sum(a["amount"] or 0 for a in arts if "Operating budget" not in a["tags"])
        pet = sum(a["petition"] for a in arts)
        zon = sum("Zoning" in a["tags"] for a in arts)
        cur = g["year"] == year
        rows.append((g, total, op, pet, zon, cur, partial))

        def recs(a):
            if not a["recs"]: return '<span class="muted">No recommendation found</span>'
            return " · ".join(f'<span class="{"rno" if r[1].startswith("Not") else "ryes"}">{e(r[1])} by {e(r[0])}{" (" + e(r[2]) + ")" if r[2] else ""}</span>' for r in a["recs"])
        trs = "".join(f"""<tr><td class="n">{e(a["n"])}</td><td><b>{e(a["head"])}</b>{"<br>" if a["head"] else ""}<span class="q">{e(a["question"][:420])}{"…" if len(a["question"]) > 420 else ""}</span>
<div class="atags">{"".join(f'<span class="chip">{e(t)}</span>' for t in a["tags"])}{'<span class="chip pet">By petition</span>' if a["petition"] else ""}</div></td>
<td class="n">{fmt(a["amount"])}{"<br><small>default " + fmt(a["default"]) + "</small>" if a["default"] else ""}</td><td>{recs(a)}</td><td>{e(a["vote"])}</td></tr>""" for a in arts)
        when = ("Dates in the warrant: " + ", ".join(g["dates"])) if g["dates"] else ""
        note = (f'<p class="cwarn">Only part of this warrant could be read automatically ({len(arts)} articles found). Use the source warrant for the rest.</p>' if partial else "") + ("" if cur else f'<p class="cwarn">{e(g["town"])} has not posted a {year} warrant yet. This is the {g["year"]} warrant, shown for reference until the new one appears.</p>')
        body = f"""<header class="hd"><div class="eyebrow">Town meeting {g["year"]}</div><h1>{e(g["town"])} warrant guide</h1>
<p class="lede">Every article on {e(g["town"])}'s {g["year"]} town warrant: what it asks, what it costs, and how the select board and budget committee recommended it.</p>{note}
<p class="note">{e(when) or "Meeting dates: see the warrant."} · <a href="{e(g["url"])}" target="_blank" rel="noopener">Source warrant</a> · <a href="../index.html">All towns</a></p></header>
<section><div class="stats"><div><b>{len(arts)}</b><span>articles</span></div><div><b>{fmt(op["amount"]) if op else "?"}</b><span>operating budget</span></div>
<div><b>{fmt(total)}</b><span>other appropriations</span></div><div><b>{pet}</b><span>by petition</span></div></div>
<div class="tablebox"><table class="wtab"><thead><tr><th>#</th><th>Article</th><th>Amount</th><th>Recommendations</th><th>Vote</th></tr></thead><tbody>{trs}</tbody></table></div>
<p class="note">Read automatically from the posted warrant, so amounts, recommendations and dates can be missed or misread. The source warrant is the authority. <a href="https://github.com/jhitchco/granite-docket/issues/new?labels=correction&title=Warrant%20correction%3A%20{e(g["town"])}" target="_blank" rel="noopener">Report an error</a>.</p></section>"""
        write(f"civic/warrants/{slug(g['town'])}/index.html", page(f"{g['town']} {g['year']} town warrant guide · Granite Docket", 3, body,
                                                               f"Article-by-article guide to the {g['town']}, NH {g['year']} town warrant"))
    rows.sort(key=lambda r: (not r[5], r[0]["town"]))
    ncur = sum(r[5] for r in rows)
    trs = "".join(f"""<tr><td><a href="{slug(g["town"])}/index.html">{e(g["town"])}</a></td><td class="n">{g["year"]}</td><td>{e(", ".join(g["dates"]))}</td>
<td class="n">{len(g["articles"])}{" (partial)" if partial else ""}</td><td class="n">{fmt(op["amount"]) if op else ""}</td><td class="n">{fmt(total)}</td><td class="n">{pet}</td><td class="n">{zon}</td></tr>""" for g, total, op, pet, zon, cur, partial in rows)
    body = f"""<header class="hd"><div class="eyebrow">Town meeting {year}</div><h1>Warrant guide</h1>
<p class="lede">What every New Hampshire town is voting on this town meeting season, article by article: cost, recommendations and the vote it takes.</p>
<p class="note">{ncur} towns have posted a {year} warrant so far.{f" Towns usually post in late January and February; until then each town shows its {year - 1} warrant for reference." if ncur < len(rows) else ""} Read automatically from the posted warrants: check the source before relying on a figure.</p></header>
<section><div class="tablebox"><table><thead><tr><th>Town</th><th>Year</th><th>Dates in the warrant</th><th>Articles</th><th>Operating budget</th><th>Other appropriations</th><th>Petitions</th><th>Zoning</th></tr></thead><tbody>{trs}</tbody></table></div></section>"""
    write("civic/warrants/index.html", page(f"{year} town warrant guide · Granite Docket", 2, body, "New Hampshire town meeting warrants, article by article"))
    return rows


if __name__ == "__main__":
    conn = sqlite3.connect(os.path.join(ROOT, "nh_meetings.db"))
    town = sys.argv[1]
    today = dt.date.today()
    g = pick(conn, town, season_year(today)) or pick(conn, town, season_year(today) - 1)
    print(json.dumps(g and {k: v for k, v in g.items() if k != "articles"}, indent=1))
    for a in (g or {}).get("articles", []):
        print(a["n"], "|", a["head"], "|", fmt(a["amount"]), "|", a["recs"], "|", a["vote"], "|", a["tags"], "|", a["question"][:120])
