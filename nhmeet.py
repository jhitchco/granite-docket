"""NH municipal meeting crawler: agendas + minutes -> SQLite (raw files on disk, extracted text in FTS5).

Usage:
  python nhmeet.py crawl [--towns "Hanover,Lebanon"] [--since 2024-01-01] [--workers 16]
  python nhmeet.py stats
"""
import argparse, concurrent.futures as cf, datetime as dt, hashlib, io, json, os, re, sqlite3, sys, threading, time, zipfile
from urllib.parse import urljoin, urlparse, urldefrag
from urllib import robotparser
import requests
from bs4 import BeautifulSoup
import warnings; warnings.filterwarnings("ignore")
import fitz  # pymupdf

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "nh_meetings.db")
RAW = os.path.join(ROOT, "raw")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36 nh-meetings-research"
MAX_PAGES = 450          # HTML pages per town
MAX_DOCS = 4000          # documents per town
MAX_BYTES = 60 << 20     # skip files over 60 MB
DEADLINE = float("inf")  # epoch seconds; set by --max-minutes so CI runs stop cleanly
DELAY = 0.25             # seconds between requests to one town
DOC_EXT = re.compile(r"\.(pdf|docx?|rtf|txt)(\?|$)", re.I)
DOC_PATH = re.compile(r"/AgendaCenter/ViewFile/|/DocumentCenter/View/|/ArchiveCenter/ViewFile/|get_agenda_document_link|/Archive\.aspx\?ADID=|/media/\d+$|/file/\d+/|/download_file/|/uploads/", re.I)
MEET = re.compile(r"agenda|minute|meeting|hearing|notice|warrant|deliberative|session|packet|mtg|\bmins?\b|\bpb\b|\bzba\b|\bbos\b|\bsb\b", re.I)
NAV = re.compile(r"agenda|minute|meeting|planning|zoning|zba|adjustment|select|council|aldermen|board|commission|committee|hearing|town[-_ ]?meeting|warrant|deliberative|government|departments?|archive|document|calendar|20(2[3-6])", re.I)
SKIP = re.compile(r"\.(jpe?g|png|gif|svg|webp|mp4|mp3|zip|xlsx?|pptx?|css|js|ico)(\?|$)|mailto:|tel:|javascript:|/Calendar\.aspx\?|/calendar/|[?&](month|date|day|week|year)=|/print/|/rss|/login|/user/|/search|/Faq|/Directory|/Jobs|/Bids|/Alert|/feed/?$|/tag/|/author/|share=|replytocom|/wp-json|/comment", re.I)
DOC_HOSTS = re.compile(r"towncloud\.io|wsimg\.com|municodemeetings|boarddocs|civicclerk|granicus|civicplus|amazonaws|squarespace|wixstatic|weebly", re.I)

BOARDS = [
    ("zoning", r"zoning|zba|adjustment|\bza\b"),
    ("planning", r"planning|\bpb\b|site[-_ ]plan|subdivision|master[-_ ]plan|\bplan\s?bd"),
    ("town_meeting", r"town[-_ ]?meeting|deliberative|warrant|annual[-_ ]meeting|special[-_ ]meeting"),
    ("select_board", r"select|\bbos\b|\bsb\b|council|aldermen|board[-_ ]of[-_ ]mayor|mayor"),
    ("conservation", r"conservation|\bconcom\b|\bcc\b"),
    ("energy", r"energy|sustainab|climate"),
    ("economic_dev", r"economic|\bedc\b|business[-_ ]development"),
    ("budget", r"budget|finance|capital[-_ ]improvement|\bcip\b"),
    ("heritage_historic", r"historic|heritage"),
    ("school", r"school"),
]
MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()


def classify_board(s):
    s = s.lower()
    for name, rx in BOARDS:
        if re.search(rx, s): return name
    return "other"


def classify_type(s):
    s = s.lower()
    if re.search(r"minute|mins\b|_min_|-min-|\bmin\b", s): return "minutes"
    if re.search(r"agenda|packet", s): return "agenda"
    if re.search(r"warrant", s): return "warrant"
    if re.search(r"notice|hearing", s): return "notice"
    return "other"


