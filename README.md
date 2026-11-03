# Granite Docket

Live site: https://jhitchco.github.io/granite-docket/


Collects public meeting records (agendas, minutes, packets, warrants, notices) from all 234 New Hampshire municipalities and scans them for topics of interest. The first topics are nuclear/micro-nuclear and data centers.

## Pipeline

| Step | Script | Output |
|---|---|---|
| Municipality list (Wikipedia) + websites (Wikidata) | `towns.py` | `towns_raw.json` |
| Platform fingerprint, URL repair | `fingerprint.py`, `resolve_sites.py` | `towns.json` |
| Crawl + download + text extraction | `nhmeet.py crawl` | `nh_meetings.db`, `raw/<Town>/*.pdf` |
| Keyword scan + report | `report.py` | `hits` table, `hits.csv`, `report.html` |
| Static site (GitHub Pages) | `site.py` | `docs/` |

## Raw data (`nh_meetings.db`, SQLite)

- `towns`: crawl status per municipality (`done`, `blocked_bot_challenge`, `robots_disallowed`, `no_website`, `unreachable`), page and document counts.
- `documents`: one row per agenda/minutes file or HTML meeting page. Columns: town, url, title, source page, board (planning, zoning, select_board, town_meeting, conservation, energy, economic_dev, budget, ...), doc_type (agenda, minutes, warrant, notice), meeting_date, sha256, local raw file path, `needs_ocr` (scanned PDFs with no text layer).
- `doc_text` + `doc_fts`: extracted full text with an FTS5 index. Ad hoc search example:
  `SELECT d.town, d.meeting_date, d.url FROM doc_fts f JOIN documents d ON d.id=f.rowid WHERE doc_fts MATCH '"battery storage"';`

## How the crawler works

- CivicPlus sites: walks AgendaCenter year by year for every board (`/AgendaCenter/UpdateCategoryList`).
- TownCloud (towncloud.io): enumerates agenda IDs back to the cutoff date.
- Everything else (WordPress, Revize, custom sites): a prioritized crawl of up to 450 pages per town, following links about agendas, minutes, boards and meetings, and collecting PDF/DOCX/HTML meeting documents dated on or after `--since` (default 2024-01-01).
- Polite by design: obeys robots.txt, about 4 requests per second per town, and never tries to get past bot challenges.

## Adding topics

Edit `keywords.json` (regex terms per topic, plus `exclude` patterns for false positives) and rerun `python report.py`. No re-crawl is needed.

## Refreshing

```
python nhmeet.py crawl --since 2024-01-01 --skip-done   # resume / finish
python nhmeet.py crawl                                  # incremental: already-stored URLs are skipped
python report.py
python site.py      # regenerate docs/, then commit and push
```
