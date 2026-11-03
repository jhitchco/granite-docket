"""Static site generator for Granite Docket (GitHub Pages, served from docs/).

  python report.py && python site.py
Pages: docs/index.html, docs/topics/<topic>/index.html, docs/towns/<town>/index.html, docs/coverage/index.html
"""
import datetime as dt, html, json, os, re, shutil, sqlite3
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "docs")
NAME = "Granite Docket"
MIN_SCORE = 8          # weaker single passing mentions stay in hits.csv but off the site
WINDOW = 90            # days for "recent movement"
TOPIC_INFO = {
    "data_center": ("Data centers", "data-centers",
                    "Proposals, moratoria and zoning for data centers, hyperscale and colocation facilities, and crypto-mining operations."),
    "nuclear": ("Nuclear & micro-nuclear", "nuclear",
                "Mentions of nuclear energy, microreactors, small modular and advanced reactors in local meetings, ordinances and warrants."),
}
BOARD = {"planning": "Planning board", "zoning": "Zoning / ZBA", "select_board": "Select board / council", "town_meeting": "Town meeting / warrant",
         "conservation": "Conservation commission", "energy": "Energy committee", "economic_dev": "Economic development", "budget": "Budget / CIP",
         "heritage_historic": "Historic district", "school": "School", "other": "Other board"}
STATUS = {"done": "Crawled", "blocked_bot_challenge": "Bot challenge", "robots_disallowed": "robots.txt blocks crawlers",
          "no_website": "No website", "unreachable": "Unreachable", "error": "Crawl error", "crawling": "Partial crawl", "pending": "Queued"}
e = lambda s: html.escape(str(s if s is not None else ""))
slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def page(title, depth, body, desc=""):
    up = "../" * depth
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;800&family=IBM+Plex+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="{up}assets/site.css?v={dt.date.today():%Y%m%d}"></head><body>
<nav class="bar"><div class="in"><a class="brand" href="{up}index.html">{NAME}</a><span class="links"><a href="{up}topics/data-centers/index.html">Data centers</a><a href="{up}topics/nuclear/index.html">Nuclear</a><a href="{up}housing/index.html">Housing</a><a href="{up}coverage/index.html">Coverage</a></span></div></nav>
<main class="wrap">{body}</main>
<footer class="wrap foot">Built from agendas, minutes, packets and warrants posted by New Hampshire municipalities. Excerpts are quoted from public records; open the linked document before relying on one. Topic definitions and scoring are ours.</footer>
</body></html>"""


def write(rel, text):
    p = os.path.join(OUT, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf8").write(text)


def snip(s):
    return f'<p class="snip">…{e(s["pre"])}<mark>{e(s["hit"])}</mark>{e(s["post"])}…</p>'


def event_html(ev, depth, show_town=True):
    up = "../" * depth
    town = f'<a class="town" href="{up}towns/{slug(ev["town"])}/index.html">{e(ev["town"])}</a>' if show_town else ""
    chip = f'<span class="chip {ev["topic"]}">{e(TOPIC_INFO[ev["topic"]][0])}</span>'
    src = '<span class="tag">web search</span>' if ev.get("fallback") else ""
    body = "".join(snip(s) for s in ev.get("snippets", [])[:2]) if ev.get("snippets") else f'<p class="snip">{e(ev.get("summary"))}</p>'
    return f"""<article class="ev"><div class="top">{town}{chip}{src}<span class="date">{e(ev.get("date") or "date unknown")}</span></div>
