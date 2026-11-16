"""
Applet: Lake Travis
Summary: Lake Travis water level
Description: Lake Travis water level for Tidbyt Gen 1. First a Hill Country lake scene where the
water sits at the real level (low water shows the pale "bathtub ring" on the limestone banks), a
sailboat bobbing on it, the level in feet and how full the lake is. Then a 1-year chart against the
681 ft full-pool line, with the change over the week and the year. Data: Texas Water Development
Board (Water Data for Texas), prepared by tools/lake_snapshot.py and passed in as `snapshot`.
Preview: tools/make_preview.py; ?level=632.3&pct=38.8 draws a drought year instead.
"""

load("encoding/json.star", "json")
load("math.star", "math")
load("render.star", "render")
load("schema.star", "schema")

DELAY_MS = 100
SCENE_FRAMES = 75  # 7.5 s
CHART_FRAMES = 75  # 7.5 s

FULL_POOL = 681.0  # ft above sea level; above it is flood storage
SCENE_LOW = 600.0  # bottom and top of the scene's elevation scale (record low 614, record high 710)
SCENE_HIGH = 720.0

WHITE = "#f4f4f4"
GREY = "#b8c0cc"
ORANGE = "#ff9a3a"
UP = "#5fe08a"
DOWN = "#ff6a5a"
WATER = "#1f6fc0"
WATER_DEEP = "#174f94"
WAVE = "#7fc4ff"
CHART_FILL = "#1d4f8f"
CHART_LINE = "#7fc4ff"
NIGHT = "#0e2350"
SKY = ["#24519c", "#2a5aa8", "#3164b2", "#386ebc", "#4078c4", "#4a82cc", "#548cd2", "#5e96d8"]
CEDAR = "#3c7a3a"
ROCK = ["#c2aa80", "#ad966e"]  # limestone strata
RING = "#e4dac2"  # bleached rock that the full lake normally covers

