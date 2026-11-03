"""Add hand-downloaded meeting documents to the database.

Drop files into  inbox/<Town>/  (any subfolders, any file names), e.g.
    inbox/Rochester/Planning Board/PB Minutes 2026-08-17.pdf
then run
    python import_inbox.py            # add to the local database
    python import_inbox.py --publish  # also OCR the new scans, rebuild the site and hand the database to the weekly job
Each file is hashed, stored in raw/<Town>/, text-extracted (scans are flagged for ocr.py), classified by
board / type / date from its folder and file name plus its text, and moved to inbox/_done/.
Files already in the database (same contents) are skipped. Folder names must match a town name.
"""
import datetime as dt, hashlib, json, os, re, shutil, sqlite3, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
INBOX = os.path.join(ROOT, "inbox")
sys.path.insert(0, ROOT)
from nhmeet import DB, RAW, SCHEMA, extract_text, classify_board, classify_type, find_date, retry, load_towns

EXT = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
       ".htm": "text/html", ".html": "text/html", ".txt": "text/plain"}


def main():
    os.makedirs(INBOX, exist_ok=True)
    towns = {t["name"].lower(): t["name"] for t in load_towns()}
    conn = sqlite3.connect(DB, timeout=120); conn.executescript(SCHEMA)
    known = {r[0] for r in conn.execute("SELECT sha256 FROM documents WHERE sha256 IS NOT NULL")}
    added = skipped = 0
    for folder in sorted(os.listdir(INBOX)):
        src_dir = os.path.join(INBOX, folder)
        if folder.startswith("_") or not os.path.isdir(src_dir): continue
        town = towns.get(folder.strip().lower())
        if not town:
            print(f"skipping folder '{folder}': not a NH town name"); continue
        for dirpath, _, files in os.walk(src_dir):
            for fn in files:
                path = os.path.join(dirpath, fn); ext = os.path.splitext(fn)[1].lower()
                if ext not in EXT: continue
                content = open(path, "rb").read()
                sha = hashlib.sha256(content).hexdigest()
                rel = os.path.relpath(path, src_dir).replace("\\", "/")
                if sha in known:
                    skipped += 1
                else:
                    text = extract_text(content, EXT[ext], fn)
                    label = f"{rel} {os.path.splitext(fn)[0].replace('_', ' ')}"
                    board = classify_board(label)
                    if board == "other": board = classify_board(text[:600])
                    dtype = classify_type(label)
                    if dtype == "other": dtype = classify_type(text[:400])
                    date = find_date(label) or find_date(text[:1500])
                    d = os.path.join(RAW, re.sub(r"\W+", "_", town)); os.makedirs(d, exist_ok=True)
                    dest = os.path.join(d, sha[:16] + (".pdf" if content[:4] == b"%PDF" else ext))
                    if not os.path.exists(dest): shutil.copyfile(path, dest)
                    needs_ocr = int(content[:4] == b"%PDF" and len(text.strip()) < 200)
                    url = f"inbox://{town}/{rel}"

                    def write():
                        cur = conn.execute(
                            "INSERT OR IGNORE INTO documents(town,url,title,source_page,board,doc_type,meeting_date,content_type,sha256,local_path,n_chars,needs_ocr,fetched_at,error) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (town, url, os.path.splitext(fn)[0][:300], "manual download", board, dtype, date, EXT[ext], sha,
                             os.path.relpath(dest, ROOT), len(text), needs_ocr, dt.datetime.now().isoformat(timespec="seconds"), None))
                        if cur.rowcount and text.strip():
                            conn.execute("INSERT INTO doc_text(id,text) VALUES(?,?)", (cur.lastrowid, text))
                            conn.execute("INSERT INTO doc_fts(rowid,text) VALUES(?,?)", (cur.lastrowid, text))
                        conn.commit()
                    retry(write)
                    known.add(sha); added += 1
                    print(f"{town}: {rel} -> {board}/{dtype} {date or 'no date'}{' (scan, needs OCR)' if needs_ocr else ''}")
                done = os.path.join(INBOX, "_done", folder, os.path.dirname(rel))
                os.makedirs(done, exist_ok=True)
                shutil.move(path, os.path.join(done, fn))
        # mark the town as having hand-imported records so the coverage page says so
        n = conn.execute("SELECT count(*) FROM documents WHERE town=? AND source_page='manual download'", (town,)).fetchone()[0]
        if n:
            retry(lambda: (conn.execute("UPDATE towns SET notes=? WHERE name=?",
                                        (f"Site blocks automated access; {n} documents added by hand", town)), conn.commit()))
    print(f"added {added}, already had {skipped}.")
    conn.close()
    if "--publish" in sys.argv and added: publish()


def publish():
    """OCR new scans, rebuild the site, and replace the weekly job's database with this one. Avoid Monday mornings (job running)."""
    import gzip, subprocess
    run = lambda *a: subprocess.run([sys.executable, "-W", "ignore", *a], cwd=ROOT, check=True)
    run("ocr.py", "--workers", "8"); run("report.py"); run("housing.py", "projects"); run("site.py")
    c = sqlite3.connect(DB, timeout=300); c.execute("PRAGMA wal_checkpoint(TRUNCATE)"); c.close()
    gz = DB + ".gz"
    with open(DB, "rb") as f, gzip.open(gz, "wb", compresslevel=6) as g: shutil.copyfileobj(f, g, 1 << 20)
    gh = lambda *a: subprocess.run(["gh", *a, "--repo", "jhitchco/granite-docket"], cwd=ROOT, check=True)
    if subprocess.run(["gh", "release", "view", "data", "--repo", "jhitchco/granite-docket"], capture_output=True).returncode:
        gh("release", "create", "data", "--title", "Database snapshot", "--notes", "SQLite database used by the weekly crawl. Replaced every run.")
    gh("release", "upload", "data", gz, "--clobber")
    subprocess.run(["git", "add", "docs", "hits.csv", "housing.db"], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Add hand-downloaded records"], cwd=ROOT)
    subprocess.run(["git", "push", "-q"], cwd=ROOT, check=True)
    print("published: site rebuilt and database handed to the weekly job")


if __name__ == "__main__":
    main()
