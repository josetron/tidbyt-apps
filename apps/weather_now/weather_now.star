"""
Applet: Weather Now
Summary: Current weather conditions
Description: Current conditions with an animated pixel-art icon, big temperature,
today's high/low and a slow rotating detail line (city, condition, feels-like,
humidity, wind, rain chance, UV). Companion app: Weather Forecast.
Weather and ZIP lookup both from Open-Meteo (no API keys needed). Tuned for Gen 1 Tidbyt.
"""

load("http.star", "http")
load("math.star", "math")
load("render.star", "render")
load("schema.star", "schema")

DEFAULT_ZIP = "78620"
DEFAULT_UNITS = "imperial"

ZIP_URL = "https://geocoding-api.open-meteo.com/v1/search?name=%s&count=1&countryCode=US"
WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s" +
    "&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day," +
    "weather_code,wind_speed_10m,wind_direction_10m,uv_index" +
    "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max" +
    "&temperature_unit=%s&wind_speed_unit=%s&timezone=auto&forecast_days=4"
)

ZIP_TTL = 60 * 60 * 24 * 30  # ZIP coordinates never change
WEATHER_TTL = 60 * 10  # refresh weather every 10 minutes

DELAY_MS = 80
ICON_FRAMES = 12  # every icon animation loops cleanly in 12 frames

# Pixlet/Tidbyt cap an app's animation at 15s. Worst case (daytime, 7 ticker
# lines): 7 * 24 = 168 frames * 80ms = 13.4s, i.e. 1.9 seconds per detail.
# 24 is a multiple of ICON_FRAMES, so the icon is back at its first frame when
# the app loops (no jump).
INFO_FRAMES = 24  # how long each line of the rotating detail ticker shows

SMALL = "tom-thumb"

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

SUN_CORE = "#ffd93b"
SUN_EDGE = "#ffaa00"
SUN_RAY = "#ffc928"
MOON = "#f2eecb"
MOON_SHADE = "#c9c39a"
STAR_ON = "#ffffff"
STAR_OFF = "#50507a"
CLOUD = "#e8eef5"
CLOUD_SHADE = "#a9b6c4"
CLOUD_BACK = "#8f9aa8"
CLOUD_BACK_SHADE = "#66707c"
STORM = "#7a8290"
STORM_SHADE = "#4f5661"
STORM_FLASH = "#c8d0dc"
RAIN = "#4da6ff"
DRIZZLE = "#9fd0ff"
SNOW = "#ffffff"
FOG = "#aab3bd"
BOLT = "#ffe14d"

# Gen 1 Tidbyt LEDs barely show very dark colors, so "dim" UI colors stay
# above roughly #303030 to remain visible.
LABEL = "#7d8794"
DIVIDER = "#343c48"
WHITE = "#e8e8e8"
HI_COLOR = "#ff9d4a"
LO_COLOR = "#5fb4ff"
RAIN_TEXT = "#6fb8ff"

# ---------------------------------------------------------------------------
# Weather codes (WMO) -> icon kind + label
# ---------------------------------------------------------------------------

CODE_LABELS = {
    0: "Clear",
    1: "Mostly Clear",
    2: "Partly Cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Icy Fog",
    51: "Lt Drizzle",
    53: "Drizzle",
    55: "Hvy Drizzle",
    56: "Frz Drizzle",
    57: "Frz Drizzle",
    61: "Light Rain",
    63: "Rain",
    65: "Heavy Rain",
    66: "Freezing Rain",
    67: "Freezing Rain",
    71: "Light Snow",
    73: "Snow",
    75: "Heavy Snow",
    77: "Snow Grains",
    80: "Showers",
    81: "Showers",
    82: "Hvy Showers",
    85: "Snow Showers",
    86: "Snow Showers",
    95: "T-Storms",
    96: "T-Storm Hail",
    99: "T-Storm Hail",
}

KIND_COLORS = {
    "clear": SUN_CORE,
    "partly": "#ffe08a",
    "cloudy": CLOUD,
    "fog": FOG,
    "drizzle": DRIZZLE,
    "rain": RAIN,
    "snow": SNOW,
    "storm": BOLT,
}

def code_kind(code):
    if code == 0:
        return "clear"
    if code in (1, 2):
        return "partly"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if code in (51, 53, 55, 56, 57):
        return "drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "storm"
    return "cloudy"

def code_label(code, is_day):
    if code == 0 and is_day:
        return "Sunny"
    return CODE_LABELS.get(code, "Unknown")

# ---------------------------------------------------------------------------
# Pixel-art icon engine
#
# Icons are described in a 16x16 coordinate space as a stack of "layers"
# (functions of u, v that return a color or None). They are rasterized at any
# size, run-length encoded into crisp SVG rects, and shown with render.Image.
# ---------------------------------------------------------------------------