def fmt1(x):
    tenths = int(math.round(abs(x) * 10))
    return "%s%d.%d" % ("-" if x < 0 else "", tenths // 10, tenths % 10)

def pct_color(pct):
    if pct >= 99.5:
        return "#5fe0ff"
    if pct >= 80:
        return "#7fc4ff"
    if pct >= 55:
        return "#ffd04a"
    return "#ff8a4a"

def elev_y(level):
    # elevation -> screen row in the scene (32 rows; the lake bed is off the bottom)
    p = (level - SCENE_LOW) / (SCENE_HIGH - SCENE_LOW)
    return int(math.round(31 - p * 20))

def ground_y(x):
    # top of the banks for column x: a steep cliff on the left, a gentler shore on the right
    if x <= 18:
        return int(10 + x * 1.3)
    if x >= 44:
        return int(11 + (63 - x) * 1.05)
    return 40  # open water

# ---------------------------------------------------------------------------
# Lake scene
# ---------------------------------------------------------------------------

def column(x, top, bottom, color):
    if bottom < top:
        return None
    return render.Padding(pad = (x, top, 0, 0), child = render.Box(width = 1, height = bottom - top + 1, color = color))

def scene_static(surface):
    # sky, banks and still water; drawn once, reused on every frame
    full_y = elev_y(FULL_POOL)
    parts = [render.Column(children = [render.Box(width = 64, height = 4, color = c) for c in SKY])]
    parts.append(render.Padding(pad = (0, surface, 0, 0), child = render.Column(children = [
        render.Box(width = 64, height = 3, color = WATER),
        render.Box(width = 64, height = 32, color = WATER_DEEP),
    ])))
    for x in range(64):
        g = ground_y(x)
        if g > 31:
            continue
        parts.append(column(x, g, g + 1, CEDAR))
        for y0 in range(g + 2, 32, 3):
            # dry rock below the full-pool line is the pale "bathtub ring"
            color = RING if (y0 >= full_y and y0 < surface) else ROCK[(y0 // 3) % 2]
            parts.append(column(x, y0, min(31, y0 + 2), color))
    return [p for p in parts if p]

def boat(f):
    bob = 1 if (f // 6) % 2 == 0 else 0
    rows = [
        "..w....",
        "..ww...",
        "..www..",
        "..wwww.",
        "hhhhhhh",
        ".hhhhh.",
    ]
    colors = {"w": WHITE, "h": "#d04a3a"}
    lines = []
    for line in rows:
        runs = []
        for ch in line.elems():
            runs.append(render.Box(width = 1, height = 1, color = colors[ch]) if ch != "." else render.Box(width = 1, height = 1))
        lines.append(render.Row(children = runs))
    return render.Column(children = lines), bob

def scene_frames(snap, count):
    level = snap["level"]
    surface = max(2, min(31, elev_y(level)))
    static = scene_static(surface)
    pct = snap["pct"]
    status = "FULL" if pct >= 99.95 else "%d%% FULL" % int(math.round(pct))
    if level > FULL_POOL + 0.5:
        status = "FLOOD"
    hull, _ = boat(0)

    # open water span on the surface row, for the waves and the boat
    left = 0
    for x in range(64):
        if ground_y(x) > surface:
            left = x
            break
    right = 63
    for x in range(63, -1, -1):
        if ground_y(x) > surface:
            right = x
            break

    frames = []
    for f in range(count):
        waves = []
        for x in range(left, right + 1):
            if (x + f // 2) % 5 == 0:
                waves.append(render.Padding(pad = (x, surface, 0, 0), child = render.Box(width = 2 if x < right else 1, height = 1, color = WAVE)))
        span = max(1, right - left - 8)
        bx = left + span // 2 + int((f / max(1, count - 1)) * span * 0.4)  # drifts right, clear of the text
        if surface < 19:  # high water reaches the text: keep the boat right of it
            bx = 50 + int((f / max(1, count - 1)) * 6)
        bob = 1 if (f // 6) % 2 == 0 else 0
        text = [
            render.Padding(pad = (1, 1, 0, 0), child = render.Text("LAKE TRAVIS", font = "tom-thumb", color = WHITE)),
            render.Padding(pad = (1, 8, 0, 0), child = render.Row(children = [
                render.Text(fmt1(level) + "'", font = "tom-thumb", color = WHITE),
                render.Text(" " + status, font = "tom-thumb", color = pct_color(pct)),
            ])),
        ]
        frames.append(render.Stack(children = static + waves + [
            render.Padding(pad = (bx, surface - 5 + bob, 0, 0), child = hull),
        ] + text))
    return frames

# ---------------------------------------------------------------------------
# 1-year chart
# ---------------------------------------------------------------------------

def change_text(now, then, label):
    if then == None:
        return render.Text(label + " -", font = "tom-thumb", color = GREY)
    d = now - then
    arrow = "+" if d >= 0 else "-"
    color = UP if d > 0.05 else (DOWN if d < -0.05 else GREY)
    return render.Row(children = [
        render.Text(label + " ", font = "tom-thumb", color = GREY),
        render.Text(arrow + fmt1(abs(d)) + " FT", font = "tom-thumb", color = color),
    ])

def chart_frames(snap, count):
    series = snap.get("series", [])
    if len(series) < 2:
        series = [snap["level"], snap["level"]]
    lo = min(series + [FULL_POOL]) - 1.0
    hi = max(series + [FULL_POOL]) + 0.5
    top, bottom = 9, 31
    n = len(series)

    def y_of(v):
        return int(math.round(bottom - (v - lo) / (hi - lo) * (bottom - top)))

    xs = [2 + int(math.round(i * 59 / (n - 1))) for i in range(n)]
    full_y = y_of(FULL_POOL)
    dashes = [
        render.Padding(pad = (x, full_y, 0, 0), child = render.Box(width = 2, height = 1, color = ORANGE))
        for x in range(2, 62, 4)
    ]
    labels = [change_text(snap["level"], snap.get("week_ago"), "WEEK"), change_text(snap["level"], snap.get("year_ago"), "YEAR")]

    frames = []
    for f in range(count):
        shown = int(n * min(1.0, (f + 1) / 15.0))  # the line draws in over 1.5 s
        cols = []
        for i in range(shown):
            y = y_of(series[i])
            x = xs[i]
            w = (xs[i + 1] - x) if i + 1 < n else 1
            cols.append(render.Padding(pad = (x, y, 0, 0), child = render.Box(width = max(1, w), height = bottom - y + 1, color = CHART_FILL)))
            cols.append(render.Padding(pad = (x, y, 0, 0), child = render.Box(width = max(1, w), height = 1, color = CHART_LINE)))
        label = labels[0] if f < count // 2 else labels[1]
        frames.append(render.Stack(children = [render.Box(width = 64, height = 32, color = NIGHT)] + cols + dashes + [
            render.Padding(pad = (1, 1, 0, 0), child = label),
            render.Padding(pad = (1, full_y + 2, 0, 0), child = render.Text("FULL", font = "tom-thumb", color = ORANGE)),
        ]))
    return frames

# ---------------------------------------------------------------------------

def message(text):
    return render.Root(child = render.Box(color = NIGHT, child = render.WrappedText(text, font = "tom-thumb", color = WAVE, align = "center", width = 62)))

def main(config):
    raw = config.str("snapshot")
    if not raw:
        return message("LAKE TRAVIS: NO DATA YET")
    snap = json.decode(raw)
    if config.str("level"):  # preview only
        snap["level"] = float(config.str("level"))
        snap["pct"] = float(config.str("pct", "50"))
    return render.Root(
        delay = DELAY_MS,
        show_full_animation = True,
        child = render.Sequence(children = [
            render.Animation(children = scene_frames(snap, SCENE_FRAMES)),
            render.Animation(children = chart_frames(snap, CHART_FRAMES)),
        ]),
    )

def get_schema():
    return schema.Schema(version = "1", fields = [])