<div class="meta">{e(BOARD.get(ev.get("board"), ev.get("board") or ""))} · {e(ev.get("type") or "")}{" · terms: " + e(ev["terms"]) if ev.get("terms") else ""}</div>
<a class="doc" href="{e(ev["url"])}" target="_blank" rel="noopener">{e((ev.get("title") or ev["url"]).replace(" | ", " · ")[:170])}</a>{body}</article>"""


def main():
    conn = sqlite3.connect(os.path.join(ROOT, "nh_meetings.db"), timeout=60)
    today = dt.date.today()
    cut, cut2 = (today - dt.timedelta(WINDOW)).isoformat(), (today - dt.timedelta(2 * WINDOW)).isoformat()
    events = []
    for r in conn.execute("""SELECT h.topic,d.town,d.board,d.doc_type,d.meeting_date,d.title,d.url,h.terms,h.score,h.snippets
                             FROM hits h JOIN documents d ON d.id=h.doc_id WHERE h.score>=? AND h.zoning_context>0""", (MIN_SCORE,)):
        events.append(dict(topic=r[0], town=r[1], board=r[2], type=r[3], date=r[4], title=r[5], url=r[6], terms=r[7], score=r[8], snippets=json.loads(r[9])))
    fbp = os.path.join(ROOT, "search_fallback.json")
    if os.path.exists(fbp):
        for f in json.load(open(fbp, encoding="utf8"))["findings"]:
            events.append(dict(f, type=f.get("source_type", "").replace("_", " "), fallback=True, score=10))
    towns = {r[0]: dict(name=r[0], county=r[1], pop=r[2], status=r[3], docs=r[4] or 0, site=r[5], notes=r[6])
             for r in conn.execute("SELECT name,county,population,crawl_status,docs,website,notes FROM towns")}
    for t in json.load(open(os.path.join(ROOT, "towns.json"), encoding="utf8")):  # towns not crawled yet
        if t["name"] not in towns:
            c = t["cells"]
            towns[t["name"]] = dict(name=t["name"], county=re.sub(r"\s*\(.*", "", c[2]), pop=int(c[4].replace(",", "") or 0),
                                    status="pending", docs=0, site=t.get("final_url"), notes="")
    ndocs = dict(conn.execute("SELECT town,count(*) FROM documents WHERE error IS NULL GROUP BY town").fetchall())
    for t in towns.values(): t["docs"] = ndocs.get(t["name"], 0)
    total_docs = sum(ndocs.values())
    span = conn.execute("SELECT min(meeting_date),max(meeting_date) FROM documents WHERE meeting_date BETWEEN '2023-07-01' AND ?", (today.isoformat(),)).fetchone()

    by_tt = defaultdict(list)
    for ev in events: by_tt[(ev["topic"], ev["town"])].append(ev)
    for v in by_tt.values(): v.sort(key=lambda x: x.get("date") or "", reverse=True)

    if os.path.exists(OUT): shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, "assets"))
    shutil.copy(os.path.join(ROOT, "site.css"), os.path.join(OUT, "assets", "site.css"))
    open(os.path.join(OUT, ".nojekyll"), "w").close()

    def movement(evs):
        a = sum(1 for x in evs if (x.get("date") or "") >= cut)
        b = sum(1 for x in evs if cut2 <= (x.get("date") or "") < cut)
        if a and not b: trend = '<span class="tr up">new</span>'
        elif b: trend = f'<span class="tr {"up" if a > b else "dn" if a < b else "eq"}">{"▲" if a > b else "▼" if a < b else "▬"} {abs(a - b)}</span>'
        else: trend = ""
        return a, trend

    # ---- topic pages
    topic_cards = []
    for key, (label, tslug, desc) in TOPIC_INFO.items():
        rows = []
        for (tk, town), evs in by_tt.items():
            if tk != key: continue
            a, trend = movement(evs)
            rows.append((a, len(evs), town, evs, trend))
        rows.sort(key=lambda x: (-x[0], -x[1], x[2]))
        n_ev = sum(r[1] for r in rows); n_recent = sum(r[0] for r in rows)
        topic_cards.append((key, label, tslug, desc, len(rows), n_ev, n_recent, rows[:4]))
        table = "".join(f"""<li class="row"><a class="town" href="../../towns/{slug(town)}/index.html">{e(town)}</a>
<span class="num">{n} record{"s" if n != 1 else ""}</span><span class="num">{a} in {WINDOW} days</span>{trend}
<span class="latest">latest {e(evs[0].get("date") or "?")}: {e(((evs[0].get("title") or "").split(" | ")[0].strip() or BOARD.get(evs[0].get("board"), "") + " " + (evs[0].get("type") or ""))[:80])}</span></li>""" for a, n, town, evs, trend in rows)
        recent = sorted([ev for ev in events if ev["topic"] == key], key=lambda x: x.get("date") or "", reverse=True)[:60]
        body = f"""<header class="hd"><div class="eyebrow">Topic · New Hampshire · public record</div><h1>{e(label)}</h1><p class="lede">{e(desc)}</p></header>