def to_svg(rows, w, h):
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % (w, h, w, h)]
    for y in range(h):
        row = rows[y]
        start = 0
        color = row[0]
        for x in range(1, w + 1):
            c = row[x] if x < w else "_end"
            if c != color:
                if color != None:
                    parts.append('<rect x="%d" y="%d" width="%d" height="1" fill="%s"/>' % (start, y, x - start, color))
                start = x
                color = c
    parts.append("</svg>")
    return "".join(parts)

def sprite_image(lines, color):
    """Tiny hand-drawn sprite from strings: '#' = color, '.' = empty."""
    rows = [[color if ch == "#" else None for ch in line.elems()] for line in lines]
    return render.Image(src = to_svg(rows, len(lines[0]), len(lines)))

def sun_layer(cx, cy, r, ray_len, rot):
    def layer(u, v):
        dx = u - cx
        dy = v - cy
        d = math.sqrt(dx * dx + dy * dy)
        if d <= r:
            return SUN_EDGE if d > r - 1.1 else SUN_CORE
        if d >= r + 1.1 and d <= r + 1.1 + ray_len:
            a = math.atan2(dy, dx) * 180.0 / math.pi - rot
            m = a % 45.0
            if m < 9.0 or m > 36.0:
                return SUN_RAY
        return None

    return layer

def moon_layer(cx, cy, r):
    def layer(u, v):
        dx = u - cx
        dy = v - cy
        if dx * dx + dy * dy > r * r:
            return None
        bx = u - (cx + r * 0.6)
        by = v - (cy - r * 0.35)
        cut = r * 0.8
        if bx * bx + by * by < cut * cut:
            return None
        return MOON_SHADE if dx + dy > r * 0.6 else MOON

    return layer

def stars_layer(f, n, points):
    def layer(u, v):
        for i, p in enumerate(points):
            if int(u) == p[0] and int(v) == p[1]:
                return STAR_ON if (f + i * 3) % n < n // 2 else STAR_OFF
        return None

    return layer

CLOUD_CIRCLES = [(5.0, 10.0, 3.3), (9.0, 7.2, 4.3), (12.6, 10.2, 3.0)]

def cloud_layer(ox, oy, k, body, shade):
    """Puffy cloud built from three circles + a flat base. k scales it."""

    def layer(u, v):
        x = (u - ox) / k
        y = (v - oy) / k
        inside = x >= 4.5 and x <= 12.8 and y >= 10.0 and y <= 13.3
        if not inside:
            for c in CLOUD_CIRCLES:
                dx = x - c[0]
                dy = y - c[1]
                if dx * dx + dy * dy <= c[2] * c[2]:
                    inside = True
                    break
        if not inside:
            return None
        return shade if y > 11.9 else body

    return layer

def drops_layer(f, xs, phases, top, span, speed, length, width, color, wobble):
    def layer(u, v):
        for i, x0 in enumerate(xs):
            y = top + (f * speed + phases[i]) % span
            x = x0
            if wobble:
                x = x0 + math.sin(2 * math.pi * (f / ICON_FRAMES) + i)
            if u >= x and u < x + width and v >= y and v < y + length:
                return color
        return None

    return layer

def fog_layer(f, n):
    def layer(u, v):
        for i, y in enumerate([4.0, 7.5, 11.0, 14.5]):
            if v >= y and v < y + 1.4:
                shift = 2.0 * math.sin(2 * math.pi * f / n + i * 1.7)
                start = 1.5 + shift + (i % 2) * 1.5
                if u >= start and u < start + 12.0:
                    return FOG if i % 2 == 0 else CLOUD_SHADE
        return None

    return layer

BOLT_PIXELS = [
    (9, 8),
    (10, 8),
    (8, 9),
    (9, 9),
    (7, 10),
    (8, 10),
    (7, 11),
    (8, 11),
    (9, 11),
    (10, 11),
    (9, 12),
    (8, 13),
    (9, 13),
    (7, 14),
    (8, 14),
    (7, 15),
]

def bolt_layer():
    def layer(u, v):
        if (int(u), int(v)) in BOLT_PIXELS:
            return BOLT
        return None

    return layer

def wave(f, n, amp):
    return amp * math.sin(2 * math.pi * f / n)

