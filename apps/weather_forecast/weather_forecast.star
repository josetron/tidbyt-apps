"""
Applet: Weather Forecast
Summary: Forecast and 24h chart
Description: A 3-day forecast with animated pixel-art icons, highs/lows and rain
chance, followed by a 24-hour temperature / rain chart that draws itself.
Companion app: Weather Now. Weather and ZIP lookup both from Open-Meteo
(no API keys needed). Tuned for Gen 1 Tidbyt.
"""

load("http.star", "http")
load("math.star", "math")
load("render.star", "render")
load("schema.star", "schema")
load("time.star", "time")

DEFAULT_ZIP = "78620"
DEFAULT_UNITS = "imperial"

ZIP_URL = "https://geocoding-api.open-meteo.com/v1/search?name=%s&count=1&countryCode=US"
WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s" +
    "&current=temperature_2m" +
    "&hourly=temperature_2m,precipitation_probability" +
    "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max" +
    "&temperature_unit=%s&wind_speed_unit=%s&timezone=auto&forecast_days=4"
)

ZIP_TTL = 60 * 60 * 24 * 30  # ZIP coordinates never change
WEATHER_TTL = 60 * 10  # refresh weather every 10 minutes

DELAY_MS = 80
ICON_FRAMES = 12  # every icon animation loops cleanly in 12 frames

# Pixlet/Tidbyt cap an app's animation at 15s:
# 20 (location card) + 80 (forecast) + 23 (chart draws itself) + 50 (chart holds)
# = 173 frames * 80ms = 13.8s.
INTRO_FRAMES = 20  # 1.6s showing which location this forecast is for
FORECAST_FRAMES = 80  # 6.4s on the 3-day forecast
CHART_HOLD_FRAMES = 50  # 4.0s on the finished 24h chart

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
DIM = "#56606c"
DIVIDER = "#343c48"
WHITE = "#e8e8e8"
HI_COLOR = "#ff9d4a"
LO_COLOR = "#5fb4ff"
RAIN_TEXT = "#6fb8ff"

# ---------------------------------------------------------------------------
# Weather codes (WMO) -> icon kind + label
# ---------------------------------------------------------------------------

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
DROP = [".#.", "###", "###", ".#."]

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

def hour_label(iso):
    h = int(iso[11:13])
    suffix = "A" if h < 12 else "P"
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    return "%d%s" % (h12, suffix)

def hold(widget, frames):
    """Show a static widget for a fixed number of frames."""
    return render.Animation(children = [widget] * frames)

def spacer_frames(frames):
    return render.Animation(children = [render.Box(width = 1, height = 1)] * frames)

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

def forecast_column(wx, i, metric):
    daily = wx["daily"]
    day = time.parse_time(daily["time"][i], format = "2006-01-02").format("Mon").upper()
    code = int(daily["weather_code"][i])
    hi = iround(daily["temperature_2m_max"][i])
    lo = iround(daily["temperature_2m_min"][i])
    pop = iround(daily["precipitation_probability_max"][i] or 0)

    # "100/78" is too wide for the 21 px column, so 3-digit days get a 1 px gap instead of the
    # slash (the two numbers already differ in colour)
    separator = render.Text("/", font = SMALL, color = DIM)
    if len("%d%d" % (hi, lo)) > 4:
        separator = render.Box(width = 1, height = 1)

    return render.Box(
        width = 21,
        height = 32,
        child = render.Column(
            cross_align = "center",
            children = [
                render.Text(day, font = SMALL, color = WHITE),
                render.Padding(pad = (0, 1, 0, 1), child = icon_animation(code_kind(code), True, 12)),
                render.Row(children = [
                    render.Text("%d" % hi, font = SMALL, color = temp_color(hi, metric)),
                    separator,
                    render.Text("%d" % lo, font = SMALL, color = temp_color(lo, metric)),
                ]),
                render.Row(cross_align = "center", children = [
                    sprite_image(DROP, RAIN_TEXT if pop > 0 else DIM),
                    render.Text("%d%%" % pop, font = SMALL, color = RAIN_TEXT if pop > 0 else LABEL),
                ]),
            ],
        ),
    )

