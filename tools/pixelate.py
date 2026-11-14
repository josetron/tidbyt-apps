"""
pixelate.py - turn artwork images into 64x32 Tidbyt pixel art and embed them in an app.

Usage:
    pip install pillow            (once)
    python tools/pixelate.py apps/pixel_museum

Reads <app>/artworks.json, converts every artwork to <app>/art/<id>.png, writes a
magnified contact sheet <app>/art/_gallery.png, and regenerates the block between
the "BEGIN ARTWORKS" / "END ARTWORKS" markers in <app>/<app_name>.star.

Per-artwork options (artworks.json):
    mode   "photo"    - photographs / paintings: crop to 2:1, high-quality downscale,
                        then tune colour for the LED panel (default)
           "pixelart" - an image that is already pixel art on a ~64x32 grid: takes the
                        median colour of each grid cell, so edges stay crisp
           "fit"      - show the WHOLE image (no crop), letterboxed on `background`
    focus  [x, y]     - centre of the crop, as fractions of the image (default [0.5, 0.5])
    zoom   0..1       - fraction of the image width to keep (default 1.0)
    background "#rrggbb" for mode "fit" (default "#000000")
    boost  number     - extra brightness for dark images on Gen 1 LEDs (default 1.0)
    sharpen 0..200    - sharpening strength for mode "photo" (default 70, 0 = off)
"""

import base64
import json
import os
import re
import sys

# Optional: let a private Pillow install be used (handy for sandboxed runs).
if os.environ.get("PIXEL_MUSEUM_PYLIB"):
    sys.path.insert(0, os.environ["PIXEL_MUSEUM_PYLIB"])

from PIL import Image, ImageEnhance, ImageFilter  # noqa: E402

W, H = 64, 32


def crop_2to1(im, focus, zoom):
    """Crop a 2:1 window of `zoom` x image width, centred on `focus`, clamped inside the image."""
    iw, ih = im.size
    cw = iw * max(0.05, min(zoom, 1.0))
    ch = cw / 2.0
    if ch > ih:  # image is wider than 2:1 -> limit by height instead
        ch = ih
        cw = ch * 2.0
    cx, cy = focus[0] * iw, focus[1] * ih
    x0 = min(max(cx - cw / 2, 0), iw - cw)
    y0 = min(max(cy - ch / 2, 0), ih - ch)
    return im.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch)))


def led_tune(im, boost):
    """Gen 1 LEDs crush dark tones: lift shadows slightly, add a little punch."""
    im = ImageEnhance.Color(im).enhance(1.2)
    im = ImageEnhance.Contrast(im).enhance(1.1)
    gamma = 0.85 / boost
    lut = [min(255, round(255 * ((i / 255) ** gamma))) for i in range(256)]
    return im.point(lut * 3)


def convert_photo(im, art):
    im = crop_2to1(im, art.get("focus", [0.5, 0.5]), art.get("zoom", 1.0))
    # two-step downscale keeps detail without shimmering
    im = im.resize((W * 4, H * 4), Image.LANCZOS).resize((W, H), Image.BOX)
    # a light sharpen gives soft photos a crisper, more "pixel art" look
    im = im.filter(ImageFilter.UnsharpMask(radius=1, percent=art.get("sharpen", 70), threshold=2))
    return led_tune(im, art.get("boost", 1.0))


def convert_fit(im, art):
    bg = art.get("background", "#000000")
    iw, ih = im.size
    scale = min(W / iw, H / ih)
    nw, nh = max(1, round(iw * scale)), max(1, round(ih * scale))
    small = im.resize((nw * 4, nh * 4), Image.LANCZOS).resize((nw, nh), Image.BOX)
    canvas = Image.new("RGB", (W, H), bg)
    canvas.paste(small, ((W - nw) // 2, (H - nh) // 2))
    return led_tune(canvas, art.get("boost", 1.0))


def convert_pixelart(im, art):
    iw, ih = im.size
    cw, ch = iw / W, ih / H
    px = im.load()
    out = Image.new("RGB", (W, H))
    for y in range(H):
        for x in range(W):
            x0, x1 = int((x + 0.2) * cw), max(int((x + 0.8) * cw), int((x + 0.2) * cw) + 1)
            y0, y1 = int((y + 0.2) * ch), max(int((y + 0.8) * ch), int((y + 0.2) * ch) + 1)
            chans = ([], [], [])
            for yy in range(y0, y1):
                for xx in range(x0, x1):
                    for c, v in zip(chans, px[xx, yy]):
                        c.append(v)
            out.putpixel((x, y), tuple(sorted(c)[len(c) // 2] for c in chans))
    return out


def star_block(arts, app_dir):
    lines = ["ARTWORKS = ["]
    for art in arts:
        b64 = base64.b64encode(open(os.path.join(app_dir, "art", art["id"] + ".png"), "rb").read()).decode()
        chunks = [b64[i:i + 96] for i in range(0, len(b64), 96)]
        lines.append("    {")
        for k in ("id", "title", "artist", "year"):
            lines.append('        "%s": %s,' % (k, json.dumps(art.get(k, ""))))
        lines.append('        "png": base64.decode(')
        lines.append(" +\n".join('            "%s"' % c for c in chunks) + ",")
        lines.append("        ),")
        lines.append("    },")
    lines.append("]")
    return "\n".join(lines)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    app_dir = sys.argv[1].rstrip("/\\")
    app_name = os.path.basename(app_dir)
    cfg = json.load(open(os.path.join(app_dir, "artworks.json"), encoding="utf-8"))
    arts = cfg["artworks"]
    os.makedirs(os.path.join(app_dir, "art"), exist_ok=True)

    converters = {"photo": convert_photo, "pixelart": convert_pixelart, "fit": convert_fit}
    images = []
    for art in arts:
        im = Image.open(os.path.join(app_dir, art["source"])).convert("RGB")
        out = converters[art.get("mode", "photo")](im, art)
        out.save(os.path.join(app_dir, "art", art["id"] + ".png"), optimize=True)
        images.append(out)
        print("converted %-16s (%s)" % (art["id"], art.get("mode", "photo")))

    # contact sheet for quick review: 2 columns, magnified 6x
    m, cols = 6, 2
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (W * m + 8), rows * (H * m + 8)), (40, 40, 40))
    for i, img in enumerate(images):
        sheet.paste(img.resize((W * m, H * m), Image.NEAREST), ((i % cols) * (W * m + 8), (i // cols) * (H * m + 8)))
    sheet.save(os.path.join(app_dir, "art", "_gallery.png"))

    star_path = os.path.join(app_dir, app_name + ".star")
    src = open(star_path, encoding="utf-8").read()
    begin = "# --- BEGIN ARTWORKS (generated by tools/pixelate.py; do not edit by hand) ---"
    end = "# --- END ARTWORKS ---"
    pattern = re.compile(re.escape(begin) + ".*?" + re.escape(end), re.S)
    if not pattern.search(src):
        sys.exit("markers not found in " + star_path)
    src = pattern.sub(lambda _: begin + "\n" + star_block(arts, app_dir) + "\n" + end, src)
    open(star_path, "w", encoding="utf-8", newline="\n").write(src)
    print("updated %s with %d artworks" % (star_path, len(arts)))


if __name__ == "__main__":
    main()
