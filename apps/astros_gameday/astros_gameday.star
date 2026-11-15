"""
Applet: Astros GameDay
Summary: Houston Astros game day
Description: Houston Astros games for Tidbyt Gen 1. Before a game: opponent, day and first-pitch
time (Houston time) and a countdown. During a game: the live score, inning, runners on base and
outs. After it: the final score with W or L, then the next game. Data: MLB Stats API (no key).
Preview switches: ?date=YYYY-MM-DD to look at that day, ?demo=live to draw that day's game as live.
"""

load("encoding/json.star", "json")
load("http.star", "http")
load("math.star", "math")
load("render.star", "render")
load("schema.star", "schema")
load("time.star", "time")

API = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=117&gameType=S,R,F,D,L,W"
TEAM = "HOU"
TZ = "America/Chicago"
FINAL_SHOW_HOURS = 14  # keep the final score up this long after the game

DELAY_MS = 100
FRAMES = 150  # 15.0 s
HALF = 75

ORANGE = "#ff7a1a"
ORANGE_LIGHT = "#ffa060"
NAVY = "#14306e"
WHITE = "#f4f4f4"
GREY = "#b8c0cc"
DIM = "#3a4660"
GREEN = "#3ddc6a"
RED = "#ff4a4a"
BLACK = "#000000"

# Box colour and text colour per team, brightened where the real colour vanishes on LEDs
TEAM_COLORS = {
    "ATH": ("#0f6b4b", "#ffd23c"),
    "ATL": ("#c8102e", WHITE),
    "AZ": ("#a71930", WHITE),
    "BAL": ("#df4601", BLACK),
    "BOS": ("#bd3039", WHITE),
    "CHC": ("#1d4fb0", WHITE),
    "CIN": ("#c6011f", WHITE),
    "CLE": ("#1d3f7a", "#ff5a5a"),
    "COL": ("#5a3e9e", WHITE),
    "CWS": ("#4a4a4a", WHITE),
    "DET": ("#24427a", "#ff8a3a"),
    "HOU": (NAVY, ORANGE),
    "KC": ("#1c5bb0", WHITE),
    "LAA": ("#ba0021", WHITE),
    "LAD": ("#1560c4", WHITE),
    "MIA": ("#00a3e0", BLACK),
    "MIL": ("#1d3a78", "#ffc52f"),
    "MIN": ("#1d3a78", "#e8364a"),
    "NYM": ("#1d4ab0", "#ff7a2a"),
    "NYY": ("#283c78", WHITE),
    "PHI": ("#e81828", WHITE),
    "PIT": ("#3a3a3a", "#fdb827"),
    "SD": ("#5a4636", "#ffc425"),
    "SEA": ("#0c5c63", WHITE),
    "SF": ("#fd5a1e", BLACK),
    "STL": ("#c41e3a", WHITE),
    "TB": ("#2a5ba0", "#8fbce6"),
    "TEX": ("#1d4ab0", "#ff4a4a"),
    "TOR": ("#1d5dc0", WHITE),
    "WSH": ("#ab0003", WHITE),
}

LOGO = [
    "....wwwww....",
    "..ww..o..ww..",
    ".w....o....w.",
    ".w...ooo...w.",
    "w.oohooohoo.w",
    "w..ohoooho..w",
    "w..ohhhhho..w",
    "w...hoooh...w",
    "w..ohoooho..w",
    ".w.oo...oo.w.",
    ".woo.....oow.",
    "..ww.....ww..",
    "....wwwww....",
]
LOGO_COLORS = {".": NAVY, "w": WHITE, "o": ORANGE, "h": WHITE}

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def fetch(start, end, hydrate, ttl):
    url = "%s&startDate=%s&endDate=%s&hydrate=%s" % (API, start, end, hydrate)
    rep = http.get(url, ttl_seconds = ttl)
    if rep.status_code != 200:
        return None
    games = []
    for d in rep.json().get("dates", []):
        games.extend(d.get("games", []))
    return games

def load_games(config, now):
    # The cloud job passes the games in (tools/gameday_snapshot.py fetches them with retries,
    # since the MLB API can take several seconds); without it, fetch directly.
    raw = config.str("snapshot")
    if raw:
        return json.decode(raw).get("games", []), True
    day = time.parse_duration("24h")
    return fetch((now - day).format("2006-01-02"), (now + day).format("2006-01-02"), "team,linescore", 60), False

def side_info(game):
    # (our side, their side) of the game record
    home = game["teams"]["home"]
    away = game["teams"]["away"]
    if home["team"].get("abbreviation") == TEAM:
        return home, away, True
    return away, home, False

def game_time(game):
    return time.parse_time(game["gameDate"]).in_location(TZ)

def state(game):
    return game.get("status", {}).get("abstractGameState", "Preview")

# ---------------------------------------------------------------------------
# Pieces
# ---------------------------------------------------------------------------

def logo():
    rows = []
    for line in LOGO:
        chars = line.elems()
        runs, x = [], 0
        for _ in range(len(chars)):
            if x >= len(chars):
                break
            n = 1
            for k in range(x + 1, len(chars)):
                if chars[k] != chars[x]:
                    break
                n += 1
            runs.append(render.Box(width = n, height = 1, color = LOGO_COLORS[chars[x]]))
            x += n
        rows.append(render.Row(children = runs))
    return render.Column(children = rows)

