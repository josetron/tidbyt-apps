"""
Renders Tidbyt apps and pushes them to the device. Run by GitHub Actions
(.github/workflows/tidbyt.yml), so no home PC is needed. Python 3 standard library only.

  python tools/cloud_push.py market [--hourly|--force]   MarketPulse + MarketPulse Stocks
  python tools/cloud_push.py weather            Weather Now, Weather Forecast, Pixel Museum, Pixel Aquarium, Astros News
  python tools/cloud_push.py movies             Now Playing (needs TMDB_API_KEY and Pillow)
  python tools/cloud_push.py stars              Astros Stars (needs Pillow)
  python tools/cloud_push.py gameday [--follow] Astros GameDay; --follow keeps running through a game

Environment:
  TIDBYT_API_TOKEN, TIDBYT_DEVICE_ID   (GitHub secrets; never stored in the repo)
  PIXLET                               path to pixlet (default "pixlet")
  MP_PAGE                              stocks page 0/1 (the workflow passes run_number % 2)
  MP_SNAPSHOT                          where the last good market snapshot is kept
                                       (the workflow restores/saves it with actions/cache)

Market rules (New York time): the 5-minute run pushes on weekdays 04:00-20:00 ET (pre, regular and
post market) and skips otherwise. The hourly run (--hourly) does the opposite: it pushes only outside
those hours, keeping the CLOSED cards current overnight and at weekends. --force always pushes.
If Yahoo fails, the last good snapshot is rendered so the apps show STALE instead of going blank.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIXLET = os.environ.get("PIXLET", "pixlet")

SYMBOLS = ["SPY", "QQQ", "DIA", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "HPQ"]
SPARK_URL = "https://query1.finance.yahoo.com/v7/finance/spark?symbols=%s&range=1d&interval=5m"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

MARKET_APPS = [
    ("apps/marketpulse/marketpulse.star", "marketpulse", False),
    ("apps/marketpulse_stocks/marketpulse_stocks.star", "marketpulsestocks", True),
]
WEATHER_APPS = [
    ("apps/weather_now/weather_now.star", "weathernow"),
    ("apps/weather_forecast/weather_forecast.star", "weatherforecast"),
    ("apps/pixel_museum/pixel_museum.star", "pixelmuseum"),
    ("apps/pixel_aquarium/pixel_aquarium.star", "pixelaquarium"),
    ("apps/astros_news/astros_news.star", "astrosnews"),
]


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def market_hours():
    ny = datetime.now(ZoneInfo("America/New_York"))
    mins = ny.hour * 60 + ny.minute
    return ny.weekday() < 5 and 240 <= mins < 1200


def fetch_snapshot():
    url = SPARK_URL % ",".join(SYMBOLS)
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = json.load(r)
            quotes = {}
            for res in raw.get("spark", {}).get("result", []):
                resp = (res.get("response") or [None])[0]
                if not resp:
                    continue
                m = resp["meta"]
                prev = m.get("chartPreviousClose") or m.get("previousClose")
                if not m.get("regularMarketPrice") or not prev:
                    continue
                q = (resp.get("indicators", {}).get("quote") or [{}])[0]
                periods = {
                    name: [int(p["start"]), int(p["end"])]
                    for name, p in (m.get("currentTradingPeriod") or {}).items()
                    if isinstance(p, dict) and "start" in p
                }
                quotes[res["symbol"]] = {
                    "price": m["regularMarketPrice"],
                    "prev": prev,
                    "time": int(m.get("regularMarketTime", 0)),
                    "closes": [round(c, 2) for c in (q.get("close") or []) if c is not None],
                    "periods": periods,
                }
            if len(quotes) >= 3:
                return {"fetched_at": int(time.time()), "quotes": quotes}
            log("fetch attempt %d: only %d quotes" % (attempt, len(quotes)))
        except Exception as e:  # network errors, HTTP 429, bad JSON
            log("fetch attempt %d failed: %s" % (attempt, e))
        if attempt < 3:
            time.sleep(10)
    return None


def render_and_push(star, installation_id, config, attempts=3):
    token = os.environ["TIDBYT_API_TOKEN"]
    device = os.environ["TIDBYT_DEVICE_ID"]
    out = os.path.join(tempfile.gettempdir(), installation_id + ".webp")
    args = [PIXLET, "render", os.path.join(ROOT, star)] + ["%s=%s" % kv for kv in config.items()] + ["-o", out]
    for attempt in range(1, attempts + 1):
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(out):
            break
        log("%s: render attempt %d failed: %s" % (installation_id, attempt, (r.stderr or r.stdout).strip()[-300:]))
        if attempt == attempts:
            return False
        time.sleep(15)
    r = subprocess.run(
        [PIXLET, "push", "--api-token", token, "--installation-id", installation_id, "--background", device, out],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        log("%s: push failed: %s" % (installation_id, (r.stderr or r.stdout).strip()[-300:]))
        return False
    log("%s: pushed OK (%d bytes)" % (installation_id, os.path.getsize(out)))
    return True


def run_market(force, hourly):
    active = market_hours()
    if not force and hourly and active:
        log("market hours: the 5-minute run handles it")
        return True
    if not force and not hourly and not active:
        log("outside 04:00-20:00 ET on a weekday: the hourly run handles it")
        return True
    snap_path = os.environ.get("MP_SNAPSHOT", os.path.join(ROOT, ".cache", "marketpulse_snapshot.json"))
    snap = fetch_snapshot()
    if snap:
        os.makedirs(os.path.dirname(snap_path), exist_ok=True)
        with open(snap_path, "w") as f:
            json.dump(snap, f, separators=(",", ":"))
        log("fetched %d quotes" % len(snap["quotes"]))
    elif os.path.exists(snap_path):
        with open(snap_path) as f:
            snap = json.load(f)
        log("fetch failed; rendering the last good snapshot (apps will show STALE)")
    else:
        log("no market data and no saved snapshot")
        return False

    snap_json = json.dumps(snap, separators=(",", ":"))
    page = os.environ.get("MP_PAGE", "0")
    ok = True
    for star, iid, paged in MARKET_APPS:
        config = {"snapshot": snap_json}
        if paged:
            config["page"] = page
        ok = render_and_push(star, iid, config, attempts=1) and ok
    return ok


def run_movies():
    snap_path = os.environ.get("NP_SNAPSHOT", os.path.join(ROOT, ".cache", "now_playing.json"))
    snap = None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import movies_snapshot
        snap = movies_snapshot.build(os.path.join(ROOT, ".cache", "imdb"))
        if not snap["movies"]:
            snap = None
    except Exception as e:
        log("movie fetch failed: %s" % e)
    if snap:
        os.makedirs(os.path.dirname(snap_path), exist_ok=True)
        with open(snap_path, "w") as f:
            json.dump(snap, f, separators=(",", ":"))
        log("fetched %d movies" % len(snap["movies"]))
    elif os.path.exists(snap_path):
        with open(snap_path) as f:
            snap = json.load(f)
        log("using the last good movie list")
    else:
        return False
    # Pass only this hour's pair: the stills make the full list too big for one config value
    movies = snap["movies"]
    start = (int(time.time()) // 3600 * 2) % len(movies)
    page = dict(snap, movies=(movies + movies)[start:start + 2])
    return render_and_push("apps/now_playing/now_playing.star", "nowplaying",
                           {"snapshot": json.dumps(page, separators=(",", ":")), "page": "0"})


def run_stars():
    snap_path = os.path.join(ROOT, ".cache", "astros_stars.json")
    snap = None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import stars_snapshot
        snap = stars_snapshot.build()
        if not snap["players"]:
            snap = None
    except Exception as e:
        log("stars fetch failed: %s" % e)
    if snap:
        os.makedirs(os.path.dirname(snap_path), exist_ok=True)
        with open(snap_path, "w") as f:
            json.dump(snap, f, separators=(",", ":"))
        log("fetched %d players" % len(snap["players"]))
    elif os.path.exists(snap_path):
        with open(snap_path) as f:
            snap = json.load(f)
        log("using the last good player list")
    else:
        return False
    # one star per hour, passed alone to keep the config value small
    players = snap["players"]
    one = dict(snap, players=[players[(int(time.time()) // 3600) % len(players)]])
    return render_and_push("apps/astros_stars/astros_stars.star", "astrosstars",
                           {"snapshot": json.dumps(one, separators=(",", ":")), "page": "0"})


FOLLOW_BUDGET = 340 * 60  # GitHub stops a job at 6 h; leave room to finish cleanly
LIVE_EVERY = 90           # seconds between pushes during a game


def run_gameday(follow):
    """Pushes the GameDay card. With --follow, when a game is live or starts within 5 hours,
    keeps running: a push every 30 min until 10 min before first pitch, then every 90 s
    until the final score is pushed (doubleheaders included)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gameday_snapshot

    def push():
        try:
            snap = gameday_snapshot.build()
        except Exception as e:
            log("gameday fetch failed: %s" % e)
            return None
        render_and_push("apps/astros_gameday/astros_gameday.star", "astrosgameday",
                             {"snapshot": json.dumps(snap, separators=(",", ":"))}, attempts=2)
        return snap

    snap = push()
    if not snap:
        return False
    if not follow:
        return True
    began = time.time()
    while time.time() - began < FOLLOW_BUDGET:
        ph, start = gameday_snapshot.phase(snap)
        if ph == "live":
            wait = LIVE_EVERY
        elif ph == "soon":
            wait = max(60, min(30 * 60, start.timestamp() - time.time() - 10 * 60))
        else:
            log("no game in progress or within 5 h; done")
            return True
        log("%s: next push in %d s" % (ph, wait))
        time.sleep(wait)
        snap = push() or snap
    log("time budget used; the next scheduled run carries on")
    return True


def run_weather():
    ok = True
    for star, iid in WEATHER_APPS:
        ok = render_and_push(star, iid, {}) and ok
    return ok


def main():
    group = sys.argv[1] if len(sys.argv) > 1 else ""
    force = "--force" in sys.argv
    if group == "market":
        ok = run_market(force, "--hourly" in sys.argv)
    elif group == "weather":
        ok = run_weather()
    elif group == "movies":
        ok = run_movies()
    elif group == "stars":
        ok = run_stars()
    elif group == "gameday":
        ok = run_gameday("--follow" in sys.argv)
    else:
        sys.exit(__doc__)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
