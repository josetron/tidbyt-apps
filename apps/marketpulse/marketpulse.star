"""
Applet: MarketPulse
Summary: Market ETFs at a glance
Description: Market overview for Tidbyt Gen 1. The S&P 500, Nasdaq-100 and Dow are tracked
through their ETF proxies SPY, QQQ and DIA (labelled as ETFs, not the indices themselves).
Screen 1: all three with green/red arrows, daily % change (then price) and intraday sparklines.
Screen 2: S&P 500 ETF detail with price, change and a sparkline against yesterday's close.
Shows the market status (OPEN / PRE / POST / CLOSED) and a STALE flag when data is old.
Prices are shown for information only. Companion app: MarketPulse Stocks.

Data: Yahoo Finance "spark" endpoint (unofficial, no key), or a `snapshot` config value
(compact JSON written by the push script; see DESIGN.md). Preview switches:
  demo_status=OPEN|PRE|POST|CLOSED   force the status chip
  demo_stale=true                    force the STALE state
"""

load("encoding/json.star", "json")
load("http.star", "http")
load("humanize.star", "humanize")
load("math.star", "math")
load("render.star", "render")
load("schema.star", "schema")
load("time.star", "time")

ETFS = [
    {"symbol": "SPY", "name": "S&P500 ETF"},
    {"symbol": "QQQ", "name": "NDX100 ETF"},
    {"symbol": "DIA", "name": "DOW30 ETF"},
]

SPARK_URL = "https://query1.finance.yahoo.com/v7/finance/spark?symbols=%s&range=1d&interval=5m"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}  # Yahoo returns 429 without it
CACHE_TTL = 240

STALE_AFTER = 15 * 60  # data this old while a session is running = STALE
NY = "America/New_York"

# Timing (Gen 1: whole animation under 15 s) -> 2 screens x 7.2 s = 14.4 s
DELAY_MS = 100
SCREEN_FRAMES = 72
DRAW_FRAMES = 10  # sparklines draw in over the first second

# Palette (bright enough for Gen 1 LEDs)
UP = "#33dd66"
DOWN = "#ff4a4a"
FLAT = "#9aa4b0"
AMBER = "#ffb000"
WHITE = "#e8e8e8"
LABEL = "#7d8794"
DIM = "#4a525c"
BASELINE = "#5a6470"
SMALL = "tom-thumb"

# ---------------------------------------------------------------------------
# Formatting (Starlark has no %.2f)
# ---------------------------------------------------------------------------

