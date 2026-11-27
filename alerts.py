"""Alerts: Atom feeds and digests for a town, a topic, or a town and topic.

Topics are the site topics in keywords.json (nuclear, data centers) plus the alert-only topics in
alerts_keywords.json (solar, battery storage, wind, transmission, housing). Alert hits are computed here over a
recent window and never written to the hits table or hits.csv, so the site's topic pages and Mettison's feed are
unchanged.

  docs/alerts/index.html                 sign-up page (feed links per topic, town, town + topic)
  docs/alerts/feeds/topic-<topic>.xml    statewide, one topic
  docs/alerts/feeds/energy-siting.xml    statewide, every energy and siting topic
  docs/alerts/feeds/town-<town>.xml      one town, every topic
  docs/alerts/feeds/<town>--<topic>.xml  one town, one topic
  docs/alerts/data.json                  every alert item in the window (for digests and email delivery)

  python alerts.py digest --period weekly [--town Bow] [--topic solar]   # text digest, ready for an email sender

Feeds are deterministic: entry ids and dates come from the documents, never from the build time.
Called from site.py.
"""
import argparse, datetime as dt, hashlib, json, os, re, sqlite3
from collections import defaultdict
from report import compile_cfg, snippets, CTX, NEAR

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = "https://jhitchco.github.io/granite-docket"
PAST, AHEAD = 60, 60       # meeting dates the alerts cover
MIN_SCORE = 8              # same bar as the site's topic pages
MAX_ENTRIES = 100
ENERGY = ["nuclear", "data_center", "solar", "battery_storage", "wind", "transmission"]
MORATORIUM = re.compile(r"\bmoratori(um|a)\b", re.I)


def load_topics():
    base = json.load(open(os.path.join(ROOT, "keywords.json"), encoding="utf8"))
    extra = json.load(open(os.path.join(ROOT, "alerts_keywords.json"), encoding="utf8"))
    cfg = {"topics": {**base["topics"], **extra["topics"]}}
    return compile_cfg(cfg, None), base["zoning_context"]


def score_doc(text, tp, zrx):
    """The report.py scoring rule, for one document and topic. Returns (score, zoning_terms, excerpt) or None."""
    body = tp["exclude"].sub(" ", text) if tp["exclude"] else text
    strong = list(tp["strong"].finditer(body))
    if not strong: return None
    weak = list(tp["weak"].finditer(body)) if tp["weak"] else []
    terms = {m.group(0).lower() for m in strong}
    near = [m for m in strong if zrx.search(body[max(0, m.start() - NEAR):m.end() + NEAR])]
    z = len({w.group(0).lower() for m in near for w in zrx.finditer(body[max(0, m.start() - NEAR):m.end() + NEAR])})
    score = round(min(len(strong), 20) + 3 * len(terms) + 0.5 * min(len(weak), 10) + 2 * z + min(len(near), 10), 1)
    first = near[0].start() if near else 0
    sn = snippets(body[max(0, first - CTX):], tp["strong"], 1) or snippets(body, tp["strong"], 1)
    mor = any(MORATORIUM.search(body[max(0, m.start() - NEAR):m.end() + NEAR]) for m in near)
    return score, z, sn[0] if sn else None, sorted(terms), mor


def items(conn, today, clean_title):
    topics, zctx = load_topics()
    zrx = re.compile("|".join(f"(?:{w})" for w in zctx), re.I)
    lo, hi = (today - dt.timedelta(PAST)).isoformat(), (today + dt.timedelta(AHEAD)).isoformat()
    out, seen = [], set()
    for doc_id, town, board, typ, date, title, url, sha, text in conn.execute("""SELECT d.id,d.town,d.board,d.doc_type,d.meeting_date,
            d.title,d.url,d.sha256,x.text FROM documents d JOIN doc_text x ON x.id=d.id WHERE d.meeting_date BETWEEN ? AND ?
            AND d.error IS NULL AND length(x.text)>200 ORDER BY length(d.url), d.id""", (lo, hi)):
        key = hashlib.sha1(re.sub(r"\W+", "", text[:3000]).lower().encode()).hexdigest()
        for t, tp in topics.items():
            if (sha, t) in seen or (key, t) in seen: continue
            r = score_doc(text, tp, zrx)
            if not r or r[0] < MIN_SCORE or r[1] == 0 or not r[2]: continue
            sn = r[2]
            ek = (town, t, re.sub(r"\W+", "", (sn["hit"] + sn["post"][:120]).lower()))
            if ek in seen: continue  # same passage in an agenda and its packet, or two postings of one notice
            seen.update({(sha, t), (key, t), ek})
            out.append(dict(id=f"{doc_id}-{t}", topic=t, label=tp["label"], town=town, board=board, type=typ, date=date,
                            title=clean_title(title)[:140], url=url, score=r[0], terms=r[3], moratorium=r[4],
                            excerpt=(sn["pre"][-200:], sn["hit"], sn["post"][:200])))
    out.sort(key=lambda x: (x["date"], x["id"]), reverse=True)
    return out, {k: v["label"] for k, v in topics.items()}