def header(title, tag = None, tag_color = WHITE):
    children = [
        render.Padding(pad = (1, 0, 0, 0), child = logo()),
        render.Padding(pad = (16, 2, 0, 0), child = render.Text(title, font = "tb-8", color = WHITE)),
        render.Padding(pad = (16, 11, 0, 0), child = render.Box(width = 47, height = 1, color = ORANGE)),
    ]
    if tag:
        children.append(render.Padding(pad = (0, 2, 1, 0), child = render.Row(expanded = True, main_align = "end", children = [
            render.Box(width = 4 * len(tag) + 1, height = 7, color = tag_color, child = render.Text(tag, font = "tom-thumb", color = BLACK)),
        ])))
    return children

def team_box(abbr, width = 19, height = 13):
    bg, fg = TEAM_COLORS.get(abbr, (DIM, WHITE))
    return render.Box(width = width, height = height, color = bg, child = render.Text(abbr, font = "5x8", color = fg))

def ease_out(p):
    p = min(1.0, max(0.0, p))
    return 1 - (1 - p) * (1 - p)

def slide(f, start, length, distance):
    return int(math.round(distance * (1 - ease_out((f - start + 1) / length))))

def background():
    return render.Box(width = 64, height = 32, color = NAVY)

def kind_tag(game):
    kind = game.get("gameType", "R")
    if kind == "S":
        return "SPRING"
    if kind in ("F", "D", "L", "W"):
        return {"F": "WILD CARD", "D": "ALDS", "L": "ALCS", "W": "WORLD SERIES"}[kind]
    return ""

# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------

