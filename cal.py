"""Calendar feeds (iCalendar .ics) built from the meeting database.

  docs/cal/<town>.ics              every board in one town
  docs/cal/<town>-<board>.ics      one board (planning, zoning, select board, ...)
  docs/cal/nh-hearings.ics         public hearings statewide
  docs/civic/calendars/index.html  subscribe page for every town

One event per town, board and date, linking the agenda, minutes and notices filed for it. Meeting times come from
the agenda text when it states one; otherwise the event is all-day. Files stay byte-identical between builds unless
the record changed (DTSTAMP is the document's fetch time, not the build time), so weekly commits stay small.
Called from site.py.
"""
import datetime as dt, hashlib, os, re
from collections import defaultdict

BASE = "https://jhitchco.github.io/granite-docket"
PAST, AHEAD = 60, 120                      # days of meetings each feed carries
BOARDS = ["planning", "zoning", "select_board", "town_meeting", "budget", "conservation", "energy", "economic_dev", "heritage_historic"]
TIME = re.compile(r"(?<![\d:])(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*([ap])\.?\s?m\.?(?![a-z])", re.I)
POSTED = re.compile(r"posted\s+\w{3,9}\.?\s+\d{1,2},?\s+\d{4}\s*$", re.I)   # CivicPlus "Posted Sep 24, 2026 11:00 AM"
HEARING = re.compile(r"\bpublic\s+hearing\b", re.I)
VTZ = """BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE"""


def meeting_time(text):
    """First clock time in the top of an agenda, skipping a portal's 'Posted <date> <time>' stamp."""
    for m in TIME.finditer(text[:1500]):
        if POSTED.search(text[max(0, m.start() - 40):m.start()]): continue
        h, mi = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0), int(m.group(2) or 0)
        if 6 <= h <= 22: return h, mi     # meetings run 6am to 10pm; anything else is a misread
    return None


def esc(s):
    return re.sub(r"([,;\\])", r"\\\1", str(s)).replace("\n", "\\n")


def fold(line):
    """RFC 5545: lines over 75 octets continue on the next line after a single space."""
    b, out = line.encode("utf8"), []
    while len(b) > (75 if not out else 74):
        cut = 75 if not out else 74
        while (b[cut] & 0xC0) == 0x80: cut -= 1   # don't split a UTF-8 character
        out.append(b[:cut].decode("utf8")); b = b[cut:]
    out.append(b.decode("utf8"))
    return "\r\n ".join(out)


