"""
Applet: Astros News
Summary: Latest Houston Astros news
Description: One Houston Astros headline at a time, from MLB.com's official Astros news feed,
next to a pixel Astros star logo. Short headlines use a larger font; long ones scroll gently.
Each refresh shows the next recent headline. News only: no scores, no portraits.
Preview switch: ?item=<n> to show a specific headline.
"""

load("http.star", "http")
load("math.star", "math")
load("render.star", "render")
load("schema.star", "schema")
load("time.star", "time")
load("xpath.star", "xpath")

FEED_URL = "https://www.mlb.com/astros/feeds/news/rss.xml"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
CACHE_TTL = 900
MAX_AGE_DAYS = 21
ROTATE_EVERY_SECONDS = 15 * 60
SKIP_WORDS = ["TRIVIA", "PUZZLE", "QUIZ", "TICKETS", "GIVEAWAY", "SWEEPSTAKES"]

DELAY_MS = 100
FRAMES = 150  # 15.0 s

PAD_X = 2
LINE_CHARS = 12  # 5x8 font: 5 px per character
PAGE_LINES = 2

ORANGE = "#ff7a1a"
ORANGE_LIGHT = "#ffa060"
NAVY = "#14306e"  # brighter than the real navy so it shows on Gen 1 LEDs
WHITE = "#f4f4f4"
GREY = "#b8c0cc"

# Words that get the orange highlight (the first one found in a headline)
ACTION_WORDS = [
    "WINS",
    "WIN",
    "TAKES",
    "SIGNS",
    "SIGN",
    "HIRES",
    "HIRE",
    "HIRING",
    "NAMED",
    "NAMES",
    "INTRODUCE",
    "INTRODUCES",
    "ADDS",
    "ACQUIRE",
    "ACQUIRES",
    "TRADE",
    "TRADES",
    "AGREE",
    "AGREES",
    "CLAIM",
    "CLAIMS",
    "PROMOTE",
    "PROMOTES",
    "RETURNS",
    "RE-SIGN",
    "EXTENSION",
    "MVP",
    "CY",
    "HOMER",
    "WALK-OFF",
    "CLINCH",
    "CLINCHES",
    "BEAT",
    "BEATS",
    "SWEEP",
    "SWEEPS",
]

# ---------------------------------------------------------------------------
# Logo: 13x13 pixel art of the Astros star-and-H in a white ring
# (".", navy; "w", white ring; "o", orange star; "h", white H)
# ---------------------------------------------------------------------------

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

def logo():
    # Built from box runs: an SVG's transparent parts render black in Pixlet
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

# ---------------------------------------------------------------------------
# Feed
# ---------------------------------------------------------------------------

def clean(text):
    for a, b in (
        ("&#8217;", "'"),
        ("&#8216;", "'"),
        ("&#8220;", '"'),
        ("&#8221;", '"'),
        ("&#8212;", "-"),
        ("&#8211;", "-"),
        ("&amp;", "&"),
        ("&quot;", '"'),
        ("&#39;", "'"),
        ("’", "'"),
        ("‘", "'"),
        ("“", '"'),
        ("”", '"'),
        ("—", "-"),
        ("–", "-"),
        ("é", "E"),
        ("É", "E"),
        ("á", "A"),
        ("í", "I"),
        ("ó", "O"),
        ("ú", "U"),
        ("ñ", "N"),
        ("Á", "A"),
    ):
        text = text.replace(a, b)
    return " ".join(text.strip().split())

def headlines(now):
    rep = http.get(FEED_URL, headers = HEADERS, ttl_seconds = CACHE_TTL)
    if rep.status_code != 200:
        return []
    doc = xpath.loads(rep.body())
    titles = doc.query_all("//item/title")
    dates = doc.query_all("//item/pubDate")
    items = []
    for i, title in enumerate(titles):
        title = clean(title).upper()
        if not title or any([w in title for w in SKIP_WORDS]):
            continue
        when = None
        if i < len(dates):
            when = time.parse_time(dates[i].strip(), format = "Mon, 02 Jan 2006 15:04:05 MST")
        if when and now.unix - when.unix > MAX_AGE_DAYS * 86400:
            continue
        items.append({"title": title, "when": when})
    return items

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def wrap(text, max_chars):
    lines, current = [], ""
    for word in text.split(" "):
        for _ in range(5):  # hard-break words longer than a line
            if len(word) <= max_chars:
                break
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:max_chars - 1] + "-")
            word = word[max_chars - 1:]
        joined = word if not current else current + " " + word
        if len(joined) <= max_chars:
            current = joined
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