def icon_layers(kind, is_day, f, n):
    rot = 45.0 * f / n
    drift = wave(f, n, 1.0)
    if kind == "clear":
        if is_day:
            return [sun_layer(8.0, 8.0, 4.2, 2.6, rot)]
        return [
            stars_layer(f, n, [(2, 3), (13, 2), (14, 11), (2, 12), (11, 14)]),
            moon_layer(7.5, 8.0, 5.6),
        ]
    if kind == "partly":
        if is_day:
            return [
                sun_layer(10.5, 5.5, 3.0, 1.8, rot),
                cloud_layer(-1.0 + drift, 2.0, 0.95, CLOUD, CLOUD_SHADE),
            ]
        return [
            stars_layer(f, n, [(2, 2), (6, 1), (2, 7)]),
            moon_layer(11.0, 4.6, 4.2),
            cloud_layer(-1.5 + drift, 3.2, 0.9, CLOUD, CLOUD_SHADE),
        ]
    if kind == "cloudy":
        return [
            cloud_layer(3.0 - drift, -3.5, 0.8, CLOUD_BACK, CLOUD_BACK_SHADE),
            cloud_layer(-1.0 + drift, 1.5, 1.0, CLOUD, CLOUD_SHADE),
        ]
    if kind == "fog":
        return [fog_layer(f, n)]

    # Precipitation icons: cloud on top, stuff falling underneath.
    cloud = cloud_layer(0.0, -3.0, 1.0, CLOUD, CLOUD_SHADE)
    if kind == "drizzle":
        return [cloud, drops_layer(f, [3.5, 7.0, 10.5, 13.5], [0.0, 3.0, 1.5, 4.5], 10.5, 6.0, 0.5, 1.6, 1.5, DRIZZLE, False)]
    if kind == "rain":
        return [cloud, drops_layer(f, [2.5, 5.5, 8.5, 11.5, 14.0], [0.0, 3.0, 1.0, 4.0, 2.0], 10.0, 6.0, 1.0, 2.8, 1.5, RAIN, False)]
    if kind == "snow":
        return [cloud, drops_layer(f, [3.0, 6.5, 10.0, 13.0], [0.0, 3.0, 1.5, 4.5], 10.5, 6.0, 0.5, 1.6, 1.6, SNOW, True)]
    if kind == "storm":
        flash = f in (0, 1, 6)
        body = STORM_FLASH if flash else STORM
        layers = [
            cloud_layer(0.0, -3.0, 1.0, body, STORM_SHADE),
            drops_layer(f, [3.5, 12.5], [0.0, 3.0], 10.0, 6.0, 1.0, 2.0, 1.3, RAIN, False),
        ]
        if flash or f == 7:
            layers.append(bolt_layer())
        return layers
    return [cloud]

def icon_animation(kind, is_day, size):
    n = ICON_FRAMES
    s = 16.0 / size
    frames = []
    for f in range(n):
        layers = icon_layers(kind, is_day, f, n)
        rows = []
        for py in range(size):
            v = (py + 0.5) * s
            row = []
            for px in range(size):
                u = (px + 0.5) * s
                c = None
                for layer in layers:
                    lc = layer(u, v)
                    if lc != None:
                        c = lc
                row.append(c)
            rows.append(row)
        frames.append(render.Image(src = to_svg(rows, size, size), width = size, height = size))
    return render.Animation(children = frames)

# Little UI glyphs
UP_ARROW = [".#.", "###"]
DOWN_ARROW = ["###", ".#."]
DEGREE = [".#.", "#.#", ".#."]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def iround(x):
    return int(math.floor(x + 0.5))

def temp_color(t, metric):
    f = t * 9.0 / 5.0 + 32.0 if metric else t
    if f <= 32:
        return "#b8e4ff"
    if f < 50:
        return "#6cc0ff"
    if f < 65:
        return "#7fe3c4"
    if f < 80:
        return "#ffd75e"
    if f < 90:
        return "#ff9a3c"
    return "#ff5a3c"

def compass(deg):
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[iround(deg / 45.0) % 8]

def uv_color(uv):
    if uv < 3:
        return "#7fe37f"
    if uv < 6:
        return "#ffe14d"
    if uv < 8:
        return "#ff9a3c"
    return "#ff4a4a"

def hold(widget, frames):
    """Show a static widget for a fixed number of frames."""
    return render.Animation(children = [widget] * frames)

def label_value(label, value, color):
    return render.Row(
        children = [
            render.Text(label + " ", font = SMALL, color = LABEL),
            render.Text(value, font = SMALL, color = color),
        ],
    )

def error_screen(message):
    return render.Root(
        child = render.Box(
            child = render.Column(
                cross_align = "center",
                children = [
                    icon_animation("storm", True, 14),
                    render.WrappedText(message, font = SMALL, color = "#ff8080", align = "center", width = 62),
                ],
            ),
        ),
    )

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def lookup_zip(zip_code):
    rep = http.get(ZIP_URL % zip_code, ttl_seconds = ZIP_TTL)
    if rep.status_code != 200:
        return None
    results = rep.json().get("results") or []
    if not results:
        return None
    p = results[0]
    return {
        "lat": str(p["latitude"]),
        "lon": str(p["longitude"]),
        "city": p["name"],
    }