PIN = [".###.", "##.##", "#####", ".###.", "..#.."]

def intro_screen(place):
    """Title card: map pin + label, then the city name (wraps onto 2 lines if long)."""
    card = render.Box(
        width = 64,
        height = 32,
        child = render.Column(
            cross_align = "center",
            children = [
                render.Row(cross_align = "center", children = [
                    sprite_image(PIN, "#ff5a5a"),
                    render.Box(width = 2, height = 1),
                    render.Text("3-DAY FORECAST", font = SMALL, color = LABEL),
                ]),
                render.Box(width = 1, height = 3),
                render.WrappedText(place["city"], font = "tb-8", color = WHITE, align = "center", width = 64),
            ],
        ),
    )
    return hold(card, INTRO_FRAMES)

def forecast_screen(wx, metric):
    divider = render.Box(width = 1, height = 30, color = DIVIDER)
    return render.Stack(children = [
        spacer_frames(FORECAST_FRAMES),
        render.Row(cross_align = "center", children = [
            forecast_column(wx, 1, metric),
            divider,
            forecast_column(wx, 2, metric),
            divider,
            forecast_column(wx, 3, metric),
        ]),
    ])

def chart_screen(wx):
    cur_hour = wx["current"]["time"][:13]
    times = wx["hourly"]["time"]
    start = 0
    for i, t in enumerate(times):
        if t[:13] == cur_hour:
            start = i
            break
    end = min(start + 24, len(times))
    temps = wx["hourly"]["temperature_2m"][start:end]
    pops = wx["hourly"]["precipitation_probability"][start:end]
    hours = times[start:end]
    n = len(temps)

    t_min = min(temps)
    t_max = max(temps)
    pad = max(1.0, (t_max - t_min) * 0.15)
    y_lim = (t_min - pad, t_max + pad)
    x_lim = (0, 23)
    temp_pts = [(i, temps[i]) for i in range(n)]
    pop_pts = [(i, pops[i] or 0) for i in range(n)]
    any_rain = max([p[1] for p in pop_pts]) > 0

    header = render.Row(
        expanded = True,
        main_align = "space_between",
        children = [
            render.Text("NEXT 24H", font = SMALL, color = LABEL),
            render.Row(children = [
                render.Text("%d" % iround(t_max), font = SMALL, color = HI_COLOR),
                render.Text("/", font = SMALL, color = DIM),
                render.Text("%d" % iround(t_min), font = SMALL, color = LO_COLOR),
            ]),
        ],
    )

    labels = render.Row(children = [
        render.Box(width = 16, height = 6, child = render.Row(expanded = True, children = [
            render.Text(hour_label(hours[k]) if k < n else "", font = SMALL, color = LABEL),
        ]))
        for k in (0, 6, 12, 18)
    ])

    def chart(upto):
        layers = []
        if any_rain:
            layers.append(render.Plot(
                data = pop_pts[:upto],
                width = 64,
                height = 19,
                color = "#1f5fbf",
                fill = True,
                x_lim = x_lim,
                y_lim = (0, 100),
            ))
        layers.append(render.Plot(
            data = temp_pts[:upto],
            width = 64,
            height = 19,
            color = HI_COLOR,
            fill = not any_rain,  # with rain, the blue area is the rain chance
            fill_color = "#7a4216",
            x_lim = x_lim,
            y_lim = y_lim,
        ))
        return render.Column(children = [header, render.Stack(children = layers), labels])

    # Draw the line left-to-right, then hold the finished chart.
    frames = [chart(k) for k in range(2, n + 1)]
    frames.extend([frames[-1]] * CHART_HOLD_FRAMES)
    return render.Animation(children = frames)

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

    return render.Root(
        delay = DELAY_MS,
        show_full_animation = True,
        max_age = WEATHER_TTL,
        child = render.Sequence(children = [
            intro_screen(place),
            forecast_screen(wx, metric),
            chart_screen(wx),
        ]),
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
