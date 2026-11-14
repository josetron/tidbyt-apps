"""
Applet: Mona Lisa
Summary: Pixel-art Mona Lisa
Description: A 64x32 pixel-art Mona Lisa, converted from the mockup in this folder
(mockup.webp -> mona_lisa_64x32.png, median of each grid cell).
"""

load("encoding/base64.star", "base64")
load("render.star", "render")

# 64x32 PNG generated from mockup.webp. Regenerate it if the artwork changes.
MONA_LISA_PNG = base64.decode(
    "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" +
    "wIdarAAAAABJRU5ErkJggg==",
)

def main():
    return render.Root(
        child = render.Image(src = MONA_LISA_PNG, width = 64, height = 32),
    )
