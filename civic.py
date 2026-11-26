"""Town records pilot (NH Civic Tracker, phase 1): per-town pages built from the meeting database.

Each pilot town gets
  - Ask the records: a search box over the last 12 months of minutes and agendas. Every result is a quoted
    passage with a link to the source document. No generated answers: no source, no answer.
  - This week: meetings in the last 14 days and the next 30, by board, with draft minutes labeled.
  - Coverage: what was collected, when it last updated, and the known gaps.
Called from site.py; writes docs/civic/index.html, docs/civic/<town>/index.html and docs/civic/<town>/records.json.
"""
import datetime as dt, hashlib, json, os, re

CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "civic.json")
SEARCH_DAYS = 365          # how far back the search index reaches
MAX_CHARS = 6_000_000      # per-town cap on indexed text; oldest documents drop first
PASSAGE = 700              # target passage length in characters
AGENDA_CHARS = 4000        # agendas repeat boilerplate; index only the top of each
DRAFT = re.compile(r"\b(draft|unapproved|not yet approved|subject to approval)\b", re.I)


def clean_title(t):
    """Crawled titles are 'link text | row text' and often repeat themselves; keep the distinct parts."""
    t = re.sub(r"\s+", " ", t or "")
    t = re.sub(r"\s*[—-]\s*Posted [A-Z][a-z]{2} \d{1,2}, \d{4} \d{1,2}:\d{2} [AP]M", "", t)       # CivicPlus "— Posted Sep 24, 2026 11:00 AM"
    t = re.sub(r"\s*(Download\s*▼.*?)(?=\||$)|\s*Previous Versions", "", t)                         # CivicPlus link furniture
    parts = []
    for p in re.split(r"\s*\|\s*", t):
        p = p.strip(" ·—-")
        if p and not any(p.lower() in q.lower() for q in parts): parts = [q for q in parts if q.lower() not in p.lower()] + [p]
    return " · ".join(parts)[:160]


def load_cfg():
    return json.load(open(CFG, encoding="utf8"))


def passages(text):
    """Split on sentence ends into passages of about PASSAGE characters."""
    text = re.sub(r"\s+", " ", text).strip()
    out, cur = [], ""
    for s in re.split(r"(?<=[.;:?!])\s+", text):
        if len(cur) + len(s) > PASSAGE and cur:
            out.append(cur.strip()); cur = ""
        while len(s) > PASSAGE * 2:  # run-on text with no sentence breaks
            out.append(s[:PASSAGE]); s = s[PASSAGE:]
        cur += " " + s
    if cur.strip(): out.append(cur.strip())
    return [p for p in out if len(p) > 40]


def town_data(conn, town, today):
    lo, hi = (today - dt.timedelta(SEARCH_DAYS)).isoformat(), (today + dt.timedelta(60)).isoformat()
    rows = conn.execute("""SELECT d.id,d.board,d.doc_type,d.meeting_date,d.title,d.url,d.sha256,x.text FROM documents d
        JOIN doc_text x ON x.id=d.id WHERE d.town=? AND d.meeting_date BETWEEN ? AND ? AND d.error IS NULL
        AND d.doc_type IN ('minutes','agenda','warrant') AND length(x.text)>200
        ORDER BY d.meeting_date DESC, length(d.url)""", (town, lo, hi)).fetchall()
    docs, ps, seen, used = [], [], set(), 0
    for _id, board, typ, date, title, url, sha, text in rows:
        key = hashlib.sha1(re.sub(r"\W+", "", text[:3000]).lower().encode()).hexdigest()
        if sha in seen or key in seen: continue  # the same record posted at several URLs, or as both HTML and PDF
        seen.update((sha, key))
        body = text if typ != "agenda" else text[:AGENDA_CHARS]
        if used + len(body) > MAX_CHARS: break
        used += len(body)
        draft = int(typ == "minutes" and bool(DRAFT.search(text[:300])))  # the header, not "approve the draft minutes of..."
        docs.append([date, board, typ, clean_title(title), url, draft])
        ps.extend([len(docs) - 1, p] for p in passages(body))
    return {"town": town, "from": lo, "docs": docs, "p": ps}


