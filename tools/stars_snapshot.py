"""
Builds the data snapshot for the Astros Stars app (apps/astros_stars).

  python tools/stars_snapshot.py <out.json>        (needs Pillow; no API key)

- Roster, awards and season stats: MLB Stats API (statsapi.mlb.com, Astros teamId 117).
- Portraits: MLB's cut-out headshots, placed on Astros navy and shrunk to 24x32 with Pillow
  (blur, then average each cell, then lift colour and darks for the Gen 1 LEDs).
- The pool is the current 40-man roster: everyone with a notable MLB award in recent seasons,
  plus the core names in CORE, ordered by how big their best achievement is.

Output: {"fetched_at": unix, "season": 2026, "players": [{name, number, pos, big, small, stats, portrait}]}
"""

import base64
import io
import json
import re
import sys
import time
import unicodedata
import urllib.request

API = "https://statsapi.mlb.com/api/v1"
TEAM_ID = 117
HEADSHOT = ("https://img.mlbstatic.com/mlb-photos/image/upload/w_240,d_people:generic:headshot:silo:current.png,"
            "q_auto:best,f_png/v1/people/%d/headshot/silo/current")
PORTRAIT_W, PORTRAIT_H = 24, 32
NAVY = (20, 48, 110)
MAX_PLAYERS = 12
NAME_CHARS = 8  # 5x8 font in a 40 px panel

# Always in the rotation while they are on the roster
CORE = {514888, 670541, 665161, 686613, 623352, 621043}  # Altuve, Alvarez, Pena, Brown, Hader, Correa

# Shown by the name fans use; everyone else by last name
NICKNAMES = {670541: "YORDAN"}

# (pattern on the award name, priority, big label, small label; {y} = 'YY, {n} = All-Star count)
AWARDS = [
    (r"^(AL|NL) MVP$", 100, "{lg} MVP", "{yyyy}"),
    (r"^(AL|NL) Cy Young", 98, "CY YOUNG", "{lg} {yyyy}"),
    (r"^World Series MVP", 96, "WS MVP", "{yyyy}"),
    (r"^(AL|NL) Rookie of the Year$", 90, "{lg} ROY", "{yyyy}"),
    (r"^(ALCS|NLCS) MVP", 88, "{lg}CS MVP", "{yyyy}"),
    (r"^(AL|NL) Comeback Player of the Year$", 80, "COMEBACK", "PLAYER '{y}"),
    (r"^(AL|NL) Gold Glove", 75, "GOLD", "GLOVE '{y}"),
    (r"^(AL|NL) Silver Slugger", 75, "SILVER", "SLUGGER '{y}"),
    (r"^All-MLB First Team$", 72, "ALL-MLB", "1ST TEAM '{y}"),
    (r"^(AL|NL) All-Star$", 70, "ALL-STAR", "{n}X '{y}"),
    (r"^All-MLB Second Team$", 65, "ALL-MLB", "2ND TEAM '{y}"),
    (r"^(AL|NL) Reliever of the Month$", 52, "TOP ARM", "{lg} MONTH '{y}"),
    (r"^(AL|NL) Pitcher of the Month$", 52, "TOP ARM", "{lg} MONTH '{y}"),
    (r"^(AL|NL) Player of the Month$", 52, "TOP BAT", "{lg} MONTH '{y}"),
    (r"^World Series Championship$", 60, "CHAMPION", "WS {yyyy}"),
    (r"^(AL|NL) Player of the Week$", 30, "HOT BAT", "{lg} WEEK '{y}"),
    (r"^Astros Rookie of the Year$", 35, "TOP", "ROOKIE '{y}"),
    (r"^Astros Pitcher of the Year$", 40, "ACE", "ASTROS '{y}"),
]


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "tidbyt-astros-stars/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def plain(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").upper()


def current_season():
    t = time.gmtime()
    return t.tm_year if t.tm_mon >= 3 else t.tm_year - 1


def best_award(awards, season):
    allstar_years = {a.get("season") for a in awards if re.match(r"^(AL|NL) All-Star$", a.get("name", ""))}
    best, best_score = None, -1
    for a in awards:
        name, year = a.get("name", ""), int(a.get("season") or 0)
        for pattern, prio, big, small in AWARDS:
            m = re.match(pattern, name)
            if not m:
                continue
            score = prio - 12 * max(0, season - year)  # recent achievements first
            if big == "ALL-STAR":
                score += 3 * (len(allstar_years) - 1)  # 9X ALL-STAR beats a recent one-off
            if score > best_score:
                lg = (m.group(1) if m.groups() else "AL")[:2]
                fields = {"lg": lg, "yyyy": year, "y": "%02d" % (year % 100), "n": len(allstar_years)}
                best_score, best = score, (big.format(**fields), small.format(**fields))
            break
    if best and best[0] == "ALL-STAR" and len(allstar_years) == 1:
        best = ("ALL-STAR", "%d" % max(int(y) for y in allstar_years))
    return best, best_score


