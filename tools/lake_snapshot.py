"""
Builds the data snapshot for the Lake Travis app (apps/lake_travis).

  python tools/lake_snapshot.py <out.json>        (no key needed)

Data: Texas Water Development Board, Water Data for Texas (daily lake level and percent full,
from LCRA / USGS gauges): https://www.waterdatafortexas.org/reservoirs/individual/travis
The full history file is about 2 MB and slow (10-15 s), so the app gets only what it draws:
today's level and percent full, the levels 7 and 365 days ago, and 60 points for the 1-year chart.

Output: {"fetched_at", "date", "level", "pct", "week_ago", "year_ago", "series": [60 levels]}
"""

import csv
import io
import json
import sys
import time
import urllib.request
from datetime import date, timedelta

URL = "https://www.waterdatafortexas.org/reservoirs/individual/travis.csv"
CHART_POINTS = 60


def fetch(attempts=3):
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": "tidbyt-lake-travis/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8")
        except Exception:
            if attempt == attempts:
                raise
            time.sleep(10 * attempt)


def build():
    text = fetch()
    rows = [line for line in text.splitlines() if line and not line.startswith("#")]
    days = {}
    for r in csv.DictReader(io.StringIO("\n".join(rows))):
        try:
            days[date.fromisoformat(r["date"])] = (float(r["water_level"]), float(r["percent_full"]))
        except (ValueError, KeyError):
            continue
    latest = max(days)
    level, pct = days[latest]

    def level_on(d):
        # nearest earlier day with data (gauges miss the odd day)
        for k in range(10):
            if d - timedelta(days=k) in days:
                return days[d - timedelta(days=k)][0]
        return None

    step = 365 / (CHART_POINTS - 1)
    series = [level_on(latest - timedelta(days=round(365 - i * step))) for i in range(CHART_POINTS)]
    series = [round(v, 2) for v in series if v is not None]
    return {
        "fetched_at": int(time.time()),
        "date": latest.isoformat(),
        "level": round(level, 2),
        "pct": pct,
        "week_ago": level_on(latest - timedelta(days=7)),
        "year_ago": level_on(latest - timedelta(days=365)),
        "series": series,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    snap = build()
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(snap, f, separators=(",", ":"))
    print(snap["date"], snap["level"], "ft", snap["pct"], "% full | week ago", snap["week_ago"],
          "| year ago", snap["year_ago"], "|", len(snap["series"]), "chart points, low", min(snap["series"]))