def x(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def atom(fid, title, subtitle, link, entries, BOARD):
    entries = entries[:MAX_ENTRIES]
    updated = (entries[0]["date"] if entries else "2024-01-01") + "T12:00:00Z"
    parts = ['<?xml version="1.0" encoding="utf-8"?>', '<feed xmlns="http://www.w3.org/2005/Atom">',
             f"<id>tag:granite-docket,2026:{x(fid)}</id>", f"<title>{x(title)}</title>", f"<subtitle>{x(subtitle)}</subtitle>",
             f'<link rel="alternate" href="{x(link)}"/>', f'<link rel="self" href="{x(BASE + "/alerts/feeds/" + fid + ".xml")}"/>',
             f"<updated>{updated}</updated>", "<author><name>Granite Docket</name></author>"]
    for it in entries:
        pre, hit, post = it["excerpt"]
        flag = "Moratorium mentioned. " if it["moratorium"] else ""
        summary = f"{flag}...{pre}[{hit}]{post}..."
        parts += ["<entry>", f"<id>tag:granite-docket,2026:{x(it['id'])}</id>",
                  f"<title>{x(it['town'])} {x(BOARD.get(it['board'], it['board']))}: {x(it['label'])} ({x(it['date'])})</title>",
                  f'<link href="{x(it["url"])}"/>', f"<updated>{it['date']}T12:00:00Z</updated>",
                  f'<category term="{x(it["topic"])}" label="{x(it["label"])}"/>',
                  f"<summary>{x(summary)}</summary>", "</entry>"]
    parts.append("</feed>")
    return "\n".join(parts) + "\n"


def build(conn, page, write, slug, e, BOARD, clean_title, towns):
    today = dt.date.today()
    its, labels = items(conn, today, clean_title)
    by_topic, by_town, by_tt = defaultdict(list), defaultdict(list), defaultdict(list)
    for it in its:
        by_topic[it["topic"]].append(it); by_town[it["town"]].append(it); by_tt[(it["town"], it["topic"])].append(it)
    for t, lab in labels.items():
        write(f"alerts/feeds/topic-{slug(t)}.xml", atom(f"topic-{slug(t)}", f"{lab}: New Hampshire town meetings",
              f"Town meeting records that mention {lab.lower()} with land-use context.", f"{BASE}/alerts/", by_topic.get(t, []), BOARD))
    energy = [it for it in its if it["topic"] in ENERGY]
    write("alerts/feeds/energy-siting.xml", atom("energy-siting", "Energy siting: New Hampshire town meetings",
          "Every town record on nuclear, data centers, solar, battery storage, wind and transmission with land-use context.",
          f"{BASE}/alerts/", energy, BOARD))
    combos = defaultdict(list)
    for town in towns:
        s = slug(town)
        write(f"alerts/feeds/town-{s}.xml", atom(f"town-{s}", f"{town} NH: tracked topics", f"Town meeting records in {town} on the tracked topics.",
              f"{BASE}/civic/calendars/", by_town.get(town, []), BOARD))
    # every town and topic pair gets a feed, empty or not, so people can subscribe before the first match
    for town in towns:
        for t in labels:
            lst = by_tt.get((town, t), [])
            write(f"alerts/feeds/{slug(town)}--{slug(t)}.xml", atom(f"{slug(town)}--{slug(t)}", f"{town} NH: {labels[t]}",
                  f"Town meeting records in {town} on {labels[t].lower()}.", f"{BASE}/alerts/", lst, BOARD))
            if lst: combos[town].append(t)
        write(f"alerts/feeds/{slug(town)}--energy-siting.xml", atom(f"{slug(town)}--energy-siting", f"{town} NH: energy siting",
              f"Town meeting records in {town} on energy and siting topics.", f"{BASE}/alerts/",
              [i for i in by_town.get(town, []) if i["topic"] in ENERGY], BOARD))
    write("alerts/data.json", json.dumps({"from": (today - dt.timedelta(PAST)).isoformat(), "labels": labels, "items": its},
                                         ensure_ascii=False, separators=(",", ":")))

    def feed_links(fid):
        url = f"{BASE}/alerts/feeds/{fid}.xml"
        return f'<a href="feeds/{fid}.xml">Feed</a> · <a class="copy" data-url="{e(url)}" href="#">Copy link</a>'
    trows = "".join(f'<tr><td>{e(labels[t])}</td><td class="n">{len(by_topic.get(t, []))}</td><td class="n">{len({i["town"] for i in by_topic.get(t, [])})}</td><td>{feed_links("topic-" + slug(t))}</td></tr>'
                    for t in sorted(labels, key=lambda k: -len(by_topic.get(k, []))))
    recent = "".join([f"""<article class="ev"><div class="top"><span class="date">{e(i["date"])}</span><span class="chip">{e(i["label"])}</span>{'<span class="tag draft">Moratorium</span>' if i["moratorium"] else ""}</div>
<div class="meta">{e(i["town"])} · {e(BOARD.get(i["board"], i["board"]))} · {e(i["type"])}</div>
<p class="snip">…{e(i["excerpt"][0])}<mark>{e(i["excerpt"][1])}</mark>{e(i["excerpt"][2])}…</p><a class="doc" href="{e(i["url"])}" target="_blank" rel="noopener">Source: {e(i["title"])}</a></article>"""
                     for i in its if i["date"] <= today.isoformat()][:20])
    picker = json.dumps({"towns": sorted(towns), "labels": labels, "combos": {t: sorted(v) for t, v in combos.items()},
                         "slugs": {t: slug(t) for t in list(towns) + list(labels)}})
    body = f"""<header class="hd"><div class="eyebrow">Alerts</div><h1>Get alerts for a town and a topic</h1>
<p class="lede">Follow what New Hampshire boards say about energy projects, data centers and housing. Pick a town, a topic, or both, and add the feed to a feed reader. New matches show up as towns post agendas and minutes.</p>
<p class="note">Email alerts (daily or weekly) are coming. Until then, any feed reader works, and most can email you new items on the schedule you choose. A match means a record names the topic near land-use words like ordinance, application or moratorium. Covers meetings {PAST} days back and {AHEAD} days ahead.</p></header>
<section class="calbox"><h2>Build your alert</h2>
<div class="pick"><label>Town <select id="at"><option value="">Every town</option></select></label>
<label>Topic <select id="ap"><option value="">Every topic</option><option value="energy-siting">Energy siting (all energy topics)</option></select></label></div>
<p id="aout" class="note"></p></section>
<section><h2>Statewide topics</h2><div class="tablebox"><table><thead><tr><th>Topic</th><th>Records</th><th>Towns</th><th>Subscribe</th></tr></thead>
<tbody><tr><td><b>Energy siting</b> (nuclear, data centers, solar, storage, wind, transmission)</td><td class="n">{len(energy)}</td><td class="n">{len({i["town"] for i in energy})}</td><td>{feed_links("energy-siting")}</td></tr>{trows}</tbody></table></div></section>
<section><h2>Latest matches</h2><div class="ares">{recent or '<p class="empty">No matches in the window.</p>'}</div></section>
<script>window.ALERTS={picker};</script><script src="../assets/alerts.js?v={today:%Y%m%d}"></script>"""
    write("alerts/index.html", page("Alerts · Granite Docket", 1, body, "Alerts for New Hampshire town meetings by town and topic"))
    return its


def digest(period, town=None, topic=None, data_path=None):
    """Plain-text digest of matches dated in the last day or week plus the next two weeks."""
    data = json.load(open(data_path or os.path.join(ROOT, "docs", "alerts", "data.json"), encoding="utf8"))
    today = dt.date.today()
    lo = (today - dt.timedelta(1 if period == "daily" else 7)).isoformat()
    hi = (today + dt.timedelta(14)).isoformat()
    sel = [i for i in data["items"] if lo <= i["date"] <= hi and (not town or i["town"] == town)
           and (not topic or i["topic"] == topic or (topic == "energy" and i["topic"] in ENERGY))]
    head = f"Granite Docket {period} alert: {town or 'every town'}, {data['labels'].get(topic, 'energy siting' if topic == 'energy' else 'every topic')}"
    lines = [head, f"{len(sel)} matches, meetings {lo} to {hi}", ""]
    for i in sorted(sel, key=lambda i: i["date"]):
        lines += [f"{i['date']}  {i['town']} {i['board']} ({i['type']}): {i['label']}{'  [moratorium]' if i['moratorium'] else ''}",
                  f"  ...{i['excerpt'][0][-120:]}[{i['excerpt'][1]}]{i['excerpt'][2][:120]}...", f"  {i['url']}", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["digest"])
    ap.add_argument("--period", choices=["daily", "weekly"], default="weekly"); ap.add_argument("--town"); ap.add_argument("--topic")
    ap.add_argument("--data")
    a = ap.parse_args()
    print(digest(a.period, a.town, a.topic, a.data))
