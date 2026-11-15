"""
Applet: Astros Stars
Summary: Houston Astros star players
Description: One Houston Astros star at a time for Tidbyt Gen 1: a pixel portrait, the player's
name, their biggest recent achievement in orange (AL MVP, 9X ALL-STAR...) and their season stats.
Each refresh moves on to the next star. Data: MLB Stats API and MLB headshots, prepared by
tools/stars_snapshot.py and passed in as the `snapshot` config value.
Preview: tools/make_preview.py builds apps/astros_stars/preview/ with sample data embedded.
"""

load("encoding/base64.star", "base64")
load("encoding/json.star", "json")
load("math.star", "math")
load("render.star", "render")
load("schema.star", "schema")
load("time.star", "time")

DELAY_MS = 100
FRAMES = 150  # 15.0 s (the Gen 1 limit)
FIRST_LINE_FRAMES = 45  # achievement detail, then each stat gets an equal share
ROTATE_EVERY_SECONDS = 60 * 60

PORTRAIT_W = 24
X = PORTRAIT_W + 1

ORANGE = "#ff7a1a"
ORANGE_LIGHT = "#ffa060"
NAVY = "#14306e"
WHITE = "#f4f4f4"
GREY = "#b8c0cc"

def ease_out(p):
    p = min(1.0, max(0.0, p))
    return 1 - (1 - p) * (1 - p)

def slide(f, start, length, distance):
    # pixels still to travel at frame f for a move that starts at `start`
    return int(math.round(distance * (1 - ease_out((f - start + 1) / length))))

def bottom_lines(player):
    lines = [render.Text(player["small"], font = "tom-thumb", color = GREY)]
    for value, label in player.get("stats", [])[:3]:
        lines.append(render.Row(children = [
            render.Text(value + " ", font = "tom-thumb", color = WHITE),
            render.Text(label, font = "tom-thumb", color = ORANGE_LIGHT),
        ]))
    return lines

def frames_for(player):
    portrait = render.Box(width = PORTRAIT_W, height = 32, color = NAVY)
    if player.get("portrait"):
        portrait = render.Image(src = base64.decode(player["portrait"]), width = PORTRAIT_W, height = 32)

    tag = "#%s %s" % (player.get("number", ""), player.get("pos", "")) if player.get("number") else player.get("pos", "")
    top = render.Text(tag, font = "tom-thumb", color = ORANGE_LIGHT)
    name = render.Text(player["name"], font = "5x8", color = WHITE)
    big = render.Text(player["big"], font = "5x8", color = ORANGE)
    lines = bottom_lines(player)
    per_stat = (FRAMES - FIRST_LINE_FRAMES) // max(1, len(lines) - 1)

    frames = []
    for f in range(FRAMES):
        # which bottom line, and how far into it
        if f < FIRST_LINE_FRAMES or len(lines) == 1:
            i, start = 0, 0
        else:
            i = min(len(lines) - 1, 1 + (f - FIRST_LINE_FRAMES) // per_stat)
            start = FIRST_LINE_FRAMES + (i - 1) * per_stat
        dy = slide(f, start, 4, 7) if i > 0 else 0  # each stat slides up from below

        rule = int(math.round(38 * ease_out((f - 3) / 10.0)))
        frames.append(render.Stack(children = [
            render.Box(width = 64, height = 32, color = NAVY),
            render.Padding(pad = (X + slide(f, 0, 6, 40), 1, 0, 0), child = top),
            render.Padding(pad = (X + slide(f, 2, 6, 40), 7, 0, 0), child = name),
            render.Padding(pad = (X, 15, 0, 0), child = render.Box(width = max(1, rule), height = 1, color = ORANGE)) if rule > 0 else render.Box(width = 1, height = 1, color = NAVY),
            render.Padding(pad = (X + slide(f, 6, 6, 40), 17, 0, 0), child = big),
            render.Padding(pad = (X + (slide(f, 10, 6, 40) if i == 0 else 0), 26 + dy, 0, 0), child = lines[i]),
            render.Padding(pad = (-slide(f, 0, 7, PORTRAIT_W), 0, 0, 0), child = portrait),
        ]))
    return frames

def message(text):
    return render.Root(child = render.Stack(children = [
        render.Box(width = 64, height = 32, color = NAVY),
        render.Box(child = render.WrappedText(text, font = "tom-thumb", color = ORANGE_LIGHT, align = "center", width = 62)),
    ]))

def main(config):
    raw = config.str("snapshot")
    if not raw:
        return message("ASTROS STARS: NO PLAYER DATA YET")
    players = json.decode(raw).get("players", [])
    if not players:
        return message("ASTROS STARS: NO PLAYERS FOUND")

    index = int(config.str("page", str(time.now().unix // ROTATE_EVERY_SECONDS))) % len(players)
    return render.Root(
        delay = DELAY_MS,
        show_full_animation = True,
        child = render.Animation(children = frames_for(players[index])),
    )

def get_schema():
    return schema.Schema(version = "1", fields = [])