<div class="stats"><div><b>{len(rows)}</b><span>towns on the record</span></div><div><b>{n_ev}</b><span>matching documents</span></div><div><b>{n_recent}</b><span>in the last {WINDOW} days</span></div></div>
<section><h2>Where it is on the record</h2><p class="note">Most recent movement first. A record is one agenda, minutes, packet or warrant that discusses the topic.</p><ol class="ledger">{table or '<li class="row">Nothing on the record yet.</li>'}</ol></section>
<section><h2>Latest documents</h2><div class="evs">{"".join(event_html(x, 2) for x in recent)}</div></section>"""
        write(f"topics/{tslug}/index.html", page(f"{label} in New Hampshire · {NAME}", 2, body, desc))

    # ---- town pages
    for t in towns.values():
        evs = sorted([ev for ev in events if ev["town"] == t["name"]], key=lambda x: x.get("date") or "", reverse=True)
        boards = conn.execute("SELECT board,count(*) FROM documents WHERE town=? AND error IS NULL GROUP BY 1 ORDER BY 2 DESC", (t["name"],)).fetchall()
        st = STATUS.get(t["status"], t["status"] or "Not crawled")
        btxt = ", ".join(f"{BOARD.get(b, b)} {n}" for b, n in boards[:8])
        site = f'<a href="{e(t["site"])}" target="_blank" rel="noopener">{e(re.sub(r"^https?://(www\.)?", "", t["site"] or "").rstrip("/"))}</a>' if t["site"] else "no municipal website"
        body = f"""<header class="hd"><div class="eyebrow">Town · {e(t["county"])} County · pop. {(t["pop"] or 0):,}</div><h1>{e(t["name"])}</h1>
<p class="lede">{len(evs)} matching record{"s" if len(evs) != 1 else ""} across {t["docs"]:,} meeting documents collected. Source: {site}. Crawl status: <span class="st {"ok" if t["status"] == "done" else "gap"}">{e(st)}</span>. <a href="../../housing/{slug(t["name"])}/index.html">New construction in {e(t["name"])}</a>.</p>
{f'<p class="note">Documents by board: {e(btxt)}.</p>' if btxt else ""}</header>
<div class="evs">{"".join(event_html(x, 2, show_town=False) for x in evs) or '<p class="empty">No mentions of the tracked topics in the documents collected for this town.</p>'}</div>"""
        write(f"towns/{slug(t['name'])}/index.html", page(f"{t['name']}, NH · {NAME}", 2, body, f"{t['name']} NH meeting records"))

    # ---- crawl progress bar (shown while a crawl is still running)
    cnt = defaultdict(int)
    for t in towns.values():
        st = t["status"]
        cnt["done" if st == "done" else "crawling" if st == "crawling" else "queued" if st == "pending" else "gap"] += 1
    ocr_left = conn.execute("SELECT count(*) FROM documents WHERE needs_ocr=1").fetchone()[0]
    ocr_done = conn.execute("SELECT count(*) FROM documents WHERE needs_ocr=2").fetchone()[0]
    seg = lambda k: f'<span class="seg {k}" style="width:{cnt[k] / len(towns) * 100:.2f}%"></span>'
    progress = "" if not (cnt["crawling"] or cnt["queued"] or ocr_left) else f"""<section class="progress" aria-label="Crawl progress">
<div class="ph"><b>Collection in progress</b><span>{cnt["done"]} towns crawled · {cnt["crawling"]} in progress · {cnt["queued"]} queued · {cnt["gap"]} can't be crawled automatically</span></div>
<div class="pbar">{seg("done")}{seg("crawling")}{seg("gap")}{seg("queued")}</div>
<div class="pnote">Scanned PDFs read by OCR: {ocr_done:,} done, {ocr_left:,} waiting. Results update about every 30 minutes until collection finishes · last update {dt.datetime.now():%b %d, %H:%M}.</div></section>"""

    # ---- coverage
    order = sorted(towns.values(), key=lambda t: (t["status"] == "done", -(t["pop"] or 0)))
    gaps = [t for t in towns.values() if t["status"] != "done"]
    rows = "".join(f"""<tr><td><a href="../towns/{slug(t["name"])}/index.html">{e(t["name"])}</a></td><td>{e(t["county"])}</td><td class="n">{(t["pop"] or 0):,}</td>
