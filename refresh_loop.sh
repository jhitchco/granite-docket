#!/usr/bin/env bash
# While the first crawl runs: rescan, rebuild and publish the site every 30 minutes.
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf8
while true; do
  python -W ignore report.py >/dev/null && python -W ignore housing.py projects >/dev/null && python -W ignore site.py >/dev/null \
    && git add docs hits.csv housing.db && (git diff --cached --quiet || (git commit -q -m "Progress update $(date +%F' '%H:%M)" && git push -q)) \
    && echo "$(date +%H:%M) published"
  powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Select-Object -ExpandProperty CommandLine" 2>/dev/null | grep -qE "nhmeet.py crawl|ocr.py" || break
  sleep 1800
done
