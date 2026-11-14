"""
Applet: MarketPulse Stocks
Summary: Stocks with logos
Description: Companion to MarketPulse for Tidbyt Gen 1. One card per stock (default AAPL, MSFT,
NVDA, AMZN, GOOGL, HPQ): pixel-art logo, ticker, price, green/red arrow with daily % and change, and an
intraday sparkline against yesterday's close. Shows the market status (OPEN / PRE / POST /
CLOSED) and a blinking STALE flag when data is old. Prices are shown for information only.

Data: Yahoo Finance "spark" endpoint (unofficial, no key), or a `snapshot` config value
(compact JSON written by the push script; see ../marketpulse/DESIGN.md). Preview switches:
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

DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "HPQ"]

SPARK_URL = "https://query1.finance.yahoo.com/v7/finance/spark?symbols=%s&range=1d&interval=5m"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}  # Yahoo returns 429 without it
CACHE_TTL = 240

STALE_AFTER = 15 * 60
NY = "America/New_York"

# Timing (Gen 1: whole animation within 15 s) -> 3 cards x 5 s = 15 s.
# Six stocks don't fit at 5 s each, so each push shows one "page" of 3 and the
# next push shows the other page (the push script passes page=0/1; without it
# the page follows the clock, changing every 5 minutes).
DELAY_MS = 100
CARD_FRAMES = 50
DRAW_FRAMES = 10
PER_PAGE = 3
PAGE_SECONDS = 300

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
# Logos: 16x16 pixel art, one character per pixel ("." = transparent)
# ---------------------------------------------------------------------------

LOGOS = {
    "AAPL": {
        "colors": {"g": "#61bb46", "y": "#fdb827", "o": "#f5821f", "r": "#e03a3e", "p": "#a64ca6", "b": "#009ddc"},
        "rows": [
            "..........g.....",
            ".........gg.....",
            "........gg......",
            "...gggg.ggggg...",
            "..gggggggggggg..",
            ".yyyyyyyyyyy....",
            ".yyyyyyyyyy.....",
            ".oooooooooo.....",
            ".oooooooooo.....",
            ".rrrrrrrrrrr....",
            ".rrrrrrrrrrrr...",
            "..pppppppppppp..",
            "..ppppppppppp...",
            "...bbbbbbbbbb...",
            "....bbb..bbb....",
            "................",
        ],
    },
    "MSFT": {
        "colors": {"r": "#f25022", "g": "#7fba00", "b": "#00a4ef", "y": "#ffb900"},
        "rows": [
            "rrrrrrr.ggggggg."
            for _ in range(7)
        ] + ["................"] + [
            "bbbbbbb.yyyyyyy."
            for _ in range(7)
        ] + ["................"],
    },
    "NVDA": {
        "colors": {"g": "#76b900"},
        "rows": [
            "gggggggggggggggg",
            "gggggggggggggggg",
            "gggggggggggggggg",
            "gggggg....gggggg",
            "gggg..gggg..gggg",
            "ggg.gggggggg.ggg",
            "gg.ggg....ggg.gg",
            "g.ggg..gg..ggg.g",
            "g.ggg..gg..ggg.g",
            "gg.ggg....ggg.gg",
            "ggg.gggggggg.ggg",
            "gggg..gggg..gggg",
            "gggggg....gggggg",
            "gggggggggggggggg",
            "gggggggggggggggg",
            "gggggggggggggggg",
        ],
    },
    "AMZN": {
        "colors": {"w": "#e8e8e8", "o": "#ff9900"},
        "rows": [
            "................",
            "................",
            "....######......",
            "...##....##.....",
            ".........##.....",
            "....#######.....",
            "...##....##.....",
            "...##....##.....",
            "...##...###.....",
            "....#####.##....",
            "................",
            ".o..........ooo.",
            "..oo.........oo.",
            "....ooooooooo.o.",
            "................",
            "................",
        ],
    },
    "GOOGL": {
        "colors": {"r": "#ea4335", "y": "#fbbc05", "g": "#34a853", "b": "#4285f4"},
        "rows": [
            ".....rrrrrr.....",
            "...rrrrrrrrrr...",
            "..rrrrrrrrrrrr..",
            ".rrrr......rrr..",
            ".yyy............",
            "yyy.............",
            "yyy.....bbbbbbbb",
            "yyy.....bbbbbbbb",
            "yyy.....bbbbbbbb",
            "ggg..........bbb",
            ".ggg........bbb.",
            ".gggg......bbbb.",
            "..gggggggggbbb..",
            "...gggggggggg...",
            ".....gggggg.....",
            "................",
        ],
    },
    "HPQ": {
        "colors": {"b": "#0096d6", "w": "#ffffff"},
        "rows": [
            ".....bbbbbb.....",
            "...bbbbbbbbbb...",
            "..bbbbbbbbbbbb..",
            ".bbbwbbbbbbbbbb.",
            ".bbbwbbbbbbbbbb.",
            "bbbwwwwbbwwwwbbb",
            "bbbwbbwbbwbbwbbb",
            "bbbwbbwbbwbbwbbb",
            "bbbwbbwbbwwwwbbb",
            "bbbwbbwbbwbbbbbb",
            ".bbbbbbbbwbbbbb.",
            ".bbbbbbbbwbbbbb.",
            "..bbbbbbbbbbbb..",
            "...bbbbbbbbbb...",
            ".....bbbbbb.....",
            "................",
        ],
    },
}

FALLBACK_COLORS = ["#3a7bd5", "#8e44ad", "#d35400", "#16a085", "#c0392b"]

# ---------------------------------------------------------------------------
# Formatting (Starlark has no %.2f)
# ---------------------------------------------------------------------------

def two_dp(v):
    c = int(math.round(abs(v) * 100))
    return "%d.%s" % (c // 100, str(100 + c % 100)[1:])

def fmt_price(p):
    if p >= 10000:
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

def pixel_svg(rows, colors):
    rects = []
    for y, line in enumerate(rows):
        for x, ch in enumerate(line.elems()):
            c = colors.get(ch)
            if c:
                rects.append('<rect x="%d" y="%d" width="1" height="1" fill="%s"/>' % (x, y, c))
    w, h = len(rows[0]), len(rows)
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" shape-rendering="crispEdges">%s</svg>' % (w, h, "".join(rects))
    return render.Image(src = svg, width = w, height = h)

def arrow(pct):
    c = direction_color(pct)
    if c == UP:
        rows = ["..#..", ".###.", "#####"]
    elif c == DOWN:
        rows = ["#####", ".###.", "..#.."]
    else:
        rows = [".....", "#####", "....."]
    return pixel_svg(rows, {"#": c})

def logo(symbol):
    spec = LOGOS.get(symbol)
    if spec:
        colors = dict(spec["colors"])
        if "#" not in colors:
            colors["#"] = WHITE
        return pixel_svg(spec["rows"], colors)

    # Unknown ticker: initial letter on a coloured tile
    bg = FALLBACK_COLORS[len(symbol) % len(FALLBACK_COLORS)]
    return render.Box(width = 16, height = 16, color = bg, child = render.Text(symbol[:1], font = "6x13", color = WHITE))

# ---------------------------------------------------------------------------
# Data: live fetch or snapshot (same shape as MarketPulse)
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

def sparkline(q, width, height, upto):
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

    # dotted line at yesterday's close
    y = int(math.round((hi - q["prev"]) / (hi - lo) * (height - 1)))
    dots = render.Row(children = [
        render.Box(width = 1, height = 1, color = BASELINE if x % 3 == 0 else "#00000000")
        for x in range(width)
    ])
    return render.Stack(children = [render.Padding(pad = (0, y, 0, 0), child = dots), plot])

def card(q, status, stale, clock):
    color = direction_color(q["pct"])
    icon = logo(q["symbol"])
    frames = []
    for f in range(CARD_FRAMES):
        upto = min(1.0, (f + 1) / DRAW_FRAMES)
        blink_on = (f // 5) % 2 == 0

        # top-right corner: status for the first half, clock for the second (STALE always wins)
        if stale or f < CARD_FRAMES // 2:
            corner = status_chip(status, stale, blink_on)
        else:
            corner = render.Text(clock, font = SMALL, color = LABEL)

        frames.append(render.Column(children = [
            render.Row(children = [
                render.Padding(pad = (0, 1, 0, 0), child = icon),
                render.Box(width = 2, height = 1),
                render.Column(children = [
                    render.Row(expanded = True, main_align = "space_between", children = [
                        render.Text(q["symbol"], font = SMALL, color = WHITE),
                        corner,
                    ]),
                    render.Text(fmt_price(q["price"]), font = "6x13", color = WHITE),
                ]),
            ]),
            render.Row(cross_align = "end", children = [
                render.Box(width = 26, height = 12, child = render.Column(
                    expanded = True,
                    main_align = "end",
                    children = [
                        render.Row(cross_align = "center", children = [
                            arrow(q["pct"]),
                            render.Box(width = 1, height = 1),
                            render.Text(fmt_pct(q["pct"]), font = SMALL, color = color),
                        ]),
                        render.Text(fmt_change(q["change"]), font = SMALL, color = color),
                    ],
                )),
                render.Box(width = 3, height = 1),
                sparkline(q, 35, 12, upto),
            ]),
        ]))
    return render.Animation(children = frames)

def message(text):
    return render.Root(child = render.Box(child = render.WrappedText(text, font = SMALL, color = AMBER, align = "center", width = 62)))

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def watchlist(config):
    symbols = []
    for i, default in enumerate(DEFAULT_WATCHLIST):
        s = config.str("stock%d" % (i + 1), default).strip().upper()
        if s and s not in symbols:
            symbols.append(s)
    return symbols or DEFAULT_WATCHLIST

def main(config):
    symbols = watchlist(config)
    data = load_data(config, symbols)
    quotes = (data or {}).get("quotes", {})
    shown = [s for s in symbols if s in quotes and quotes[s].get("price") and quotes[s].get("prev")]
    if not shown:
        return message("MarketPulse Stocks: no market data")

    now = time.now().unix
    status = market_status(quotes[shown[0]], now)
    stale = status != "CLOSED" and now - int(data["fetched_at"]) > STALE_AFTER

    if config.str("demo_status"):
        status = config.str("demo_status").upper()
        stale = False
    if config.bool("demo_stale"):
        stale = True

    # Choose this push's page of 3 cards
    pages = (len(shown) + PER_PAGE - 1) // PER_PAGE
    page = int(config.str("page", str(now // PAGE_SECONDS))) % pages
    shown = shown[page * PER_PAGE:(page + 1) * PER_PAGE]

    last = max([int(quotes[s]["time"]) for s in shown])
    clock = time.from_timestamp(last if status == "CLOSED" else now).in_location(NY).format("3:04")

    return render.Root(
        delay = DELAY_MS,
        show_full_animation = True,
        child = render.Sequence(children = [
            card(enrich(s, quotes[s]), status, stale, clock)
            for s in shown
        ]),
    )

def get_schema():
    return schema.Schema(
        version = "1",
        fields = [
            schema.Text(
                id = "stock%d" % (i + 1),
                name = "Stock %d" % (i + 1),
                desc = "Ticker symbol (logo shown for AAPL, MSFT, NVDA, AMZN, GOOGL, HPQ; others get a letter tile).",
                icon = "chartLine",
                default = s,
            )
            for i, s in enumerate(DEFAULT_WATCHLIST)
        ],
    )