def find_date(s):
    """Best-effort meeting date from a filename / link text / doc text. Returns ISO date or None."""
    s = s.replace("%20", " ")
    pats = [
        (r"_([01]\d)([0-3]\d)(20[12]\d)-", "mdy"),   # CivicPlus _MMDDYYYY-ID
        (r"(20[12]\d)[-_./ ]?([01]\d)[-_./ ]?([0-3]\d)(?!\d)", "ymd"),
        (r"(?<!\d)([01]?\d)[-_./]([0-3]?\d)[-_./](20[12]\d)(?!\d)", "mdy"),
        (r"(?<!\d)([01]?\d)[-_./]([0-3]?\d)[-_./]([12]\d)(?!\d)", "mdy2"),
        (r"(?<!\d)([01]\d)([0-3]\d)(20[12]\d)(?!\d)", "mdy"),
        (r"(?<!\d)([01]\d)([0-3]\d)([12]\d)(?!\d)", "mdy2"),
        (r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?[-_ ]+([0-3]?\d)(?:st|nd|rd|th)?,?[-_ ]+(20[12]\d)", "Mdy"),
    ]
    for rx, kind in pats:
        for m in re.finditer(rx, s, re.I):
            try:
                if kind == "ymd": y, mo, d = int(m[1]), int(m[2]), int(m[3])
                elif kind == "mdy": mo, d, y = int(m[1]), int(m[2]), int(m[3])
                elif kind == "mdy2": mo, d, y = int(m[1]), int(m[2]), 2000 + int(m[3])
                else: mo, d, y = MONTHS.index(m[1].lower()[:3]) + 1, int(m[2]), int(m[3])
                if 2010 <= y <= 2027: return dt.date(y, mo, d).isoformat()
            except ValueError:
                continue
    return None


SCHEMA = """
CREATE TABLE IF NOT EXISTS towns(name TEXT PRIMARY KEY, county TEXT, type TEXT, population INTEGER, website TEXT,
  platform TEXT, crawl_status TEXT, pages INTEGER, docs INTEGER, notes TEXT, crawled_at TEXT);
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, town TEXT, url TEXT UNIQUE, title TEXT, source_page TEXT,
  board TEXT, doc_type TEXT, meeting_date TEXT, content_type TEXT, sha256 TEXT, local_path TEXT, n_chars INTEGER,
  needs_ocr INTEGER DEFAULT 0, fetched_at TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS doc_text(id INTEGER PRIMARY KEY, text TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(text, content='doc_text', content_rowid='id', tokenize='porter unicode61');
CREATE INDEX IF NOT EXISTS ix_doc_town ON documents(town);
"""
_dblock = threading.Lock()


def retry(fn, tries=20):
    """Run a DB write, waiting out locks held by OCR or report runs that share the database."""
    for k in range(tries):
        try: return fn()
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) or k == tries - 1: raise
            time.sleep(min(30, 2 + 2 * k))


