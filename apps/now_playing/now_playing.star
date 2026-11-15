"""
Applet: Now Playing
Summary: Movies in theaters now
Description: Movies now playing in US theaters for Tidbyt Gen 1: poster, title, rating and
runtime, and the IMDb rating. Two movies per showing, 7.5 s each: a panning full-screen still
from the film with its title, then the poster card. Every refresh moves on to the
next two. Data: TMDB (this product uses the TMDB API but is not endorsed or certified by TMDB)
and IMDb's public ratings dataset, prepared by tools/movies_snapshot.py and passed in as the
`snapshot` config value.
Preview: tools/make_preview.py builds apps/now_playing/preview/ with sample data embedded.
"""

load("encoding/base64.star", "base64")
load("encoding/json.star", "json")
load("math.star", "math")
load("render.star", "render")
load("schema.star", "schema")
load("time.star", "time")

DELAY_MS = 100
CARD_FRAMES = 75  # 2 cards x 7.5 s = 15.0 s (the Gen 1 limit)
PER_PAGE = 2
SCENE_FRAMES = 30  # 3 s film still, then 4.5 s poster card
ROTATE_EVERY_SECONDS = 60 * 60

POSTER_W = 21
TEXT_X = POSTER_W + 2
TEXT_W = 64 - TEXT_X

SMALL = "tom-thumb"
WHITE = "#f0f0f0"
GREY = "#8a94a0"
IMDB_YELLOW = "#f5c518"
BLACK = "#000000"
NEW_RED = "#ff4a4a"

def two_digit(n):
    return str(100 + n)[1:]

def fmt_runtime(minutes):
    if not minutes:
        return ""
    return "%dh%s" % (minutes // 60, two_digit(minutes % 60))

def fmt_rating(r):
    tenths = int(math.round(r * 10))
    return "%d.%d" % (tenths // 10, tenths % 10)

def ease_out(p):
    return 1 - (1 - p) * (1 - p)

def wrap_title(title, max_chars, max_lines):
    # Greedy word wrap; words too long for a line are hyphenated, and an over-long
    # title ends in ".." on the last line.
    words = []
    for word in title.upper().split(" "):
        for _ in range(10):  # no while loops in Starlark
            if len(word) <= max_chars:
                break
            words.append(word[:max_chars - 1] + "-")
            word = word[max_chars - 1:]
        if word:
            words.append(word)

    lines, current = [], ""
    for word in words:
        joined = word if not current else current + ("" if current.endswith("-") else " ") + word
        if len(joined) <= max_chars:
            current = joined
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1].rstrip("-")
        lines[-1] = (last if len(last) <= max_chars - 2 else last[:max_chars - 2]) + ".."
    return lines

def imdb_badge():
    return render.Box(
        width = 17,
        height = 7,
        color = IMDB_YELLOW,
        child = render.Text("IMDb", font = SMALL, color = BLACK),
    )

def rating_row(movie, f):
    if movie.get("imdb") == None:
        return render.Row(cross_align = "center", children = [
            imdb_badge(),
            render.Box(width = 2, height = 1),
            render.Text("new", font = SMALL, color = GREY),
        ])

    # the score counts up during the first second
    p = min(1.0, (f + 1) / 10.0)
    shown = movie["imdb"] * ease_out(p)
    return render.Row(cross_align = "center", children = [
        imdb_badge(),
        render.Box(width = 2, height = 1),
        render.Text(fmt_rating(shown), font = "5x8", color = WHITE),
    ])

def meta_line(movie):
    parts = []
    if movie.get("cert"):
        parts.append(movie["cert"])
    if movie.get("runtime"):
        parts.append(fmt_runtime(movie["runtime"]))
    return render.Text(" ".join(parts), font = SMALL, color = GREY)

def is_new(movie, now):
    # released in the last 7 days
    release = movie.get("release", "")
    if len(release) != 10:
        return False
    age = now.unix - time.parse_time(release + "T12:00:00Z").unix
    return age >= 0 and age < 7 * 86400

def new_tag():
    return render.Box(width = 13, height = 7, color = NEW_RED, child = render.Text("NEW", font = SMALL, color = WHITE))

def scene_frames(movie):
    # Full-screen still from the film, panning slowly, with the title along the bottom
    still = render.Image(src = base64.decode(movie["backdrop"]), width = 80, height = 40)
    title = movie["title"].upper()
    text_w = 4 * len(title)
    overflow = max(0, text_w - 62)
    frames = []
    for f in range(SCENE_FRAMES):
        p = f / (SCENE_FRAMES - 1)
        x = -int(math.round(16 * p))
        y = -2 - int(math.round(4 * p))

        # long titles scroll once, after a short pause
        shift = int(math.round(overflow * min(1.0, max(0.0, (f - 6) / (SCENE_FRAMES - 12)))))
        frames.append(render.Stack(children = [
            render.Padding(pad = (x, y, 0, 0), child = still),
            render.Padding(pad = (0, 25, 0, 0), child = render.Box(width = 64, height = 7, color = "#000000b4")),
            render.Padding(pad = (1 - shift, 26, 0, 0), child = render.Text(title, font = SMALL, color = WHITE)),
        ]))
    return frames

def info_frames(movie, now, count):
    poster = render.Image(src = base64.decode(movie["poster"]), width = POSTER_W, height = 32)
    lines = wrap_title(movie["title"], TEXT_W // 4, 3)  # tom-thumb is 4 px per character

    # left-aligned lines, padded to a fixed 18 px so the details below never move
    title = render.Column(cross_align = "start", children = [
        render.Text(line, font = SMALL, color = WHITE)
        for line in lines
    ] + [render.Box(width = 1, height = 18 - 6 * len(lines))])
    meta = meta_line(movie)
    fresh = is_new(movie, now)

    frames = []
    for f in range(count):
        # poster slides in from the left over the first 0.6 s
        slide = min(1.0, (f + 1) / 6.0)
        x = int(math.round(-POSTER_W * (1 - ease_out(slide))))
        frames.append(render.Stack(children = [
            render.Padding(pad = (x, 0, 0, 0), child = poster),
            render.Padding(pad = (x + 4, 25, 0, 0), child = new_tag()) if fresh and f % 10 < 7 else render.Box(width = 1, height = 1),
            render.Padding(pad = (TEXT_X, 0, 0, 0), child = render.Column(cross_align = "start", children = [
                title,
                render.Box(width = TEXT_W, height = 7, child = render.Row(expanded = True, children = [meta])),
                rating_row(movie, f),
            ])),
        ]))
    return frames

def card(movie, now):
    scene = scene_frames(movie) if movie.get("backdrop") else []
    return render.Animation(children = scene + info_frames(movie, now, CARD_FRAMES - len(scene)))

def message(text):
    return render.Root(child = render.Box(child = render.WrappedText(text, font = SMALL, color = IMDB_YELLOW, align = "center", width = 62)))

def main(config):
    raw = config.str("snapshot")
    if not raw:
        return message("Now Playing: no movie data yet")
    movies = json.decode(raw).get("movies", [])
    if not movies:
        return message("Now Playing: no movies found")

    now = time.now()
    pages = (len(movies) + PER_PAGE - 1) // PER_PAGE
    page = int(config.str("page", str(now.unix // ROTATE_EVERY_SECONDS))) % pages
    shown = movies[page * PER_PAGE:(page + 1) * PER_PAGE]

    return render.Root(
        delay = DELAY_MS,
        show_full_animation = True,
        child = render.Sequence(children = [card(m, now) for m in shown]),
    )

def get_schema():
    return schema.Schema(version = "1", fields = [])
