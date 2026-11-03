"""OCR scanned PDFs (documents.needs_ocr=1) with Tesseract and add their text to the search index.

  python ocr.py [--workers 16] [--max-pages 60] [--limit N]
Needs Tesseract (Windows: winget install UB-Mannheim.TesseractOCR; Ubuntu: apt install tesseract-ocr).
needs_ocr: 1 = scanned, not yet read; 2 = OCR done; 3 = OCR failed or produced nothing.
"""
import argparse, datetime as dt, multiprocessing as mp, os, sqlite3, sys, time
import fitz

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "nh_meetings.db")
WIN_TESS = r"C:\Program Files\Tesseract-OCR"
TESSDATA = os.path.join(WIN_TESS, "tessdata") if os.path.isdir(WIN_TESS) else None
PRIORITY = ["planning", "zoning", "town_meeting", "select_board", "energy", "economic_dev", "conservation", "budget", "other"]


def init_worker():
    if TESSDATA: os.environ["PATH"] = WIN_TESS + os.pathsep + os.environ["PATH"]
    try:  # stay out of the way of interactive work on this machine
        import psutil; psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
    except Exception:
        if os.name != "nt": os.nice(10)


def ocr_doc(args):
    doc_id, path, max_pages = args
    try:
        parts = []
        with fitz.open(os.path.join(ROOT, path)) as d:
            for i, pg in enumerate(d):
                if i >= max_pages: break
                kw = dict(dpi=200, full=True, language="eng")
                if TESSDATA: kw["tessdata"] = TESSDATA
                parts.append(pg.get_text(textpage=pg.get_textpage_ocr(**kw)))
        return doc_id, "\n".join(parts), None
    except Exception as e:
        return doc_id, "", str(e)[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=16); ap.add_argument("--max-pages", type=int, default=60)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    sys.path.insert(0, ROOT)
    from nhmeet import find_date, classify_board, classify_type
    conn = sqlite3.connect(DB, timeout=120)
    order = " ".join(f"WHEN '{b}' THEN {i}" for i, b in enumerate(PRIORITY))
    rows = conn.execute(f"""SELECT id, local_path FROM documents WHERE needs_ocr=1 AND local_path IS NOT NULL
                            ORDER BY CASE board {order} ELSE 99 END, meeting_date DESC""").fetchall()
    rows = [r for r in rows if os.path.exists(os.path.join(ROOT, r[1]))]  # CI runners only hold this run's downloads
    if a.limit: rows = rows[:a.limit]
    print(f"OCR {len(rows)} documents with {a.workers} workers", flush=True)
    t0, done = time.time(), 0
    with mp.Pool(a.workers, initializer=init_worker) as pool:
        for doc_id, text, err in pool.imap_unordered(ocr_doc, [(i, p, a.max_pages) for i, p in rows], chunksize=4):
            done += 1
            ok = len(text.strip()) >= 50
            for attempt in range(10):
                try:
                    old = conn.execute("SELECT text FROM doc_text WHERE id=?", (doc_id,)).fetchone()
                    if ok:
                        if old: conn.execute("INSERT INTO doc_fts(doc_fts, rowid, text) VALUES('delete', ?, ?)", (doc_id, old[0]))
                        conn.execute("INSERT OR REPLACE INTO doc_text(id, text) VALUES(?, ?)", (doc_id, text))
                        conn.execute("INSERT INTO doc_fts(rowid, text) VALUES(?, ?)", (doc_id, text))
                        d, b, ty = conn.execute("SELECT meeting_date, board, doc_type FROM documents WHERE id=?", (doc_id,)).fetchone()
                        conn.execute("UPDATE documents SET needs_ocr=2, n_chars=?, meeting_date=?, board=?, doc_type=? WHERE id=?",
                                     (len(text), d or find_date(text[:1500]), b if b != "other" else classify_board(text[:600]),
                                      ty if ty != "other" else classify_type(text[:400]), doc_id))
                    else:
                        conn.execute("UPDATE documents SET needs_ocr=3, error=COALESCE(error, ?) WHERE id=?", (err and f"ocr: {err}", doc_id))
                    conn.commit()
                    break
                except sqlite3.OperationalError:
                    conn.rollback(); time.sleep(3)
            if done % 200 == 0:
                rate = done / (time.time() - t0)
                print(f"{dt.datetime.now():%H:%M:%S} {done}/{len(rows)} docs, {rate:.1f}/s, ~{(len(rows) - done) / rate / 60:.0f} min left", flush=True)
    print("OCR finished:", conn.execute("SELECT needs_ocr, count(*) FROM documents GROUP BY 1").fetchall())


if __name__ == "__main__":
    main()