def season_stats(person, pitcher):
    group = "pitching" if pitcher else "hitting"
    for s in person.get("stats", []):
        if s.get("group", {}).get("displayName") == group and s.get("splits"):
            return s["splits"][0]["stat"]
    return None


def stat_lines(stat, pitcher):
    """Two or three short stat strings (value, label) for the bottom line."""
    if not stat:
        return []
    if pitcher:
        out = []
        if stat.get("saves", 0) >= 5:
            out.append([str(stat["saves"]), "SAVES"])
        else:
            out.append(["%d-%d" % (stat.get("wins", 0), stat.get("losses", 0)), "W-L"])
        out.append([stat.get("era", "-"), "ERA"])
        out.append([str(stat.get("strikeOuts", 0)), "K"])
        return out
    return [
        [stat.get("avg", "-"), "AVG"],
        [str(stat.get("homeRuns", 0)), "HR"],
        [str(stat.get("rbi", 0)), "RBI"],
    ]


def stat_achievement(stat, pitcher, season):
    # for players without awards: their standout number
    if not stat:
        return ("ASTRO", "%d" % season)
    if pitcher:
        if stat.get("saves", 0) >= 10:
            return ("%d SV" % stat["saves"], "%d SEASON" % season)
        return ("%d K" % stat.get("strikeOuts", 0), "%d SEASON" % season)
    return ("%d HR" % stat.get("homeRuns", 0), "%d SEASON" % season)


def display_name(person):
    if person["id"] in NICKNAMES:
        return NICKNAMES[person["id"]]
    first = plain(person.get("useName") or person.get("firstName", ""))
    last = plain(person.get("useLastName") or person.get("lastName", ""))
    if len(last) <= NAME_CHARS:
        return last
    if len(first) <= NAME_CHARS:
        return first
    return last[:NAME_CHARS]


def portrait(player_id):
    from PIL import Image, ImageEnhance, ImageFilter

    req = urllib.request.Request(HEADSHOT % player_id, headers={"User-Agent": "tidbyt-astros-stars/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        im = Image.open(io.BytesIO(r.read())).convert("RGBA")
    iw, ih = im.size
    nw = int(ih * PORTRAIT_W / PORTRAIT_H)
    im = im.crop(((iw - nw) // 2, 0, (iw - nw) // 2 + nw, ih))

    # shrink the player and the cut-out mask separately, so the navy stays exactly navy
    scale = im.width / PORTRAIT_W
    rgb = im.convert("RGB").filter(ImageFilter.GaussianBlur(scale * 0.35)).resize((PORTRAIT_W, PORTRAIT_H), Image.BOX)
    mask = im.split()[3].resize((PORTRAIT_W, PORTRAIT_H), Image.BOX)
    rgb = ImageEnhance.Color(rgb).enhance(1.3)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.2)
    lut = [int(255 * ((i / 255) ** 0.8)) for i in range(256)]
    rgb = rgb.point(lut * 3)
    out = Image.new("RGB", (PORTRAIT_W, PORTRAIT_H), NAVY)
    out.paste(rgb, (0, 0), mask)
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def build():
    season = current_season()
    roster = get_json("%s/teams/%d/roster?rosterType=40Man&season=%d" % (API, TEAM_ID, season))["roster"]
    ids = [p["person"]["id"] for p in roster]
    people = get_json(
        "%s/people?personIds=%s&hydrate=awards,stats(group=[hitting,pitching],type=[season],season=%d)"
        % (API, ",".join(map(str, ids)), season)
    )["people"]

    pool = []
    for person in people:
        pid = person["id"]
        pitcher = person.get("primaryPosition", {}).get("abbreviation") == "P"
        award, score = best_award(person.get("awards", []), season)
        if score < 45 and pid not in CORE:
            continue
        stat = season_stats(person, pitcher)
        big, small = award or stat_achievement(stat, pitcher, season)
        pool.append((score + (20 if pid in CORE else 0), {
            "id": pid,
            "name": display_name(person),
            "number": person.get("primaryNumber", ""),
            "pos": person.get("primaryPosition", {}).get("abbreviation", ""),
            "big": big,
            "small": small,
            "stats": stat_lines(stat, pitcher),
        }))

    pool.sort(key=lambda p: -p[0])
    players = []
    for _, p in pool[:MAX_PLAYERS]:
        try:
            p["portrait"] = portrait(p["id"])
        except Exception as e:  # a missing photo shouldn't drop the player
            print("portrait failed for %s: %s" % (p["name"], e), file=sys.stderr)
            p["portrait"] = ""
        players.append(p)
    return {"fetched_at": int(time.time()), "season": season, "players": players}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    snap = build()
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(snap, f, separators=(",", ":"))
    for p in snap["players"]:
        print("%-9s #%-3s %-3s %-9s %-14s %s" % (p["name"], p["number"], p["pos"], p["big"], p["small"],
                                               " ".join("%s %s" % tuple(s) for s in p["stats"])))