def two_dp(v):
    c = int(math.round(abs(v) * 100))
    return "%d.%s" % (c // 100, str(100 + c % 100)[1:])

def fmt_price(p):
    if p >= 1000:
        return humanize.comma(int(math.round(p)))
    return two_dp(p)

def fmt_pct(pct):
    return two_dp(pct) + "%"

def fmt_change(ch):
    return ("+" if ch >= 0 else "-") + two_dp(ch)

def direction_color(pct):
    if pct > 0.005:
        return UP
    if pct < -0.005:
        return DOWN
    return FLAT

# ---------------------------------------------------------------------------
# Sprites
# ---------------------------------------------------------------------------

def sprite(lines, color):
    rects = []
    for y, line in enumerate(lines):
        for x, ch in enumerate(line.elems()):
            if ch == "#":
                rects.append('<rect x="%d" y="%d" width="1" height="1" fill="%s"/>' % (x, y, color))
    w, h = len(lines[0]), len(lines)
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d">%s</svg>' % (w, h, "".join(rects))
    return render.Image(src = svg, width = w, height = h)

def arrow(pct):
    c = direction_color(pct)
    if c == UP:
        return sprite(["..#..", ".###.", "#####"], c)
    if c == DOWN:
        return sprite(["#####", ".###.", "..#.."], c)
    return sprite([".....", "#####", "....."], c)

# ---------------------------------------------------------------------------
# Data: live fetch or snapshot, both normalised to the snapshot shape
#   {"fetched_at": unix, "quotes": {SYM: {price, prev, time, closes[], periods{name: [start, end]}}}}
# ---------------------------------------------------------------------------

def fetch_live(symbols):
    rep = http.get(SPARK_URL % ",".join(symbols), headers = HEADERS, ttl_seconds = CACHE_TTL)
    if rep.status_code != 200:
        return None
    quotes = {}
    for r in rep.json().get("spark", {}).get("result", []):
        resp = (r.get("response") or [None])[0]
        if not resp:
            continue
        m = resp["meta"]
        q = resp.get("indicators", {}).get("quote", [{}])[0]
        periods = {}
        for name, p in m.get("currentTradingPeriod", {}).items():
            if type(p) == "dict" and "start" in p:
                periods[name] = [int(p["start"]), int(p["end"])]
        quotes[r["symbol"]] = {
            "price": m.get("regularMarketPrice"),
            "prev": m.get("chartPreviousClose") or m.get("previousClose"),
            "time": int(m.get("regularMarketTime", 0)),
            "closes": [c for c in (q.get("close") or []) if c != None],
            "periods": periods,
        }
    return {"fetched_at": time.now().unix, "quotes": quotes}

def load_data(config, symbols):
    if config.str("snapshot"):
        return json.decode(config.str("snapshot"))
    return fetch_live(symbols)

def enrich(sym, q):
    q = dict(q)
    q["symbol"] = sym
    q["pct"] = (q["price"] - q["prev"]) / q["prev"] * 100
    q["change"] = q["price"] - q["prev"]
    return q

def market_status(q, now):
    for name, label in (("regular", "OPEN"), ("pre", "PRE"), ("post", "POST")):
        p = q["periods"].get(name)
        if p and p[0] <= now and now < p[1]:
            return label
    return "CLOSED"

# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

def status_chip(status, stale, blink_on):
    if stale:
        return render.Text("STALE", font = SMALL, color = DOWN if blink_on else DIM)
    return render.Text(status, font = SMALL, color = {"OPEN": UP, "PRE": AMBER, "POST": AMBER}.get(status, FLAT))

def sparkline(q, width, height, upto, baseline):
    closes = q["closes"]
    if len(closes) < 2:
        return render.Box(width = width, height = height)
    lo = min(closes + [q["prev"]])
    hi = max(closes + [q["prev"]])
    if hi - lo < 0.0001:
        hi = lo + 1
    n = len(closes)
    shown = max(2, int(n * upto))
    plot = render.Plot(
        data = [(i, closes[i]) for i in range(shown)],
        width = width,
        height = height,
        color = direction_color(q["pct"]),
        x_lim = (0, n - 1),
        y_lim = (lo, hi),
    )
    if not baseline:
        return plot

    # dotted line at yesterday's close: above/below reads instantly
    y = int(math.round((hi - q["prev"]) / (hi - lo) * (height - 1)))
    dots = render.Row(children = [
        render.Box(width = 1, height = 1, color = BASELINE if x % 3 == 0 else "#00000000")
        for x in range(width)
    ])
    return render.Stack(children = [render.Padding(pad = (0, y, 0, 0), child = dots), plot])

def quote_row(q, show_price, upto):
    value = fmt_price(q["price"]) if show_price else fmt_pct(q["pct"])
    return render.Row(
        cross_align = "center",
        children = [
            render.Box(width = 16, height = 8, child = render.Row(expanded = True, children = [
                render.Text(q["symbol"], font = "5x8", color = WHITE),
            ])),
            render.Box(width = 6, height = 8, child = arrow(q["pct"])),
            render.Box(width = 24, height = 8, child = render.Row(expanded = True, main_align = "end", children = [
                render.Text(value, font = SMALL, color = WHITE if show_price else direction_color(q["pct"])),
            ])),
            render.Box(width = 1, height = 8),
            sparkline(q, 17, 7, upto, False),
        ],
    )

def overview_screen(etfs, status, stale, clock):
    frames = []
    for f in range(SCREEN_FRAMES):
        upto = min(1.0, (f + 1) / DRAW_FRAMES)
        show_price = f >= SCREEN_FRAMES // 2  # first half % change, second half price
        blink_on = (f // 5) % 2 == 0
        frames.append(render.Column(children = [
            render.Row(expanded = True, main_align = "space_between", children = [
                render.Text("ETFs", font = SMALL, color = LABEL),
                render.Row(children = [status_chip(status, stale, blink_on), render.Box(width = 3, height = 1), render.Text(clock, font = SMALL, color = LABEL)]),
            ]),
            render.Box(width = 64, height = 1),
        ] + [quote_row(q, show_price, upto) for q in etfs]))
    return render.Animation(children = frames)

def detail_screen(q, name, status, stale, clock):
    color = direction_color(q["pct"])
    frames = []
    for f in range(SCREEN_FRAMES):
        upto = min(1.0, (f + 1) / DRAW_FRAMES)
        blink_on = (f // 5) % 2 == 0
        if f < SCREEN_FRAMES // 2:
            corner = render.Text(name, font = SMALL, color = LABEL)  # first half: which index this ETF tracks
        else:
            corner = render.Row(children = [status_chip(status, stale, blink_on), render.Box(width = 3, height = 1), render.Text(clock, font = SMALL, color = LABEL)])
        frames.append(render.Column(children = [
            render.Row(expanded = True, main_align = "space_between", children = [
                render.Text(q["symbol"], font = SMALL, color = WHITE),
                corner,
            ]),
            render.Row(expanded = True, main_align = "space_between", cross_align = "center", children = [
                render.Text(fmt_price(q["price"]), font = "6x13", color = WHITE),
                render.Column(cross_align = "end", children = [
                    render.Row(cross_align = "center", children = [
                        arrow(q["pct"]),
                        render.Box(width = 1, height = 1),
                        render.Text(fmt_pct(q["pct"]), font = SMALL, color = color),
                    ]),
                    render.Text(fmt_change(q["change"]), font = SMALL, color = color),
                ]),
            ]),
            sparkline(q, 64, 11, upto, True),
        ]))
    return render.Animation(children = frames)

def message(text):
    return render.Root(child = render.Box(child = render.WrappedText(text, font = SMALL, color = AMBER, align = "center", width = 62)))

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(config):
    symbols = [e["symbol"] for e in ETFS]
    data = load_data(config, symbols)
    if not data or "SPY" not in data.get("quotes", {}):
        return message("MarketPulse: no market data")

    quotes = data["quotes"]
    now = time.now().unix
    status = market_status(quotes["SPY"], now)
    stale = status != "CLOSED" and now - int(data["fetched_at"]) > STALE_AFTER

    if config.str("demo_status"):
        status = config.str("demo_status").upper()
        stale = False
    if config.bool("demo_stale"):
        stale = True

    # Clock shows when the data is from (last trade), in New York time
    last = max([int(quotes[s]["time"]) for s in symbols if s in quotes])
    clock = time.from_timestamp(last if status == "CLOSED" else now).in_location(NY).format("3:04")

    etfs = [enrich(s, quotes[s]) for s in symbols if s in quotes]
    detail = config.str("detail", "SPY")
    focus = [q for q in etfs if q["symbol"] == detail] or etfs[:1]
    names = {e["symbol"]: e["name"] for e in ETFS}

    return render.Root(
        delay = DELAY_MS,
        show_full_animation = True,
        child = render.Sequence(children = [
            overview_screen(etfs, status, stale, clock),
            detail_screen(focus[0], names[focus[0]["symbol"]], status, stale, clock),
        ]),
    )

def get_schema():
    return schema.Schema(
        version = "1",
        fields = [
            schema.Dropdown(
                id = "detail",
                name = "Detail screen",
                desc = "Which ETF gets the large chart on screen 2.",
                icon = "chartLine",
                default = "SPY",
                options = [
                    schema.Option(display = "SPY (S&P 500 ETF)", value = "SPY"),
                    schema.Option(display = "QQQ (Nasdaq-100 ETF)", value = "QQQ"),
                    schema.Option(display = "DIA (Dow 30 ETF)", value = "DIA"),
                ],
            ),
        ],
    )