def fetch_weather(lat, lon, metric):
    url = WEATHER_URL % (lat, lon, "celsius" if metric else "fahrenheit", "kmh" if metric else "mph")
    rep = http.get(url, ttl_seconds = WEATHER_TTL)
    if rep.status_code != 200:
        return None
    return rep.json()

# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------

def now_screen(place, wx, metric, kind, is_day, code):
    cur = wx["current"]
    daily = wx["daily"]
    temp = iround(cur["temperature_2m"])
    hi = iround(daily["temperature_2m_max"][0])
    lo = iround(daily["temperature_2m_min"][0])
    tcolor = temp_color(temp, metric)
    temp_str = str(temp)

    big_temp = render.Row(
        cross_align = "start",
        children = [
            render.Text(temp_str, font = "10x20" if len(temp_str) <= 2 else "6x13", color = tcolor),
            render.Padding(pad = (1, 4, 0, 0), child = sprite_image(DEGREE, tcolor)),
        ],
    )

    hi_lo = render.Column(
        cross_align = "start",
        children = [
            render.Row(cross_align = "center", children = [
                sprite_image(UP_ARROW, HI_COLOR),
                render.Text(" %d" % hi, font = SMALL, color = HI_COLOR),
            ]),
            render.Box(width = 1, height = 3),
            render.Row(cross_align = "center", children = [
                sprite_image(DOWN_ARROW, LO_COLOR),
                render.Text(" %d" % lo, font = SMALL, color = LO_COLOR),
            ]),
        ],
    )

    top = render.Row(
        expanded = True,
        main_align = "space_evenly",
        cross_align = "center",
        children = [icon_animation(kind, is_day, 20), big_temp, hi_lo],
    )

    # Rotating detail ticker along the bottom.
    unit_wind = "KMH" if metric else "MPH"
    city = place["city"].upper()
    if len(city) > 16:  # tom-thumb is 4px per char -> 16 chars fit in 64px
        city = city[:16]
    items = [
        render.Text(city, font = SMALL, color = WHITE),
        render.Text(code_label(code, is_day).upper(), font = SMALL, color = KIND_COLORS[kind]),
        label_value("FEELS", "%d°" % iround(cur["apparent_temperature"]), temp_color(cur["apparent_temperature"], metric)),
        label_value("HUMID", "%d%%" % iround(cur["relative_humidity_2m"]), RAIN_TEXT),
        label_value("WIND", "%d%s %s" % (iround(cur["wind_speed_10m"]), unit_wind, compass(cur["wind_direction_10m"])), "#c6f0ff"),
        label_value("RAIN", "%d%%" % iround(daily["precipitation_probability_max"][0] or 0), RAIN_TEXT),
    ]
    if is_day:
        uv = cur.get("uv_index") or 0
        items.append(label_value("UV", "%d" % iround(uv), uv_color(uv)))

    ticker = render.Sequence(children = [
        hold(render.Box(width = 64, height = 7, child = item), INFO_FRAMES)
        for item in items
    ])

    return render.Column(children = [
        render.Box(width = 64, height = 23, child = top),
        render.Box(width = 64, height = 1, color = DIVIDER),
        ticker,
    ])

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(config):
    zip_code = (config.str("zip") or DEFAULT_ZIP).strip()[:5]
    metric = config.str("units", DEFAULT_UNITS) == "metric"

    if len(zip_code) != 5 or not zip_code.isdigit():
        return error_screen("Invalid ZIP code")

    place = lookup_zip(zip_code)
    if place == None:
        return error_screen("ZIP %s not found" % zip_code)

    wx = fetch_weather(place["lat"], place["lon"], metric)
    if wx == None:
        return error_screen("Weather service unavailable")

    code = int(wx["current"]["weather_code"])
    is_day = wx["current"]["is_day"] == 1

    # Debug overrides for previewing icons: ?demo_code=95&demo_time=night
    if config.str("demo_code"):
        code = int(config.str("demo_code"))
    if config.str("demo_time") in ("day", "night"):
        is_day = config.str("demo_time") == "day"

    kind = code_kind(code)

    return render.Root(
        delay = DELAY_MS,
        show_full_animation = True,
        max_age = WEATHER_TTL,
        child = now_screen(place, wx, metric, kind, is_day, code),
    )

def get_schema():
    return schema.Schema(
        version = "1",
        fields = [
            schema.Text(
                id = "zip",
                name = "ZIP code",
                desc = "US ZIP code for the weather location.",
                icon = "locationDot",
                default = DEFAULT_ZIP,
            ),
            schema.Dropdown(
                id = "units",
                name = "Units",
                desc = "Temperature and wind units.",
                icon = "temperatureHalf",
                default = DEFAULT_UNITS,
                options = [
                    schema.Option(display = "Fahrenheit / mph", value = "imperial"),
                    schema.Option(display = "Celsius / km/h", value = "metric"),
                ],
            ),
        ],
    )