<td><span class="st {"ok" if t["status"] == "done" else "gap"}">{e(STATUS.get(t["status"], t["status"]))}</span></td><td class="n">{t["docs"]:,}</td><td>{e(t["notes"] or "")}</td></tr>""" for t in order)
    body = progress + f"""<header class="hd"><div class="eyebrow">Method</div><h1>Coverage</h1>
<p class="lede">All 234 New Hampshire municipalities, with the status of each crawl. {len(gaps)} could not be read automatically: their sites sit behind a bot challenge, ask crawlers to stay out, render only with JavaScript, or do not exist. Those towns were checked through search engines and news instead, and findings from that sweep are marked "web search".</p>
<p class="note">Collected: agendas, minutes, agenda packets, warrants and notices from meetings on or after 2024-01-01. Scanned PDFs without a text layer are not searched yet.</p></header>
<div class="tablebox"><table><thead><tr><th>Town</th><th>County</th><th>Pop. 2020</th><th>Status</th><th>Documents</th><th>Note</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    write("coverage/index.html", page(f"Coverage · {NAME}", 1, body))

    # ---- index
    tcards = "".join(f"""<a class="tcard" href="topics/{tslug}/index.html"><span class="chip {key}">{e(label)}</span><b>{nt} towns</b>
<span>{ne} documents · {nr} in the last {WINDOW} days</span><span class="lead">{e(", ".join(r[2] for r in top))}</span></a>""" for key, label, tslug, desc, nt, ne, nr, top in topic_cards)
    town_rows = []
    for t in sorted(towns.values(), key=lambda t: t["name"]):
        evs = [ev for ev in events if ev["town"] == t["name"]]
        a = sum(1 for x in evs if (x.get("date") or "") >= cut)
        chips = "".join(f'<span class="chip {k}">{sum(1 for x in evs if x["topic"] == k)}</span>' for k in TOPIC_INFO if any(x["topic"] == k for x in evs))
        cls = "tc hot" if evs else "tc"
        town_rows.append(f"""<a class="{cls}" href="towns/{slug(t["name"])}/index.html"><b>{e(t["name"])}</b><span class="cs">{chips}</span>
<small>{f"{a} in last {WINDOW} days" if a else ("on the record" if evs else ("not crawled" if t["status"] != "done" else f"{t['docs']:,} docs, no mentions"))}</small></a>""")
    body = f"""<header class="hd hero"><div class="eyebrow">New Hampshire · municipal public record</div><h1>{NAME}</h1>
<p class="lede">What New Hampshire's planning boards, zoning boards, select boards and town meetings have put on the record about data centers and nuclear energy. Read from the towns' own agendas, minutes and warrants.</p></header>
{progress}<div class="stats"><div><b>{total_docs:,}</b><span>meeting documents read</span></div><div><b>{sum(1 for t in towns.values() if t["status"] == "done")} / {len(towns)}</b><span>municipalities crawled</span></div>
<div><b>{len({ev["town"] for ev in events})}</b><span>towns on the record</span></div><div><b>{e(span[0] or "?")} → {e(span[1] or "?")}</b><span>meeting dates</span></div></div>
<section><h2>Topics</h2><div class="tcards">{tcards}</div></section>
<section><h2>Latest on the record</h2><div class="evs">{"".join(event_html(x, 0) for x in sorted(events, key=lambda x: x.get("date") or "", reverse=True)[:12])}</div></section>
<section><h2>All {len(towns)} municipalities</h2><p class="note">Highlighted towns have at least one matching record. Updated {today.isoformat()}.</p><div class="grid">{"".join(town_rows)}</div></section>"""
    write("index.html", page(NAME, 0, body, "New Hampshire municipal meetings on data centers and nuclear energy, from the towns' own records."))
    if os.path.exists(os.path.join(ROOT, "housing.db")):
        import housing_site
        housing_site.build(OUT, sorted(towns), page, write, slug, e)
    print(f"site written to {OUT}: {len(events)} events, {len(towns)} towns")


if __name__ == "__main__":
    main()