def highlight_word(title):
    words = [w.strip(".,:;!?'\"") for w in title.split(" ")]
    for w in words:
        if w in ACTION_WORDS:
            return w
    return ""

def line_widget(line, hot):
    words = line.split(" ")
    children = []
    for i, w in enumerate(words):
        bare = w.strip(".,:;!?'\"")
        color = ORANGE if hot and bare == hot else WHITE
        children.append(render.Text(w + (" " if i < len(words) - 1 else ""), font = "5x8", color = color))
    return render.Row(children = children)

def age_label(when, now):
    if not when:
        return ""
    hours = (now.unix - when.unix) // 3600
    if hours < 1:
        return "NOW"
    if hours < 24:
        return "%dH" % hours
    return "%dD" % (hours // 24)

def header(when, now):
    return render.Stack(children = [
        render.Padding(pad = (1, 0, 0, 0), child = logo()),
        render.Padding(pad = (16, 2, 0, 0), child = render.Text("ASTROS", font = "tb-8", color = WHITE)),
        render.Padding(pad = (16, 11, 0, 0), child = render.Box(width = 47, height = 1, color = ORANGE)),
        render.Padding(pad = (0, 3, 1, 0), child = render.Row(expanded = True, main_align = "end", children = [
            render.Text(age_label(when, now), font = "tom-thumb", color = ORANGE_LIGHT),
        ])),
    ])

def headline_frames(title, when, now):
    lines = wrap(title, LINE_CHARS)
    pages = [lines[i:i + PAGE_LINES] for i in range(0, len(lines), PAGE_LINES)][:5]
    hot = highlight_word(title)
    page_widgets = [
        render.Column(children = [line_widget(line, hot) for line in page] + [render.Box(width = 1, height = 1)])
        for page in pages
    ]
    per_page = FRAMES // len(pages)
    top = header(when, now)

    frames = []
    for f in range(FRAMES):
        i = min(len(pages) - 1, f // per_page)
        local = f - i * per_page

        # each page slides up into place over 0.4 s (the first one slides in from the right)
        p = min(1.0, (local + 1) / 4.0)
        ease = (1 - p) * (1 - p)
        dx = int(math.round(64 * ease)) if i == 0 else 0
        dy = int(math.round(18 * ease)) if i > 0 else 0

        frames.append(render.Stack(children = [
            render.Box(width = 64, height = 32, color = NAVY),
            render.Padding(pad = (PAD_X + dx, 14 + dy, 0, 0), child = page_widgets[i]),
            top,
        ]))
    return frames

def message(text):
    return render.Root(child = render.Stack(children = [
        render.Box(width = 64, height = 32, color = NAVY),
        header(None, time.now()),
        render.Padding(pad = (PAD_X, 15, 0, 0), child = render.WrappedText(text, font = "tom-thumb", color = GREY, width = 60)),
    ]))

def main(config):
    now = time.now()
    items = headlines(now)
    if not items:
        return message("NO ASTROS NEWS RIGHT NOW")

    index = int(config.str("item", str(now.unix // ROTATE_EVERY_SECONDS))) % len(items)
    item = items[index]
    title = item["title"]
    if title.startswith("ASTROS ") and len(title) > 20:  # the header already says ASTROS
        title = title[len("ASTROS "):]
    return render.Root(
        delay = DELAY_MS,
        show_full_animation = True,
        child = render.Animation(children = headline_frames(title, item["when"], now)),
    )

def get_schema():
    return schema.Schema(version = "1", fields = [])