def coverage(conn, town, today):
    hi = (today + dt.timedelta(60)).isoformat()
    tot, since, latest, mins, ocr = conn.execute("""SELECT count(*), sum(meeting_date>='2023-07-01'),
        max(CASE WHEN meeting_date<=? THEN meeting_date END), sum(doc_type='minutes'), sum(needs_ocr=1)
        FROM documents WHERE town=? AND error IS NULL""", (hi, town)).fetchone()
    boards = conn.execute("SELECT board,count(*) FROM documents WHERE town=? AND error IS NULL AND meeting_date>='2023-07-01' GROUP BY 1 ORDER BY 2 DESC", (town,)).fetchall()
    crawled = (conn.execute("SELECT crawled_at,crawl_status FROM towns WHERE name=?", (town,)).fetchone() or (None, None))
    return dict(total=tot or 0, since=since or 0, latest=latest, minutes=mins or 0, ocr=ocr or 0, boards=boards,
                crawled=(crawled[0] or "")[:10], status=crawled[1])


def week(conn, town, today):
    lo, hi = (today - dt.timedelta(14)).isoformat(), (today + dt.timedelta(30)).isoformat()
    out, seen = [], set()
    for board, typ, date, title, url, sha, head in conn.execute("""SELECT d.board,d.doc_type,d.meeting_date,d.title,d.url,d.sha256,
            substr(x.text,1,300) FROM documents d LEFT JOIN doc_text x ON x.id=d.id WHERE d.town=? AND d.meeting_date BETWEEN ? AND ?
            AND d.error IS NULL ORDER BY d.meeting_date DESC, length(d.url)""", (town, lo, hi)):
        if sha in seen: continue
        seen.add(sha)
        out.append(dict(board=board, type=typ, date=date, title=title, url=url,
                        draft=typ == "minutes" and bool(DRAFT.search(head or ""))))
    return out


