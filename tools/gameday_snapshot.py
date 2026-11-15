"""
Fetches Astros games for the Astros GameDay app (apps/astros_gameday) from the MLB Stats API.

  python tools/gameday_snapshot.py <out.json> [YYYY-MM-DD]     (no key needed)

The snapshot holds yesterday's, today's and tomorrow's games (with the live linescore) plus the
next scheduled game, trimmed to the fields the app uses, so it fits in one config value.
cloud_push.py uses phase() to decide whether to follow a game live.
"""

import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

API = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=117&gameType=S,R,F,D,L,W"
try:
    TZ = ZoneInfo("America/Chicago")
except Exception:  # Windows without the tzdata package: close enough for picking "today"
    TZ = timezone(timedelta(hours=-6))


def get_json(url, attempts=4):
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tidbyt-astros-gameday/1.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except Exception:
            if attempt == attempts:
                raise
            time.sleep(5 * attempt)


def games(start, end, hydrate):
    data = get_json("%s&startDate=%s&endDate=%s&hydrate=%s" % (API, start, end, hydrate))
    return [g for d in data.get("dates", []) for g in d.get("games", [])]


def trim(g):
    side = lambda s: {
        "team": {"abbreviation": s["team"].get("abbreviation", "?")},
        "score": s.get("score", 0),
        "isWinner": s.get("isWinner", False),
    }
    out = {
        "gamePk": g["gamePk"],
        "gameDate": g["gameDate"],
        "gameType": g.get("gameType", "R"),
        "status": {k: g["status"].get(k) for k in ("abstractGameState", "detailedState", "startTimeTBD")},
        "teams": {"home": side(g["teams"]["home"]), "away": side(g["teams"]["away"])},
    }
    ls = g.get("linescore")
    if ls:
        out["linescore"] = {
            "currentInning": ls.get("currentInning"),
            "inningState": ls.get("inningState", ""),
            "outs": ls.get("outs", 0),
            "offense": {b: True for b in ("first", "second", "third") if b in (ls.get("offense") or {})},
            "teams": {s: {"runs": ls.get("teams", {}).get(s, {}).get("runs", 0)} for s in ("home", "away")},
        }
    return out


def build(day=None):
    today = datetime.strptime(day, "%Y-%m-%d").date() if day else datetime.now(TZ).date()
    near = games(today - timedelta(days=1), today + timedelta(days=1), "team,linescore")
    now = datetime.now(timezone.utc)
    upcoming = [g for g in near if g["status"]["abstractGameState"] == "Preview"]
    if not upcoming:
        far = games(today, today + timedelta(days=200), "team")
        nxt = [g for g in far if g["status"]["abstractGameState"] == "Preview" and parse(g) > now]
        if nxt and nxt[0]["gamePk"] not in {g["gamePk"] for g in near}:
            near.append(nxt[0])
    return {"fetched_at": int(time.time()), "games": [trim(g) for g in near]}


def parse(g):
    return datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00"))


def phase(snap):
    """('live', None) during a game; ('soon', start) when the next game starts within 5 h;
    otherwise ('idle', start-or-None)."""
    now = datetime.now(timezone.utc)
    nxt = None
    for g in snap["games"]:
        st = g["status"]["abstractGameState"]
        if st == "Live":
            return "live", None
        if st == "Preview" and g["status"]["detailedState"] not in ("Postponed", "Cancelled"):
            start = parse(g)
            if start > now - timedelta(hours=1) and (nxt is None or start < nxt):
                nxt = start
    if nxt and nxt - now < timedelta(hours=5):
        return "soon", nxt
    return "idle", nxt


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    snap = build(sys.argv[2] if len(sys.argv) == 3 else None)
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(snap, f, separators=(",", ":"))
    for g in snap["games"]:
        t = g["teams"]
        print(g["gameDate"], g["gameType"], g["status"]["detailedState"], t["away"]["team"]["abbreviation"],
              t["away"]["score"], "@", t["home"]["team"]["abbreviation"], t["home"]["score"])
    print("phase:", phase(snap))
