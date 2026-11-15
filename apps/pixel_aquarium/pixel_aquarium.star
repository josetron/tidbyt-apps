"""
Applet: Pixel Aquarium
Summary: Animated pixel fish tank
Description: A living pixel-art aquarium for Tidbyt Gen 1. Fish swim both ways at different
speeds and depths, seaweed sways, bubbles rise, a crab patrols the sand and a treasure chest
opens to release a burst of bubbles. Day and night lighting follows the local time (a glowing
jellyfish visits at night), and every refresh picks a new mix of fish.
The 15 s animation loops seamlessly: every motion repeats a whole number of times per loop.
Preview switches: ?mode=day|night, ?seed=<n> for a specific fish mix.
"""

load("math.star", "math")
load("render.star", "render")
load("schema.star", "schema")
load("time.star", "time")

W = 64
H = 32
DELAY_MS = 100
FRAMES = 150  # 15.0 s: the Gen 1 limit; all periods below divide 150
SAND_Y = 27
DEFAULT_TZ = "America/Chicago"
ROTATE_EVERY_SECONDS = 15 * 60  # new fish mix each refresh

# ---------------------------------------------------------------------------
# Sprites (right-facing; "." = transparent). Left-facing versions are mirrored.
# ---------------------------------------------------------------------------

SPECIES = {
    "clownfish": {
        "colors": {"o": "#ff7a1a", "w": "#ffffff", "k": "#202020"},
        "rows": [
            "o...oow..",
            "oo.woowk.",
            "ooowoowoo",
            "oo.woowo.",
            "o...oow..",
        ],
    },
    "blue_tang": {
        "colors": {"b": "#2a74ff", "d": "#123a9a", "y": "#ffd400", "k": "#101010"},
        "rows": [
            "....bbbb..",
            "y..bddbbb.",
            "yybbbddbkb",
            "yybbbbbbbb",
            "y..bbbbbb.",
            "....bbb...",
        ],
    },
    "yellow_tang": {
        "colors": {"y": "#ffe020", "w": "#ffffff", "k": "#202020"},
        "rows": [
            "...yy...",
            "..yyyy..",
            "y.yyyyy.",
            "yyyyyykw",
            "y.yyyyy.",
            "..yyyy..",
            "...yy...",
        ],
    },
    "goldfish": {
        "colors": {"g": "#ffa31a", "l": "#ffd27a", "k": "#202020"},
        "rows": [
            "ll..ggg..",
            ".lggggggg",
            "llgggggkg",
            ".lggggggg",
            "ll..ggg..",
        ],
    },
    "tetras": {
        # a little school of neon tetras
        "colors": {"c": "#20e0ff", "r": "#ff3a4a", "s": "#c8d0d8"},
        "rows": [
            "..sss..........",
            "srrccc.........",
            "..sss....sss...",
            ".........rrccc.",
            "...sss...sss...",
            "..rrccc........",
            "...sss.........",
        ],
    },
    "angelfish": {
        "colors": {"a": "#e8e8f0", "s": "#4a5060", "k": "#202020"},
        "rows": [
            "..a.....",
            "..aa....",
            "a.asaa..",
            "aaasaasa",
            "aaasaaka",
            "a.asaas.",
            "..aa....",
            "..a.....",
        ],
    },
}

CRAB = {
    "colors": {"r": "#ff4a30", "w": "#ffffff"},
    "rows": [
        "r.w.w.r",
        "rrrrrrr",
        ".rrrrr.",
        "r.r.r.r",
    ],
}

JELLY = {
    "colors": {"p": "#ff70d0", "q": "#ffb0ea"},
    "rows": [
        ".qqq.",
        "qpppq",
        "ppppp",
        "p.p.p",
        "p.p.p",
        ".p.p.",
        "p...p",
    ],
}

CHEST_CLOSED = {
    "colors": {"b": "#9a6230", "g": "#ffcc33"},
    "rows": [
        "........",
        ".bbbbbb.",
        "bbbbbbbb",
        "gggggggg",
        "bbbgbbbb",
        "bbbbbbbb",
    ],
}