def build(conn, out_dir, page, write, slug, e, BOARD, report_url):
    cfg = load_cfg()
    today = dt.date.today()
    cards = []
    for town in cfg["towns"]:
        s = slug(town)
        searchable = town in cfg["pilot"]  # search index only for pilot towns, to keep the weekly commit small
        data = town_data(conn, town, today) if searchable else {"docs": [], "from": ""}
        if searchable: write(f"civic/{s}/records.json", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        cov, wk = coverage(conn, town, today), week(conn, town, today)
        gap = cfg.get("gaps", {}).get(town, "")
        stale = cov["latest"] and cov["latest"] < (today - dt.timedelta(45)).isoformat()
        cards.append((town, s, cov, len(data["docs"]), len(wk), gap, stale))

        past = [m for m in wk if (m["date"] or "") <= today.isoformat()]
        nxt = [m for m in wk if (m["date"] or "") > today.isoformat()]
        def mrow(m):
            tag = '<span class="tag draft">Draft minutes</span>' if m["draft"] else ""
            return f"""<li><span class="d">{e(m["date"])}</span><span class="b">{e(BOARD.get(m["board"], m["board"]))}</span>
<a href="{e(m["url"])}" target="_blank" rel="noopener">{e(m["type"].title())}: {e(clean_title(m["title"])[:120])}</a>{tag}</li>"""
        blist = ", ".join(f"{e(BOARD.get(b, b))} {n:,}" for b, n in cov["boards"][:8])
        warn = f'<p class="cwarn">{e(gap)}</p>' if gap else ""
        if stale: warn += f'<p class="cwarn">The newest document collected is from {e(cov["latest"])}. Recent meetings for {e(town)} are missing until the crawler catches up.</p>'
        examples = "".join(f'<button type="button" class="ex">{e(q)}</button>' for q in cfg.get("examples", {}).get(town, cfg["default_examples"]))
        ask = f"""<section class="ask"><h2>Ask the records</h2>
<form id="askf" role="search"><input id="q" type="search" placeholder="e.g. data center zoning, budget vote, Route 3" aria-label="Search {e(town)} meeting records" autocomplete="off">
<select id="fb" aria-label="Board"><option value="">All boards</option></select><button type="submit">Search</button></form>
<div class="exs">Try: {examples}</div>
<p class="note" id="astat">Loading {len(data["docs"]):,} documents…</p><div id="ares" class="ares" aria-live="polite"></div></section>""" if searchable else ""
        lede = (f"Search what {e(town)}'s boards said and decided over the last year, straight from the posted minutes and agendas. Every result is a quote with a link to the document it came from."
                if searchable else f"What {e(town)}'s boards have on the calendar and what the collected record covers. Search opens for {e(town)} when it joins the pilot.")
        body = f"""<header class="hd"><div class="eyebrow">Town records · {"pilot" if searchable else "preview"}</div><h1>{e(town)}</h1>
<p class="lede">{lede}</p>{warn}</header>
{ask}
<section><h2>This week</h2>
<div class="civtwo"><div><h3 class="sub">Last 14 days</h3><ul class="mlist">{"".join(mrow(m) for m in past) or '<li class="empty">No meetings collected in the last 14 days.</li>'}</ul></div>
<div><h3 class="sub">Coming up (next 30 days)</h3><ul class="mlist">{"".join(mrow(m) for m in reversed(nxt)) or '<li class="empty">No upcoming agendas posted yet.</li>'}</ul></div></div></section>
<section><h2>What this covers</h2>
<div class="stats"><div><b>{cov["since"]:,}</b><span>documents since July 2023</span></div><div><b>{cov["minutes"]:,}</b><span>sets of minutes</span></div>
<div><b>{e(cov["latest"] or "?")}</b><span>newest meeting date</span></div><div><b>{e(cov["crawled"] or "?")}</b><span>last checked</span></div></div>
<p class="note">By board: {blist or "none"}. {cov["ocr"]:,} scanned PDFs are waiting for text recognition and are not searchable yet. {f'The search covers minutes and agendas from {e(data["from"])} on. ' if searchable else ""}Minutes marked "Draft" have not been approved by the board yet.</p>
<p class="note"><a href="{e(report_url(town))}" target="_blank" rel="noopener">Report an error</a> · <a href="../../towns/{s}/index.html">{e(town)} topic page</a> · <a href="../index.html">All pilot towns</a></p></section>
""" + (f"""<script>window.CIVIC={{town:{json.dumps(town)},boards:{json.dumps(BOARD)},report:{json.dumps(report_url(town))}}};</script><script src="../../assets/civic.js?v={today:%Y%m%d}"></script>""" if searchable else "")
        write(f"civic/{s}/index.html", page(f"{town} meeting records · Granite Docket", 2, body, f"Search {town}, NH meeting minutes and agendas"))

    rows = "".join(f"""<a class="tc{" civpilot" if t[0] in cfg["pilot"] else ""}" href="{t[1]}/index.html"><b>{e(t[0])}</b><small>{f"{t[3]:,} docs searchable" if t[0] in cfg["pilot"] else "preview"} · {t[4]} recent or upcoming{" · gaps" if (t[5] or t[6]) else ""}</small></a>""" for t in cards)
    body = f"""<header class="hd"><div class="eyebrow">Pilot</div><h1>Town records</h1>
<p class="lede">Search a town's minutes and agendas from the last year, see what met this week, and check what the record covers. Answers are quotes from the records with links, never summaries. Highlighted towns are the first pilot.</p></header>
<section><div class="grid">{rows}</div><p class="note">Some cities post only part of their record online or ask crawlers to stay out; each town page says what is missing. Updated {today.isoformat()}.</p></section>"""
    write("civic/index.html", page("Town records · Granite Docket", 1, body, "Search New Hampshire town meeting records"))
    return cards
