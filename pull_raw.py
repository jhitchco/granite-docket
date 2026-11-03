"""Move the weekly job's original files (agendas, minutes, packets) from GitHub to this PC's raw/ folder.

  python pull_raw.py
Runs from a Windows scheduled task on Mondays. Downloads each raw-YYYYMMDD.tar.part* bundle on the
"raw-archive" release, unpacks it into raw/ (existing files are kept; names are content hashes),
then deletes the bundle from GitHub.
"""
import datetime as dt, json, os, re, shutil, subprocess, sys, tarfile, tempfile
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = "jhitchco/granite-docket"
LOG = os.path.join(ROOT, "pull_raw.log")


def gh(*args):
    return subprocess.run(["gh", *args, "--repo", REPO], capture_output=True, text=True, check=True).stdout


def log(msg):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M} {msg}"
    print(line)
    with open(LOG, "a", encoding="utf8") as f: f.write(line + "\n")


def main():
    try:
        assets = json.loads(gh("release", "view", "raw-archive", "--json", "assets"))["assets"]
    except subprocess.CalledProcessError:
        log("no raw-archive release; nothing to pull"); return
    bundles = defaultdict(list)
    for a in assets:
        m = re.match(r"(raw-\d{8})\.tar\.part\d+$", a["name"])
        if m: bundles[m.group(1)].append(a["name"])
    for tag, parts in sorted(bundles.items()):
        parts.sort()
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:  # untrusted downloads get their own empty directory
            for p in parts: gh("release", "download", "raw-archive", "-p", p, "-D", tmp)
            joined = os.path.join(tmp, tag + ".tar")
            with open(joined, "wb") as out:
                for p in parts:
                    with open(os.path.join(tmp, p), "rb") as f: shutil.copyfileobj(f, out)
            added = 0
            with tarfile.open(joined) as tf:
                for m in tf.getmembers():
                    # only plain files under raw/<Town>/, no absolute paths or ..
                    if not m.isfile() or not re.match(r"^raw/[\w\-']+/[0-9a-f]{16}\.\w+$", m.name): continue
                    dest = os.path.join(ROOT, *m.name.split("/"))
                    if os.path.exists(dest): continue
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with tf.extractfile(m) as src, open(dest, "wb") as out: shutil.copyfileobj(src, out)
                    added += 1
        for p in parts: gh("release", "delete-asset", "raw-archive", p, "--yes")
        log(f"{tag}: {added} new files archived from {len(parts)} part(s)")


def sync_db():
    """Replace the local database with the weekly job's copy, so local work starts from the latest crawl."""
    import gzip
    db = os.path.join(ROOT, "nh_meetings.db")
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        try: gh("release", "download", "data", "-p", "nh_meetings.db.gz", "-D", tmp)
        except subprocess.CalledProcessError:
            log("no database snapshot on GitHub yet"); return
        new = os.path.join(tmp, "nh_meetings.db")
        with gzip.open(os.path.join(tmp, "nh_meetings.db.gz"), "rb") as g, open(new, "wb") as f: shutil.copyfileobj(g, f, 1 << 20)
        for ext in ("-wal", "-shm"):
            if os.path.exists(db + ext): os.remove(db + ext)
        os.replace(new, db)
    log("local database replaced with the weekly job's snapshot")


if __name__ == "__main__":
    try:
        main(); sync_db()
    except Exception as e:
        log(f"failed: {e}"); sys.exit(1)