CHEST_OPEN = {
    "colors": {"b": "#9a6230", "g": "#ffcc33", "y": "#fff27a"},
    "rows": [
        ".bbbbbb.",
        "b......b",
        "gygygyyg",
        "gggggggg",
        "bbbgbbbb",
        "bbbbbbbb",
    ],
}

# Light / dark palettes
PALETTES = {
    "day": {
        "water": ["#3a9ad8", "#2f8ccb", "#2880bf", "#2273b2", "#1d68a6", "#185d99", "#14538d", "#114a82"],
        "surface": ["#9fe0ff", "#6cc6f2"],
        "ray": "#ffffff22",
        "sand": ["#d8b878", "#c9a868", "#b89858", "#a88a4c", "#9a7c42"],
        "weed": ["#3ed45a", "#22a83c"],
        "rock": ["#8a949c", "#6c767e"],
        "bubble": "#d8f4ff",
    },
    "night": {
        "water": ["#1a4a80", "#174377", "#143d6e", "#123766", "#10325e", "#0e2d57", "#0d2950", "#0c264a"],
        "surface": ["#4f86c0", "#3a70aa"],
        "ray": "#c8dcff14",
        "sand": ["#8a7a58", "#7e6f50", "#726448", "#665a42", "#5c513c"],
        "weed": ["#2e9e48", "#1f7a36"],
        "rock": ["#5e6870", "#4c565e"],
        "bubble": "#a8c8ee",
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def lcg(n):
    return (n * 1103515245 + 12345) % 2147483648

def pick(r, n):
    return (r // 65536) % n  # the high bits of an LCG are the random-looking ones

def svg_image(w, h, rects):
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" shape-rendering="crispEdges">%s</svg>' % (w, h, "".join(rects))
    return render.Image(src = svg, width = w, height = h)

def rect(x, y, w, h, color):
    if len(color) == 9:  # "#rrggbbaa": SVG wants the alpha as fill-opacity
        alpha = int(color[7:], 16) / 255.0
        return '<rect x="%d" y="%d" width="%d" height="%d" fill="%s" fill-opacity="%s"/>' % (x, y, w, h, color[:7], str(alpha)[:5])
    return '<rect x="%d" y="%d" width="%d" height="%d" fill="%s"/>' % (x, y, w, h, color)

def sprite(spec, flip = False):
    # Built from boxes, not SVG: Pixlet draws an SVG's transparent areas as black,
    # while an empty Box stays see-through. Runs of one colour become one wider box.
    rows = spec["rows"]
    w, h = len(rows[0]), len(rows)
    lines = []
    for line in rows:
        chars = line.elems()
        if flip:
            chars = list(reversed(chars))
        runs = []
        x = 0
        for _ in range(w):
            if x >= w:
                break
            ch = chars[x]
            n = 1
            for k in range(x + 1, w):
                if chars[k] != ch:
                    break
                n += 1
            c = spec["colors"].get(ch)
            runs.append(render.Box(width = n, height = 1, color = c) if c else render.Box(width = n, height = 1))
            x += n
        lines.append(render.Row(children = runs))
    return render.Column(children = lines), w, h

def place(x, y, child):
    # Padding moves a child anywhere, including partly off-screen (negative values)
    return render.Padding(pad = (x, y, 0, 0), child = child)

def wave(t, period, phase = 0.0):
    return math.sin(2 * math.pi * (t / period + phase))

# ---------------------------------------------------------------------------
# Static scene: water gradient, light rays, sand, rocks
# ---------------------------------------------------------------------------

def background(pal):
    rects = []
    bands = pal["water"]
    for y in range(SAND_Y + 1):  # one row deeper so dips in the sand edge show water, not black
        rects.append(rect(0, y, W, 1, bands[min(len(bands) - 1, y * len(bands) // SAND_Y)]))

    # slanted light rays from the surface
    for x0 in (10, 30, 47):
        for y in range(1, SAND_Y - 4):
            rects.append(rect(x0 + y // 3, y, 2, 1, pal["ray"]))

    # sand with a gently uneven top edge and some speckles
    for x in range(W):
        top = SAND_Y + (1 if (x // 7) % 3 == 1 else 0)
        for y in range(top, H):
            rects.append(rect(x, y, 1, 1, pal["sand"][min(4, y - SAND_Y + (1 if x * 7 % 3 == 0 else 0))]))

    # rocks
    for x, y, w, h, c in ((16, 25, 5, 3, 0), (17, 24, 3, 1, 0), (19, 26, 4, 2, 1), (40, 26, 4, 2, 0), (41, 25, 2, 1, 1)):
        rects.append(rect(x, y, w, h, pal["rock"][c]))
    return svg_image(W, H, rects)

def surface(pal, t):
    # shimmering top row: a light dash pattern sliding sideways (period 50 frames)
    shift = (t * 8 // 50) % 8
    rects = [rect(0, 0, W, 1, pal["surface"][1])]
    for x in range(-8, W, 8):
        rects.append(rect(x + shift, 0, 3, 1, pal["surface"][0]))
    return svg_image(W, 1, rects)

# ---------------------------------------------------------------------------
# Seaweed: strands sway with height (period 50 frames, 10 drawn phases)
# ---------------------------------------------------------------------------

WEEDS = [(3, 14, 0.0), (6, 10, 0.3), (24, 12, 0.6), (35, 8, 0.15), (55, 15, 0.45), (58, 11, 0.8)]

def weeds_layer(pal, phase_index):
    pixels = []
    t = phase_index / 10.0
    for x0, height, ph in WEEDS:
        for i in range(height):
            y = SAND_Y - 1 - i
            sway = int(math.round(1.6 * (i / height) * math.sin(2 * math.pi * (t + ph) + i * 0.35)))
            pixels.append(place(x0 + sway, y, render.Box(width = 1, height = 1, color = pal["weed"][(i // 2) % 2])))
            if i % 4 == 2 and i < height - 1:  # little leaves
                pixels.append(place(x0 + sway + (1 if i % 8 == 2 else -1), y, render.Box(width = 1, height = 1, color = pal["weed"][0])))
    return render.Stack(children = pixels)

# ---------------------------------------------------------------------------
# Inhabitants
# ---------------------------------------------------------------------------

LANES = [2, 7, 12, 17]

def choose_fish(seed, count):
    names = sorted(SPECIES.keys())
    fish = []
    r = lcg(seed + 17)
    used = []
    for i in range(count):
        r = lcg(r)
        name = names[pick(r, len(names))]
        if name in used:  # prefer variety
            name = [n for n in names if n not in used][0] if len(used) < len(names) else name
        used.append(name)
        r = lcg(r)
        fish.append({
            "name": name,
            "lane": LANES[i % len(LANES)],
            "right": pick(r, 2) == 0,
            "laps": 2 if name == "tetras" else 1,  # tetras dart across twice per loop
            "offset": pick(lcg(r + 1), 100) / 100.0,
            "bob_phase": pick(lcg(r + 2), 100) / 100.0,
        })
    return fish

def fish_widgets(fish):
    out = []
    for f in fish:
        img, w, h = sprite(SPECIES[f["name"]], flip = not f["right"])
        out.append((f, img, w, h))
    return out

def fish_at(f, img, w, h, t):
    span = W + w + 6
    p = (f["laps"] * t / FRAMES + f["offset"]) % 1.0
    x = int(p * span) - w - 3
    if not f["right"]:
        x = W - w - x
    y = f["lane"] + int(math.round(1.2 * wave(t, 75, f["bob_phase"])))  # period 75 divides 150
    y = min(y, SAND_Y - h - 1)
    return place(x, y, img)

def crab_at(img, t):
    # walks right then back (ping-pong over the whole loop), pausing at the ends
    p = wave(t, FRAMES, 0.0)
    x = 26 + int(math.round(p * 9))
    lift = 1 if (t // 3) % 2 == 0 else 0  # scuttle
    return place(x, SAND_Y + 1 - lift, img)

def jelly_at(img, t):
    # drifts up and down slowly while pulsing
    y = 6 + int(math.round(4 * wave(t, FRAMES, 0.25)))
    x = 44 + int(math.round(1.5 * wave(t, 50, 0.1)))
    return place(x, y, img)

def bubbles(pal, t, chest_open_from, chest_open_to):
    out = []

    # bubbler stream behind the left seaweed: 5 bubbles, lifetime 30 frames
    for i in range(5):
        age = (t + i * 6) % 30
        y = SAND_Y - 2 - age * (SAND_Y - 2) // 30
        x = 9 + int(math.round(wave(t + i * 6, 10)))
        out.append(place(x, y, render.Box(width = 1, height = 1, color = pal["bubble"])))

    # chest burst
    if chest_open_from <= t and t < chest_open_to + 20:
        for i in range(6):
            start = chest_open_from + i * 4
            age = t - start
            if age < 0 or age > 26:
                continue
            y = SAND_Y - 4 - age
            x = 50 + (i * 3) % 6 + int(math.round(wave(age + i * 2, 8)))
            size = 2 if i % 3 == 0 else 1
            if y >= 1:
                out.append(place(x, y, render.Box(width = size, height = size, color = pal["bubble"])))
    return out

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(config):
    tz = config.get("$tz", DEFAULT_TZ)
    now = time.now().in_location(tz)
    mode = config.str("mode", "auto")
    if mode == "auto":
        mode = "night" if now.hour >= 20 or now.hour < 7 else "day"
    pal = PALETTES[mode]

    seed = int(config.str("seed", str(now.unix // ROTATE_EVERY_SECONDS)))
    count = int(config.str("fish", "4"))
    if mode == "night":
        count = max(2, count - 1)  # a few fish are asleep

    fish = fish_widgets(choose_fish(seed, count))
    bg = background(pal)
    weed_phases = [weeds_layer(pal, i) for i in range(10)]
    crab, _, _ = sprite(CRAB)
    jelly, _, _ = sprite(JELLY)
    jelly_dim, _, _ = sprite({"colors": {"p": "#c050a8", "q": "#ff90dc"}, "rows": JELLY["rows"]})
    chest_closed, _, _ = sprite(CHEST_CLOSED)
    chest_open, _, _ = sprite(CHEST_OPEN)
    open_from, open_to = 70, 95

    frames = []
    for t in range(FRAMES):
        layers = [bg, surface(pal, t), weed_phases[(t // 5) % 10]]
        if mode == "night":
            layers.append(jelly_at(jelly if (t // 5) % 2 == 0 else jelly_dim, t))
        layers.append(place(48, SAND_Y - 4, chest_open if open_from <= t and t < open_to else chest_closed))
        layers.extend(bubbles(pal, t, open_from, open_to))
        layers.extend([fish_at(f, img, w, h, t) for f, img, w, h in fish])
        layers.append(crab_at(crab, t))
        frames.append(render.Stack(children = layers))

    return render.Root(
        delay = DELAY_MS,
        show_full_animation = True,
        child = render.Animation(children = frames),
    )

def get_schema():
    return schema.Schema(
        version = "1",
        fields = [
            schema.Dropdown(
                id = "mode",
                name = "Lighting",
                desc = "Day and night follow your local time, or pick one.",
                icon = "sun",
                default = "auto",
                options = [
                    schema.Option(display = "Automatic", value = "auto"),
                    schema.Option(display = "Always day", value = "day"),
                    schema.Option(display = "Always night", value = "night"),
                ],
            ),
            schema.Dropdown(
                id = "fish",
                name = "Fish",
                desc = "How many fish groups swim in the tank.",
                icon = "fish",
                default = "4",
                options = [schema.Option(display = str(n), value = str(n)) for n in (2, 3, 4)],
            ),
        ],
    )
