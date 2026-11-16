"""
Applet: Dark Sky Tonight
Summary: Stargazing outlook tonight
Description: Tonight's stargazing outlook for a US ZIP code (setting `zip`, default 78620: Dripping
Springs, Texas, a Dark Sky Community). First a
starfield (more and brighter stars on a better night, drifting clouds when it's cloudy) with a
score out of 10, the best dark window and a dusk-to-dawn quality bar. Then the moon's phase and
when it rises or sets, which planets are up, dusk and dawn, and when the Milky Way core is out.
Data: tools/dark_sky_snapshot.py (astronomy computed there, clouds from Open-Meteo), passed in
as the `snapshot` config value.
"""

load("encoding/json.star", "json")
load("math.star", "math")
load("render.star", "render")
load("schema.star", "schema")

DEFAULT_ZIP = "78620"  # Dripping Springs, TX
DELAY_MS = 100
SCORE_FRAMES = 75  # 7.5 s
DETAIL_FRAMES = 75  # 7.5 s

SKY = "#070d22"
WHITE = "#f0f0f0"
GREY = "#9aa6bc"
LABEL = "#c8b4ff"
MOON_LIT = "#ece6cc"
MOON_DARK = "#363c50"
CLOUD = "#4a505e"
LABEL_COLORS = {"GREAT": "#5fe08a", "GOOD": "#5fd0ff", "FAIR": "#ffd04a", "POOR": "#ff7a5a"}
STAR_COLORS = ["#f4f4ff", "#c8d4ff", "#ffe8c8", "#9cb0e0", "#7f8fc0"]

def lcg(seed):
    return (seed * 1103515245 + 12345) % 2147483648

