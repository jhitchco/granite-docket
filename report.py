"""Keyword reporting layer over nh_meetings.db.

  python report.py                 # scan all docs, write hits table + hits.csv + report.html
  python report.py --topics nuclear
Edit keywords.json to add topics/terms; rerun is idempotent (hits table is rebuilt).
"""
import argparse, csv, html, json, os, re, sqlite3, datetime as dt

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "nh_meetings.db")
CTX = 220  # chars of context each side of a match


def compile_cfg(cfg, only):
    out = {}
    for key, t in cfg["topics"].items():
        if only and key not in only: continue
        out[key] = dict(label=t["label"],
                        strong=re.compile("|".join(f"(?:{x})" for x in t["strong"]), re.I),
                        weak=re.compile("|".join(f"(?:{x})" for x in t["weak"]), re.I) if t["weak"] else None,
                        exclude=re.compile("|".join(f"(?:{x})" for x in t["exclude"]), re.I) if t["exclude"] else None)
    return out


def snippets(text, rx, limit=6):
    out, last = [], -10**9
    for m in rx.finditer(text):
        if m.start() - last < CTX: continue  # merge matches that share a window
        last = m.start()
        a, b = max(0, m.start() - CTX), min(len(text), m.end() + CTX)
        out.append({"pre": re.sub(r"\s+", " ", text[a:m.start()]), "hit": m.group(0), "post": re.sub(r"\s+", " ", text[m.end():b])})
        if len(out) >= limit: break
    return out


def scan(conn, topics, zctx):
    conn.executescript("""DROP TABLE IF EXISTS hits;
      CREATE TABLE hits(doc_id INTEGER, topic TEXT, n_strong INTEGER, n_weak INTEGER, terms TEXT, zoning_context INTEGER, score REAL, snippets TEXT);""")
    rows = conn.execute("""SELECT d.id, t.text FROM documents d JOIN doc_text t ON t.id=d.id""").fetchall()
    conn.commit()
    n = 0
    for doc_id, text in rows:
        if not text: continue
        for key, tp in topics.items():
            body = tp["exclude"].sub(" ", text) if tp["exclude"] else text
            strong = list(tp["strong"].finditer(body))
            if not strong: continue
            weak = list(tp["weak"].finditer(body)) if tp["weak"] else []
            terms = sorted({m.group(0).lower() for m in strong})
            z = sum(1 for w in zctx if re.search(w, body, re.I))
            # distinct-term variety and zoning context matter more than raw repetition
            score = round(min(len(strong), 20) + 3 * len(terms) + 0.5 * min(len(weak), 10) + 1.5 * z, 1)
            rx = re.compile(tp["strong"].pattern + ("|" + tp["weak"].pattern if tp["weak"] else ""), re.I)
            sn = snippets(body, tp["strong"]) or snippets(body, rx)
            conn.execute("INSERT INTO hits VALUES(?,?,?,?,?,?,?,?)", (doc_id, key, len(strong), len(weak), ", ".join(terms), z, score, json.dumps(sn)))
            n += 1
    conn.commit()
    return n


def export(conn, topics):
    q = """SELECT h.topic, d.town, tw.county, d.board, d.doc_type, d.meeting_date, d.title, d.url, d.local_path,
                  h.n_strong, h.terms, h.zoning_context, h.score, h.snippets, d.id
           FROM hits h JOIN documents d ON d.id=h.doc_id LEFT JOIN towns tw ON tw.name=d.town
           ORDER BY h.score DESC"""
    rows = conn.execute(q).fetchall()
    with open(os.path.join(ROOT, "hits.csv"), "w", newline="", encoding="utf8") as f:
        w = csv.writer(f)
        w.writerow(["topic", "town", "county", "board", "doc_type", "meeting_date", "title", "url", "local_file", "matches", "terms", "zoning_context_terms", "score", "first_snippet"])
        for r in rows:
            sn = json.loads(r[13]); first = (sn[0]["pre"] + "[[" + sn[0]["hit"] + "]]" + sn[0]["post"]) if sn else ""
            w.writerow(list(r[:13]) + [first])
    cov = conn.execute("SELECT name, county, population, crawl_status, docs, website, notes FROM towns ORDER BY population DESC").fetchall()
    totals = conn.execute("SELECT count(*), count(DISTINCT town), min(meeting_date), max(meeting_date), sum(needs_ocr) FROM documents WHERE error IS NULL").fetchone()
    data = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "topics": {k: v["label"] for k, v in topics.items()},
        "totals": dict(zip(["docs", "towns_with_docs", "min_date", "max_date", "needs_ocr"], totals)),
        "hits": [dict(topic=r[0], town=r[1], county=r[2], board=r[3], type=r[4], date=r[5], title=r[6], url=r[7],
                      n=r[9], terms=r[10], z=r[11], score=r[12], snippets=json.loads(r[13])) for r in rows],
        "coverage": [dict(town=c[0], county=c[1], pop=c[2], status=c[3], docs=c[4], site=c[5], notes=c[6]) for c in cov],
    }
    fb = os.path.join(ROOT, "search_fallback.json")  # web-search findings for towns the crawler can't reach
    data["fallback"] = json.load(open(fb, encoding="utf8")) if os.path.exists(fb) else {"searched_towns": [], "findings": []}
    tpl = open(os.path.join(ROOT, "report_template.html"), encoding="utf8").read()
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    open(os.path.join(ROOT, "report.html"), "w", encoding="utf8").write(tpl.replace("/*__DATA__*/null", blob))
    return len(rows)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--topics")
    a = ap.parse_args()
    cfg = json.load(open(os.path.join(ROOT, "keywords.json"), encoding="utf8"))
    topics = compile_cfg(cfg, set(a.topics.split(",")) if a.topics else None)
    conn = sqlite3.connect(DB, timeout=60)
    n = scan(conn, topics, cfg["zoning_context"])
    m = export(conn, topics)
    print(f"{n} topic hits across documents; report.html + hits.csv written ({m} rows)")
    for r in conn.execute("SELECT h.topic, d.town, count(*), max(h.score) FROM hits h JOIN documents d ON d.id=h.doc_id GROUP BY 1,2 ORDER BY 1, 4 DESC"):
        print(r)


if __name__ == "__main__":
    main()