def db():
    c = sqlite3.connect(DB, timeout=120, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def extract_text(content, ctype, url):
    u = url.lower()
    try:
        if content[:4] == b"%PDF" or "pdf" in ctype:
            with fitz.open(stream=content, filetype="pdf") as d:
                return "\n".join(p.get_text() for p in d)
        if content[:2] == b"PK" or u.endswith(".docx"):
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                x = z.read("word/document.xml").decode("utf8", "ignore")
            return re.sub(r"<[^>]+>", " ", x.replace("</w:p>", "\n"))
        if "html" in ctype:
            s = BeautifulSoup(content, "lxml")
            for t in s(["script", "style", "nav", "header", "footer"]): t.decompose()
            main = s.find("main") or s.find(id=re.compile("content|main", re.I)) or s.body or s
            return main.get_text("\n", strip=True)
        if "text" in ctype or u.endswith(".txt"):
            return content.decode("utf8", "ignore")
    except Exception as e:
        return f"__EXTRACT_ERROR__ {e}"
    return ""


class Town:
    def __init__(self, t, since, conn):
        self.t, self.name, self.since, self.conn = t, t["name"], since, conn
        self.base = t["final_url"]
        self.host = urlparse(self.base).netloc.lower().removeprefix("www.")
        self.s = requests.Session(); self.s.headers["User-Agent"] = UA
        self.seen, self.docs_seen, self.pages, self.ndocs = set(), set(), 0, 0
        self.last = 0.0
        self.robots = robotparser.RobotFileParser()
        try:
            r = self.s.get(f"{urlparse(self.base).scheme}://{urlparse(self.base).netloc}/robots.txt", timeout=15)
            self.robots.parse(r.text.splitlines() if r.status_code == 200 else [])
        except Exception:
            self.robots.parse([])
        try: self.delay = float(self.robots.crawl_delay(UA) or 0)  # honor a site's Crawl-delay
        except Exception: self.delay = 0
        self.known = {r[0] for r in conn.execute("SELECT url FROM documents WHERE town=?", (self.name,))}

    def get(self, url, **kw):
        wait = max(DELAY, self.delay) - (time.time() - self.last)
        if wait > 0: time.sleep(wait)
        self.last = time.time()
        return self.s.get(url, timeout=kw.pop("timeout", 45), **kw)

    def same_site(self, u):
        h = urlparse(u).netloc.lower().removeprefix("www.")
        return h == self.host or h.endswith("." + self.host)

    def allowed(self, u):
        try: return self.robots.can_fetch(UA, u)
        except Exception: return True

    # ---------- document handling ----------
    def want_doc(self, url, text, ctx):
        blob = f"{url} {text} {ctx}"
        if not MEET.search(blob) and not re.search(r"planning|zoning|select|council|board", blob, re.I): return False
        d = find_date(f"{text} {url}")
        if d and d < self.since: return False
        return True

    def save_doc(self, url, title, src, ctx, html_text=None):
        url = urldefrag(url)[0]
        if url in self.docs_seen or url in self.known or self.ndocs >= MAX_DOCS or time.time() > DEADLINE: return
        self.docs_seen.add(url)
        label = f"{title} {url} {ctx}"
        board, dtype = classify_board(label), classify_type(f"{title} {url}") if classify_type(f"{title} {url}") != "other" else classify_type(ctx)
        date = find_date(f"{title} {url}")
        err = None; text = ""; ctype = ""; sha = None; path = None
        try:
            if html_text is not None:
                text, ctype = html_text, "text/html"
                content = html_text.encode()
            else:
                if not self.allowed(url): return
                r = self.get(url, timeout=90, stream=True)
                if r.status_code >= 400: raise Exception(f"HTTP {r.status_code}")
                ctype = r.headers.get("content-type", "").lower()
                if int(r.headers.get("content-length") or 0) > MAX_BYTES: raise Exception("too large")
                content = b""
                for chunk in r.iter_content(1 << 16):
                    content += chunk
                    if len(content) > MAX_BYTES: raise Exception("too large")
                if "html" in ctype and not DOC_EXT.search(url):
                    return  # a page, not a document; leave it to the crawler
                text = extract_text(content, ctype, url)
            sha = hashlib.sha256(content).hexdigest()
            ext = ".pdf" if content[:4] == b"%PDF" else ".docx" if content[:2] == b"PK" else ".html" if "html" in ctype else ".bin"
            d = os.path.join(RAW, re.sub(r"\W+", "_", self.name)); os.makedirs(d, exist_ok=True)
            path = os.path.join(d, sha[:16] + ext)
            if not os.path.exists(path):
                with open(path, "wb") as f: f.write(content)
            if not date: date = find_date(text[:1500])
            if date and date < self.since: return
            if board == "other": board = classify_board(text[:600])
            if dtype == "other": dtype = classify_type(text[:400])
        except Exception as e:
            err = str(e)[:300]
        needs_ocr = int(bool(sha) and ext == ".pdf" and len(text.strip()) < 200)
        def write():
          with _dblock:
            try:
              cur = self.conn.execute(
                "INSERT OR IGNORE INTO documents(town,url,title,source_page,board,doc_type,meeting_date,content_type,sha256,local_path,n_chars,needs_ocr,fetched_at,error) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (self.name, url, title[:300], src, board, dtype, date, ctype[:80], sha, path and os.path.relpath(path, ROOT), len(text), needs_ocr, dt.datetime.now().isoformat(timespec="seconds"), err))
              if cur.lastrowid and cur.rowcount and text:
                self.conn.execute("INSERT INTO doc_text(id,text) VALUES(?,?)", (cur.lastrowid, text))
                self.conn.execute("INSERT INTO doc_fts(rowid,text) VALUES(?,?)", (cur.lastrowid, text))
              self.conn.commit()
            except sqlite3.OperationalError:
              self.conn.rollback(); raise
        retry(write)
        self.ndocs += 1

    # ---------- platform helpers ----------
    def civicplus(self):
        root = f"{urlparse(self.base).scheme}://{urlparse(self.base).netloc}"
        try: r = self.get(root + "/AgendaCenter")
        except Exception: return
        if r.status_code != 200 or "AgendaCenter" not in r.text: return
        cats = dict(re.findall(r'id="cat(\d+)"[^>]*>\s*<h2[^>]*>(.*?)</h2', r.text, re.S))
        y0, y1 = int(self.since[:4]), dt.date.today().year
        for cid, cname in cats.items():
            cname = BeautifulSoup(cname, "lxml").get_text(" ", strip=True)
            for y in range(y0, y1 + 1):
                try: rr = self.s.post(root + "/AgendaCenter/UpdateCategoryList", data={"year": y, "catID": cid}, timeout=45)
                except Exception: continue
                time.sleep(DELAY)
                soup = BeautifulSoup(rr.text, "lxml")
                for tr in soup.select("tr"):
                    when = tr.get_text(" ", strip=True)[:200]
                    for a in tr.select("a[href]"):
                        h = a["href"]
                        if "/ViewFile/" not in h or "html=true" in h.lower(): continue
                        if "?packet" in h.lower(): continue
                        kind = "Minutes" if "/Minutes/" in h else "Agenda"
                        self.save_doc(urljoin(root, h), f"{cname} {kind} {when}", root + "/AgendaCenter", f"{cname} {kind}")

    def towncloud(self, html_blobs):
        slugs = set(re.findall(r"towncloud\.io/go/([\w-]+)/agendas/(\d+)", html_blobs))
        by = {}
        for slug, i in slugs: by[slug] = max(by.get(slug, 0), int(i))
        if not by:  # site built on TownCloud but no agenda links in the HTML (list is loaded by script): find the newest id
            slug = (re.findall(r"towncloud\.io/go/([\w-]+)", html_blobs) or [re.sub(r"[^a-z]+", "-", self.name.lower()).strip("-") + "-nh"])[0]
            hi, misses, i = 0, 0, 0
            while i < 2000 and (misses < 80 or (not hi and i < 400)):
                i += 1
                try: r = self.get(f"https://towncloud.io/go/{slug}/agendas/{i}", timeout=30)
                except Exception: continue
                if r.status_code == 200 and "Read the full agenda" in r.text: hi, misses = i, 0
                else: misses += 1
            if hi: by[slug] = hi
        for slug, hi in by.items():
            misses = 0
            for i in range(hi + 40, 0, -1):
                u = f"https://towncloud.io/go/{slug}/agendas/{i}"
                try: r = self.get(u, timeout=30)
                except Exception: continue
                if r.status_code != 200 or "Read the full agenda" not in r.text:
                    misses += 1
                    if misses > 60: break
                    continue
                misses = 0
                txt = BeautifulSoup(r.text, "lxml").get_text(" ", strip=True)
                d = find_date(txt)
                if d and d < self.since: break  # ids are chronological
                title = re.sub(r"\s+", " ", txt)[:200]
                for a in re.findall(r'href="([^"]*get_agenda_document_link)"', r.text):
                    if "pdf_packet" in a: continue
                    self.save_doc(urljoin(u, a), title, u, title)
                for a in re.findall(r'href="([^"]*minutes[^"]*)"', r.text, re.I):
                    self.save_doc(urljoin(u, a), "Minutes " + title, u, "minutes " + title)

    def civicclerk(self, html_blobs):
        """CivicClerk portals (<tenant>.portal.civicclerk.com) load meetings by script; read the public events API instead."""
        for tenant in set(re.findall(r"([\w-]+)\.portal\.civicclerk\.com", html_blobs)):
            api = f"https://{tenant}.api.civicclerk.com/v1"
            skip = 0
            while time.time() < DEADLINE:
                try: r = self.get(f"{api}/Events", params={"$filter": f"startDateTime ge {self.since}T00:00:00Z", "$orderby": "startDateTime desc", "$top": 100, "$skip": skip}, timeout=60)
                except Exception: break
                if r.status_code != 200: break
                events = r.json().get("value", [])
                for e in events:
                    when = (e.get("startDateTime") or "")[:10]
                    for f in e.get("publishedFiles") or []:
                        if f.get("type") == "Agenda Packet": continue  # packets repeat the agenda and run to hundreds of pages
                        title = f"{e.get('categoryName') or e.get('eventName')} {f.get('type')} {when} {f.get('name') or ''}"
                        self.save_doc(f"{api}/Meetings/GetMeetingFileStream(fileId={f['fileId']},plainText=false)", title,
                                      f"https://{tenant}.portal.civicclerk.com/event/{e['id']}/files", title)
                if len(events) < 100: break
                skip += 100

    # ---------- generic crawl ----------
    def crawl(self):
        frontier = [(0, 0, self.base, "home")]
        blobs = []
        while frontier and self.pages < MAX_PAGES and time.time() < DEADLINE:
            frontier.sort(key=lambda x: (x[0], x[1]))
            _, depth, url, ctx = frontier.pop(0)
            if url in self.seen: continue
            self.seen.add(url)
            if not self.allowed(url): continue
            try: r = self.get(url)
            except Exception: continue
            self.pages += 1
            ctype = r.headers.get("content-type", "").lower()
            if "html" not in ctype:
                if r.status_code == 200 and ("pdf" in ctype or "word" in ctype): self.save_doc(url, ctx, url, ctx)
                continue
            html = r.text
            if len(blobs) < 400: blobs.append(html[:300000])
            soup = BeautifulSoup(html, "lxml")
            heading = " ".join(h.get_text(" ", strip=True) for h in soup.select("h1,h2")[:3])[:200]
            page_ctx = f"{heading} {urlparse(r.url).path}"
            # govAccess/Drupal & similar: an agenda/minutes item rendered as an HTML page
            if re.search(r"/(agenda|minutes)/[^/]+$", urlparse(r.url).path, re.I) and not soup.select_one("table.views-table"):
                self.save_doc(r.url, heading, url, page_ctx, html_text=extract_text(r.content, "text/html", r.url))
            for a in soup.select("a[href]"):
                href = a["href"].strip()
                if not href or href.startswith("#"): continue
                try: u = urldefrag(urljoin(r.url, href))[0]; urlparse(u).netloc
                except ValueError: continue  # malformed hrefs (e.g. stray brackets read as IPv6)
                if not u.startswith("http") or SKIP.search(u): continue
                txt = a.get_text(" ", strip=True)[:200]
                # row context helps when link text is just "Agenda" / "Minutes"
                row = a.find_parent(["tr", "li", "p"])
                rowtxt = row.get_text(" ", strip=True)[:200] if row else ""
                ctx2 = f"{page_ctx} {rowtxt}"
                is_doc = DOC_EXT.search(u) or DOC_PATH.search(u)
                if is_doc and (self.same_site(u) or DOC_HOSTS.search(u)):
                    if self.want_doc(u, f"{txt} {rowtxt}", page_ctx): self.save_doc(u, f"{txt} | {rowtxt}"[:300], r.url, ctx2)
                    continue
                if not self.same_site(u) or depth >= 5: continue
                if u in self.seen: continue
                score = 0 if NAV.search(f"{txt} {urlparse(u).path}") else 5
                if re.search(r"agenda|minute", f"{txt} {u}", re.I): score -= 2
                if re.search(r"planning|zoning|select|council|town[-_ ]meeting", f"{txt} {u}", re.I): score -= 1
                if len(urlparse(u).query) > 60: score += 4
                if score >= 5 and depth >= 2: continue
                frontier.append((score, depth + 1, u, txt))
        return "\n".join(blobs)

    def run(self):
        plat = self.t.get("platform") or []
        if "civicplus" in plat or "civicplus" in self.base: self.civicplus()
        blobs = self.crawl()
        if "towncloud.io/go/" in blobs or "towncloud.com?utm" in blobs: self.towncloud(blobs)
        if ".portal.civicclerk.com" in blobs: self.civicclerk(blobs)
        return self.pages, self.ndocs


def load_towns():
    T = json.load(open(os.path.join(ROOT, "towns.json")))
    for t in T:
        c = t["cells"]
        t["county"] = re.sub(r"\s*\(.*", "", c[2]); t["type"] = c[1]
        try: t["population"] = int(c[4].replace(",", ""))
        except Exception: t["population"] = None
    return T


def crawl_town(t, since):
    if time.time() > DEADLINE: return t["name"], "skipped (time limit)"
    conn = db()
    name = t["name"]
    def mark(status, pages=0, docs=0, notes=""):
        def write():
          with _dblock:
            conn.execute("INSERT OR REPLACE INTO towns VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (name, t["county"], t["type"], t["population"], t.get("final_url"), ",".join(t.get("platform") or []),
                          status, pages, docs, notes, dt.datetime.now().isoformat(timespec="seconds")))
            conn.commit()
        retry(write)
    if t.get("resolved") == "NO_SITE" or not t.get("final_url"):
        mark("no_website", notes="No municipal website found"); return name, "no_website"
    try:
        probe = requests.get(t["final_url"], headers={"User-Agent": UA}, timeout=30)
        if probe.status_code == 403 and "cloudflare" in (probe.headers.get("server") or "").lower():
            mark("blocked_bot_challenge", notes="Site behind Cloudflare challenge; not crawled"); return name, "blocked"
        if t.get("resolved") == "FAILED":
            mark("unreachable", notes=f"HTTP {probe.status_code}"); return name, "unreachable"
    except Exception as e:
        mark("unreachable", notes=str(e)[:200]); return name, "unreachable"
    try:
        rp = robotparser.RobotFileParser()
        rb = requests.get(f"{urlparse(probe.url).scheme}://{urlparse(probe.url).netloc}/robots.txt", headers={"User-Agent": UA}, timeout=15)
        rp.parse(rb.text.splitlines() if rb.status_code == 200 else [])
        if not rp.can_fetch(UA, probe.url):
            mark("robots_disallowed", notes="robots.txt disallows non-search-engine crawlers"); return name, "robots"
    except Exception:
        pass
    mark("crawling")
    try:
        pages, docs = Town(t, since, conn).run()
        mark("done", pages, docs)
        return name, f"done pages={pages} docs={docs}"
    except Exception as e:
        mark("error", notes=str(e)[:300]); return name, f"error {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["crawl", "stats"])
    ap.add_argument("--towns"); ap.add_argument("--since", default="2024-01-01")
    ap.add_argument("--workers", type=int, default=16); ap.add_argument("--skip-done", action="store_true")
    ap.add_argument("--since-days", type=int, help="rolling window: only fetch documents dated within N days (unknown dates still fetched)")
    ap.add_argument("--max-minutes", type=float, help="stop starting new work after this many minutes")
    a = ap.parse_args()
    conn = db(); conn.executescript(SCHEMA); conn.commit()
    if a.cmd == "stats":
        for r in conn.execute("SELECT crawl_status,count(*),sum(docs) FROM towns GROUP BY 1"): print(r)
        print(conn.execute("SELECT count(*), sum(needs_ocr), sum(error IS NOT NULL) FROM documents").fetchone())
        for r in conn.execute("SELECT board,doc_type,count(*) FROM documents GROUP BY 1,2 ORDER BY 3 DESC LIMIT 30"): print(r)
        return
    global DEADLINE
    if a.max_minutes: DEADLINE = time.time() + 60 * a.max_minutes
    if a.since_days: a.since = (dt.date.today() - dt.timedelta(a.since_days)).isoformat()
    T = load_towns()
    if a.towns: T = [t for t in T if t["name"] in {x.strip() for x in a.towns.split(",")}]
    if a.skip_done:
        done = {r[0] for r in conn.execute("SELECT name FROM towns WHERE crawl_status IN ('done','blocked_bot_challenge','no_website','robots_disallowed')")}
        T = [t for t in T if t["name"] not in done]
    print(f"crawling {len(T)} towns since {a.since}", flush=True)
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for name, res in ex.map(lambda t: crawl_town(t, a.since), T):
            print(dt.datetime.now().strftime("%H:%M:%S"), name, res, flush=True)


if __name__ == "__main__":
    main()