def countdown(start, now):
    mins = int((start.unix - now.unix) // 60)
    if mins <= 0:
        return "STARTING"
    if mins < 60:
        return "IN %d MIN" % mins
    if mins < 24 * 60:
        return "IN %dH %dM" % (mins // 60, mins % 60)
    days = (mins + 12 * 60) // (24 * 60)
    return "IN %d DAY%s" % (days, "" if days == 1 else "S")

def when_label(start, now):
    today = now.format("2006-01-02")
    tomorrow = (now + time.parse_duration("24h")).format("2006-01-02")
    day = start.format("2006-01-02")
    clock = start.format("3:04PM")
    if day == today:
        return ("TONIGHT " if start.hour >= 17 else "TODAY ") + clock
    if day == tomorrow:
        return "TOMORROW " + clock if len(clock) <= 6 else "TMRW " + clock
    return start.format("Mon 1/2 ").upper() + clock

def next_frames(game, now, count):
    _, theirs, home = side_info(game)
    opp = theirs["team"].get("abbreviation", "?")
    start = game_time(game)
    status = game.get("status", {}).get("detailedState", "")
    tag = kind_tag(game)
    lines = [when_label(start, now), countdown(start, now)]
    if status in ("Postponed", "Cancelled", "Suspended"):
        lines = [status.upper(), when_label(start, now)]
    elif game.get("status", {}).get("startTimeTBD"):
        lines = [start.format("Mon 1/2").upper() + " TBD", countdown(start, now)]

    matchup = render.Row(cross_align = "center", children = [
        render.Text("VS " if home else "AT ", font = "5x8", color = GREY),
        team_box(opp, width = 4 + 5 * len(opp), height = 9),
        render.Text(" " + tag if tag and len(tag) <= 6 else "", font = "tom-thumb", color = ORANGE_LIGHT),
    ])

    frames = []
    for f in range(count):
        i = 0 if f < count // 2 else 1
        local = f if i == 0 else f - count // 2
        dy = slide(local, 0, 4, 7) if i == 1 else 0
        frames.append(render.Stack(children = [background()] + header("NEXT GAME") + [
            render.Padding(pad = (2 + slide(f, 0, 6, 64), 14, 0, 0), child = matchup),
            render.Padding(pad = (2 + (slide(f, 3, 6, 64) if i == 0 else 0), 25 + dy, 0, 0), child = render.Text(lines[i], font = "tom-thumb", color = WHITE)),
        ]))
    return frames

def final_frames(game, count):
    ours, theirs, _ = side_info(game)
    us, them = ours.get("score", 0), theirs.get("score", 0)
    won = ours.get("isWinner", us > them)
    tied = us == them
    opp = theirs["team"].get("abbreviation", "?")
    tag, color = ("W", GREEN) if won else (("T", GREY) if tied else ("L", RED))
    title = "FINAL"
    status = game.get("status", {}).get("detailedState", "")
    if status.startswith("Completed Early"):
        title = "FINAL*"

    def score_text(n, bright):
        return render.Text(str(n), font = "6x13", color = WHITE if bright else GREY)

    frames = []
    for f in range(count):
        x = slide(f, 0, 6, 64)
        frames.append(render.Stack(children = [background()] + header(title, " " + tag, color) + [
            render.Padding(pad = (1 - x, 16, 0, 0), child = render.Row(cross_align = "center", children = [
                team_box(TEAM),
                render.Box(width = 2, height = 1),
                score_text(us, us >= them),
            ])),
            render.Padding(pad = (x, 16, 1, 0), child = render.Row(expanded = True, main_align = "end", cross_align = "center", children = [
                score_text(them, them >= us),
                render.Box(width = 2, height = 1),
                team_box(opp),
            ])),
        ]))
    return frames

def base(on, blink):
    color = (ORANGE if blink else ORANGE_LIGHT) if on else DIM
    return render.Box(width = 5, height = 5, color = color)

def live_frames(game, count):
    ls = game.get("linescore", {})
    away = game["teams"]["away"]
    home = game["teams"]["home"]
    offense = ls.get("offense", {})
    inning = ls.get("currentInning")
    state_word = {"Top": "TOP", "Middle": "MID", "Bottom": "BOT", "End": "END"}.get(ls.get("inningState", ""), "")
    label = "%s %d" % (state_word, inning) if inning else game.get("status", {}).get("detailedState", "LIVE").upper()[:7]
    outs = ls.get("outs", 0) if state_word in ("TOP", "BOT") else 0
    show_bases = state_word in ("TOP", "BOT")

    def row(side, y):
        t = side["team"].get("abbreviation", "?")
        runs = ls.get("teams", {}).get("home" if side == home else "away", {}).get("runs", side.get("score", 0))
        return render.Padding(pad = (1, y, 0, 0), child = render.Row(cross_align = "center", children = [
            team_box(t),
            render.Box(width = 2, height = 1),
            render.Text(str(runs), font = "6x13", color = ORANGE if t == TEAM else WHITE),
        ]))

    frames = []
    for f in range(count):
        blink = (f // 5) % 2 == 0
        right = [
            render.Padding(pad = (41, 1, 0, 0), child = render.Text(label, font = "tom-thumb", color = ORANGE_LIGHT)),
        ]
        if show_bases:
            right.extend([
                render.Padding(pad = (49, 9, 0, 0), child = base("second" in offense, blink)),
                render.Padding(pad = (44, 14, 0, 0), child = base("third" in offense, blink)),
                render.Padding(pad = (54, 14, 0, 0), child = base("first" in offense, blink)),
            ])
            for k in range(3):
                right.append(render.Padding(pad = (44 + 5 * k, 25, 0, 0), child = render.Box(width = 3, height = 3, color = WHITE if k < outs else DIM)))
        frames.append(render.Stack(children = [
            background(),
            row(away, 2),
            row(home, 17),
            render.Padding(pad = (39, 0, 0, 0), child = render.Box(width = 1, height = 32, color = DIM)),
        ] + right))
    return frames

def message(text):
    return render.Root(child = render.Stack(children = [background()] + header("GAMEDAY") + [
        render.Padding(pad = (2, 15, 0, 0), child = render.WrappedText(text, font = "tom-thumb", color = GREY, width = 60)),
    ]))

# ---------------------------------------------------------------------------

def main(config):
    now = time.now().in_location(TZ)
    if config.str("date"):
        now = time.parse_time(config.str("date") + "T23:30:00", format = "2006-01-02T15:04:05", location = TZ)
    near, complete = load_games(config, now)  # a snapshot already includes the next game
    if near == None:
        return message("MLB DATA UNAVAILABLE")

    played = [g for g in near if g.get("linescore") and state(g) != "Preview"]
    if config.str("demo") == "live" and played:
        # preview only: draw a finished game as if it were the top of the 7th
        g = played[0]
        g["linescore"].update({"currentInning": 7, "inningState": "Top", "outs": 1, "offense": {"first": True, "third": True}})
        return root(render.Animation(children = live_frames(g, FRAMES)))

    for g in near:
        if state(g) == "Live":
            return root(render.Animation(children = live_frames(g, FRAMES)))

    recent = None
    for g in near:
        if state(g) == "Final" and now.unix - game_time(g).unix < (FINAL_SHOW_HOURS + 4) * 3600 and game_time(g).unix <= now.unix:
            recent = g

    upcoming = None
    for g in near:
        if state(g) == "Preview" and game_time(g).unix > now.unix - 3 * 3600:
            upcoming = g
            break
    if not upcoming and not complete:
        far = fetch(now.format("2006-01-02"), (now + time.parse_duration("4800h")).format("2006-01-02"), "team", 6 * 3600) or []
        for g in far:
            if state(g) == "Preview" and game_time(g).unix > now.unix:
                upcoming = g
                break

    if recent and upcoming:
        return root(render.Sequence(children = [
            render.Animation(children = final_frames(recent, HALF)),
            render.Animation(children = next_frames(upcoming, now, HALF)),
        ]))
    if recent:
        return root(render.Animation(children = final_frames(recent, FRAMES)))
    if upcoming:
        return root(render.Animation(children = next_frames(upcoming, now, FRAMES)))
    return message("NO ASTROS GAMES SCHEDULED")

def root(child):
    return render.Root(delay = DELAY_MS, show_full_animation = True, child = child)

def get_schema():
    return schema.Schema(version = "1", fields = [])