def stars(count, seed):
    # fixed pseudo-random star positions: (x, y, colour index, twinkle phase)
    out = []
    s = seed
    for _ in range(count):
        s = lcg(s)
        x = (s // 65536) % 64
        s = lcg(s)
        y = (s // 65536) % 24
        s = lcg(s)
        out.append((x, y, (s // 65536) % len(STAR_COLORS), (s // 4096) % 20))
    return out

def inside(x, y, masks):
    for x0, y0, x1, y1 in masks:
        if x >= x0 and x <= x1 and y >= y0 and y <= y1:
            return True
    return False

def star_layer(field, f, brightness, masks = []):
    # stars behind text would read as stray dots between the letters, so masked areas get none
    dots = []
    for x, y, c, phase in field:
        if inside(x, y, masks):
            continue

        # each star dims for a moment now and then; worse nights twinkle more
        if (f + phase) % 20 < (2 if brightness > 6 else 5):
            color = STAR_COLORS[4]
        else:
            color = STAR_COLORS[c]
        dots.append(render.Padding(pad = (x, y, 0, 0), child = render.Box(width = 1, height = 1, color = color)))
    return dots

def cloud_layer(clouds, f):
    # grey cloud banks drifting left; more and longer ones on cloudier nights
    if clouds < 25:
        return []
    banks = []
    n = 2 if clouds < 60 else 4
    for k in range(n):
        width = 14 + (clouds // 6) + 5 * k
        y = 2 + 6 * k
        x = (90 - (f // 2 + 23 * k) % 110) - 20
        banks.append(render.Padding(pad = (x, y, 0, 0), child = render.Box(width = width, height = 3, color = CLOUD)))
        banks.append(render.Padding(pad = (x + 3, y - 1, 0, 0), child = render.Box(width = max(2, width - 8), height = 1, color = CLOUD)))
    return banks

def bar_color(v):
    if v >= 80:
        return "#8fe6ff"
    if v >= 60:
        return "#4aa6e8"
    if v >= 40:
        return "#3c6fb0"
    if v >= 20:
        return "#3a4a78"
    return "#363a48"

def quality_bar(values, shown):
    cells = []
    for x in range(min(shown, len(values))):
        cells.append(render.Padding(pad = (2 + x, 29, 0, 0), child = render.Box(width = 1, height = 2, color = bar_color(values[x]))))
    return cells

def score_frames(snap, count):
    score = snap.get("score", 0)
    label = snap.get("label", "POOR")
    color = LABEL_COLORS.get(label, GREY)
    field = stars(6 + 4 * score, 7)
    clouds = snap.get("clouds", 0)
    best = snap.get("best")
    n = len(str(score))
    slash = score < 10  # "10/10" would crowd the window text
    info_x = 1 + 6 * n + (12 if slash else 0) + 3
    if best:
        info = [render.Text("BEST", font = "tom-thumb", color = GREY), render.Text(best[0].rstrip("AP") + "-" + best[1].rstrip("AP"), font = "tom-thumb", color = WHITE)]  # night is implied; saves 8 px
    else:
        info = [render.Text("STAY IN", font = "tom-thumb", color = GREY), render.Text(snap.get("reason", ""), font = "tom-thumb", color = color)]
    values = snap.get("bar", [])
    masks = [
        (0, 0, 33, 7),
        (62 - 4 * len(label), 0, 63, 7),
        (0, 9, info_x - 2, 22),
        (info_x - 1, 9, 63, 22),
        (0, 23, 22, 29),
        (40, 23, 63, 29),
    ]
    intro = 15  # 1.5 s of sky alone first

    frames = []
    for f in range(count):
        layers = [render.Box(width = 64, height = 32, color = SKY)]
        if f < intro:
            frames.append(render.Stack(children = layers + star_layer(field, f, score) + cloud_layer(clouds, f)))
            continue
        shown = int(len(values) * min(1.0, (f - intro + 1) / 12.0))
        score_row = [render.Text(str(score), font = "6x13", color = color)]
        if slash:
            score_row.append(render.Text("/10", font = "tom-thumb", color = GREY))
        frames.append(render.Stack(children = layers + star_layer(field, f, score, masks) + cloud_layer(clouds, f) + [
            render.Padding(pad = (1, 1, 0, 0), child = render.Text("DARK SKY", font = "tom-thumb", color = LABEL)),
            render.Padding(pad = (0, 1, 1, 0), child = render.Row(expanded = True, main_align = "end", children = [
                render.Text(label, font = "tom-thumb", color = color),
            ])),
            render.Padding(pad = (1, 10, 0, 0), child = render.Row(cross_align = "end", children = score_row)),
            render.Padding(pad = (info_x, 10, 0, 0), child = render.Column(children = info)),
            render.Padding(pad = (1, 24, 0, 0), child = render.Text(snap.get("dusk", ""), font = "tom-thumb", color = GREY)),
            render.Padding(pad = (0, 24, 1, 0), child = render.Row(expanded = True, main_align = "end", children = [
                render.Text(snap.get("dawn", ""), font = "tom-thumb", color = GREY),
            ])),
        ] + quality_bar(values, shown)))
    return frames

def moon_sprite(illum, waxing):
    # 13x13 moon: the lit part is on the right while waxing, on the left while waning
    r = 6
    t = 1 - 2 * illum / 100.0
    rows = []
    for yy in range(13):
        v = (yy - r) / (r + 0.5)
        runs = []
        for xx in range(13):
            u = (xx - r) / (r + 0.5)
            if u * u + v * v > 1:
                runs.append(render.Box(width = 1, height = 1))
                continue
            edge = t * math.sqrt(max(0.0, 1 - v * v))
            lit = (u > edge) if waxing else (-u > edge)
            runs.append(render.Box(width = 1, height = 1, color = MOON_LIT if lit else MOON_DARK))
        rows.append(render.Row(children = runs))
    return render.Column(children = rows)

DETAIL_MASKS = [(16, 1, 63, 15), (0, 16, 63, 31)]

def detail_lines(snap):
    # bottom line rotates through the place (if not the default), planets, Milky Way, dusk and dawn
    lines = []
    if snap.get("zip", DEFAULT_ZIP) != DEFAULT_ZIP and snap.get("place"):
        lines.append(("SKY OVER", snap["place"][:16]))
    planets = snap.get("planets", [])
    for i in range(0, len(planets), 2):
        names = " ".join(planets[i:i + 2])
        lines.append(("PLANETS", names))
    if snap.get("milky_way"):
        mw = snap["milky_way"]
        lines.append(("MILKY WAY", mw[0] + "-" + mw[1]))
    lines.append(("DARK FROM", snap.get("dusk", "")))
    lines.append(("DARK UNTIL", snap.get("dawn", "")))
    return lines

def detail_frames(snap, count):
    moon = snap.get("moon", {})
    illum = moon.get("illum", 0)
    field = stars(14, 11)
    sprite = moon_sprite(illum, moon.get("waxing", True)) if illum >= 3 else render.Box(width = 13, height = 13)
    phase = "NEW MOON" if illum < 3 else ("FULL MOON" if illum > 97 else "MOON %d%%" % illum)
    lines = detail_lines(snap)
    per = count // len(lines)

    frames = []
    for f in range(count):
        i = min(len(lines) - 1, f // per)
        local = f - i * per
        dy = int(math.round(6 * max(0.0, 1 - (local + 1) / 4.0))) if i > 0 else 0
        title, value = lines[i]
        frames.append(render.Stack(children = [render.Box(width = 64, height = 32, color = SKY)] + star_layer(field, f, 8, DETAIL_MASKS) + [
            render.Padding(pad = (1, 1, 0, 0), child = sprite),
            render.Padding(pad = (17, 2, 0, 0), child = render.Text(phase, font = "tom-thumb", color = WHITE)),
            render.Padding(pad = (17, 9, 0, 0), child = render.Text(moon.get("event", ""), font = "tom-thumb", color = GREY)),
            render.Padding(pad = (1, 17 + dy, 0, 0), child = render.Text(title, font = "tom-thumb", color = LABEL)),
            render.Padding(pad = (1, 24 + dy, 0, 0), child = render.Text(value, font = "tom-thumb", color = WHITE)),
        ]))
    return frames

def message(text):
    return render.Root(child = render.Box(color = SKY, child = render.WrappedText(text, font = "tom-thumb", color = LABEL, align = "center", width = 62)))

def main(config):
    raw = config.str("snapshot")
    if not raw:
        return message("DARK SKY: NO DATA YET")
    snap = json.decode(raw)
    wanted = (config.str("zip") or DEFAULT_ZIP).strip()[:5]
    if wanted != snap.get("zip", DEFAULT_ZIP):
        # the sky is computed for a place before the app runs; a new ZIP needs the next refresh
        return message("DARK SKY: NEW LOCATION %s, UPDATING SOON" % wanted)
    return render.Root(
        delay = DELAY_MS,
        show_full_animation = True,
        child = render.Sequence(children = [
            render.Animation(children = score_frames(snap, SCORE_FRAMES)),
            render.Animation(children = detail_frames(snap, DETAIL_FRAMES)),
        ]),
    )

def get_schema():
    return schema.Schema(
        version = "1",
        fields = [
            schema.Text(
                id = "zip",
                name = "ZIP code",
                desc = "US ZIP code for the sky forecast. Default: 78620 (Dripping Springs, TX).",
                icon = "locationDot",
                default = DEFAULT_ZIP,
            ),
        ],
    )