def calendar(name, desc, events):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Granite Docket//NH meetings//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{esc(name)}", f"X-WR-CALDESC:{esc(desc)}", "X-WR-TIMEZONE:America/New_York",
             "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H"] + VTZ.split("\n")
    for ev in sorted(events, key=lambda x: (x["date"], x["uid"])):
        d = ev["date"].replace("-", "")
        when = ([f"DTSTART;TZID=America/New_York:{d}T{ev['time'][0]:02d}{ev['time'][1]:02d}00", "DURATION:PT2H"] if ev["time"] else
                [f"DTSTART;VALUE=DATE:{d}", f"DTEND;VALUE=DATE:{(dt.date.fromisoformat(ev['date']) + dt.timedelta(1)):%Y%m%d}", "TRANSP:TRANSPARENT"])
        lines += ["BEGIN:VEVENT", f"UID:{ev['uid']}", f"DTSTAMP:{ev['stamp']}", *when, f"SUMMARY:{esc(ev['summary'])}",
                  f"LOCATION:{esc(ev['town'] + ', NH')}", f"URL:{ev['url']}", f"DESCRIPTION:{esc(ev['desc'])}",
                  *(["CATEGORIES:Public hearing"] if ev["hearing"] else []), "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def events(conn, today, BOARD, clean_title):
    lo, hi = (today - dt.timedelta(PAST)).isoformat(), (today + dt.timedelta(AHEAD)).isoformat()
    groups = defaultdict(list)
    for town, board, typ, date, title, url, sha, fetched, head in conn.execute("""SELECT d.town,d.board,d.doc_type,d.meeting_date,d.title,d.url,
            d.sha256,d.fetched_at,substr(x.text,1,3000) FROM documents d LEFT JOIN doc_text x ON x.id=d.id
            WHERE d.meeting_date BETWEEN ? AND ? AND d.error IS NULL ORDER BY length(d.url)""", (lo, hi)):
        key = (town, board, date) if board != "other" else (town, board, date, clean_title(title).lower()[:60])
        groups[key].append((typ, title, url, sha, fetched or "", head or ""))
    out = []
    for key, docs in groups.items():
        town, board, date = key[:3]
        seen, uniq = set(), []
        for d in docs:
            if d[3] in seen: continue
            seen.add(d[3]); uniq.append(d)
        order = {"agenda": 0, "notice": 1, "warrant": 2, "minutes": 3}
        uniq.sort(key=lambda d: order.get(d[0], 4))
        hearing = any(d[0] == "notice" or HEARING.search(d[5]) for d in uniq)
        t = next((tm for d in uniq if d[0] in ("agenda", "notice") for tm in [meeting_time(d[5])] if tm), None)
        label = BOARD.get(board, board) if board != "other" else (clean_title(uniq[0][1])[:70] or "Meeting")
        stamp = max(d[4] for d in uniq)[:19].replace("-", "").replace(":", "") or "20240101T000000"
        lines = [f"{d[0].title()}: {clean_title(d[1])[:100]}\n{d[2]}" for d in uniq[:8]]
        out.append(dict(town=town, board=board, date=date, time=t, hearing=hearing, url=uniq[0][2], stamp=stamp + ("Z" if "T" in stamp else "T000000Z"),
                        uid=hashlib.sha1("|".join(map(str, key)).encode()).hexdigest()[:20] + "@granite-docket",
                        summary=f"{'Public hearing: ' if hearing else ''}{town} {label}",
                        desc="\n\n".join(lines) + "\n\nFrom the town's posted records via Granite Docket. Check the town's site for changes."))
    return out


def build(conn, page, write, slug, e, BOARD, clean_title, towns):
    today = dt.date.today()
    evs = events(conn, today, BOARD, clean_title)
    by_town = defaultdict(list)
    for ev in evs: by_town[ev["town"]].append(ev)
    rows = []
    for town in sorted(towns):
        s, tev = slug(town), by_town.get(town, [])
        write(f"cal/{s}.ics", calendar(f"{town} NH meetings", f"Public meetings of {town}, NH boards, from posted agendas and minutes.", tev))
        feeds = [("All boards", f"cal/{s}.ics", len(tev))]
        for b in BOARDS:
            bev = [x for x in tev if x["board"] == b]
            if not bev: continue
            write(f"cal/{s}-{slug(b)}.ics", calendar(f"{town} {BOARD.get(b, b)}", f"{BOARD.get(b, b)} meetings in {town}, NH.", bev))
            feeds.append((BOARD.get(b, b), f"cal/{s}-{slug(b)}.ics", len(bev)))
        rows.append((town, s, feeds, sum(x["hearing"] for x in tev)))
    hear = [x for x in evs if x["hearing"]]
    write("cal/nh-hearings.ics", calendar("NH public hearings", "Public hearings posted by New Hampshire municipalities.", hear))

    def links(path):
        url = f"{BASE}/{path}"
        return (f'<a href="{e("webcal://" + url.split("://", 1)[1])}">Subscribe</a> · '
                f'<a href="https://calendar.google.com/calendar/r?cid={e("webcal://" + url.split("://", 1)[1])}" target="_blank" rel="noopener">Google</a> · '
                f'<a href="../../{path}">.ics</a>')
    trs = "".join(f"""<tr><td><a href="../{s}/index.html">{e(t)}</a></td><td class="n">{f[0][2]}</td><td class="n">{h}</td><td>{links(f[0][1])}</td>
<td>{" ".join(f'<details class="bfeeds"><summary>{e(n)} ({c})</summary>{links(p)}</details>' for n, p, c in f[1:])}</td></tr>""" for t, s, f, h in rows if f[0][2])
    body = f"""<header class="hd"><div class="eyebrow">Town records</div><h1>Meeting calendars</h1>
<p class="lede">Put any New Hampshire town's public meetings on your own calendar. Subscribe once and new agendas and hearings appear on their own as towns post them.</p>
<p class="note">Each event links the agenda, notices and minutes filed for that meeting. Times come from the agenda when it states one; otherwise the event shows as all-day. Feeds cover {PAST} days back and {AHEAD} days ahead and refresh with each crawl. Always confirm with the town before you go: meetings move.</p></header>
<section class="calbox"><h2>Every public hearing in the state</h2><p>{len(hear):,} hearings in the current window. {links("cal/nh-hearings.ics")}</p></section>
<section><h2>By town</h2><div class="tablebox"><table><thead><tr><th>Town</th><th>Meetings</th><th>Hearings</th><th>All boards</th><th>One board</th></tr></thead><tbody>{trs}</tbody></table></div>
<p class="note">On a phone, "Subscribe" opens your calendar app. On a computer, copy the .ics link into your calendar's "add by URL" or "subscribe" option. Towns with no meetings in the window are left out.</p></section>"""
    write("civic/calendars/index.html", page("Meeting calendars · Granite Docket", 2, body, "Subscribe to New Hampshire town meeting calendars"))
    return {t: (s, f) for t, s, f, h in rows}, links
