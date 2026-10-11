"""Generate the Questly app icons.

One geometric spec produces both the SVG (browser tab, scalable) and every
PNG the manifest and iOS need, so they can never drift apart.

    pip install pillow
    python tools/make_icons.py

Design: a grape-to-bubblegum squircle with a bold white star and two
twinkles. The star is deliberately chunky — it has to read at 32px.
"""

import math
import pathlib

from PIL import Image, ImageDraw, ImageFilter

OUT = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "icons"

S = 1024                     # design canvas
SUPERSAMPLE = 4              # render big, downscale for clean edges
CORNER = 0.225               # squircle radius as a fraction of the side

GRAPE = (124, 77, 255)
BUBBLEGUM = (255, 77, 148)
ORCHID = (176, 77, 220)      # midpoint, keeps the blend from going muddy

STAR_R = 268                 # outer radius
STAR_INNER = 0.42            # chunkier than the classic 0.382; reads better small
STAR_CY = 530                # nudged down: a 5-point star sits high optically

TWINKLES = [(768, 286, 68), (272, 716, 44)]   # x, y, radius


# --------------------------------------------------------------------------
# geometry (shared by both renderers)
# --------------------------------------------------------------------------

def star_points(cx, cy, outer, points=5, inner_ratio=STAR_INNER, rotation=-90):
    inner = outer * inner_ratio
    out = []
    for i in range(points * 2):
        r = outer if i % 2 == 0 else inner
        a = math.radians(rotation + i * 180 / points)
        out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def twinkle_points(cx, cy, outer):
    return star_points(cx, cy, outer, points=4, inner_ratio=0.30, rotation=-90)


# --------------------------------------------------------------------------
# PNG
# --------------------------------------------------------------------------

def gradient(size):
    """Smooth diagonal blend, made by scaling up a 2x2 image."""
    seed = Image.new("RGB", (2, 2))
    seed.putpixel((0, 0), GRAPE)
    seed.putpixel((1, 0), ORCHID)
    seed.putpixel((0, 1), ORCHID)
    seed.putpixel((1, 1), BUBBLEGUM)
    return seed.resize((size, size), Image.BICUBIC)


def render_png(size, maskable=False):
    big = size * SUPERSAMPLE
    scale = big / S

    img = gradient(big).convert("RGBA")

    if not maskable:
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, big - 1, big - 1], radius=int(CORNER * big), fill=255
        )
        img.putalpha(mask)

    # Maskable icons get cropped to a circle by the launcher, so shrink the
    # star into the safe zone and drop the twinkles.
    star_r = (STAR_R * 0.82 if maskable else STAR_R) * scale
    star_cy = (512 if maskable else STAR_CY) * scale
    pts = star_points(512 * scale, star_cy, star_r)

    shadow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon(
        [(x, y + 10 * scale) for x, y in pts], fill=(60, 20, 100, 90)
    )
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(9 * scale)))

    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.polygon(pts, fill=(255, 255, 255, 255))
    if not maskable:
        for tx, ty, tr in TWINKLES:
            d.polygon(
                twinkle_points(tx * scale, ty * scale, tr * scale),
                fill=(255, 255, 255, 165),
            )
    img.alpha_composite(layer)

    return img.resize((size, size), Image.LANCZOS)


# --------------------------------------------------------------------------
# SVG
# --------------------------------------------------------------------------

def path_from(pts):
    head = f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"
    rest = " ".join(f"L {x:.1f} {y:.1f}" for x, y in pts[1:])
    return f"{head} {rest} Z"


def render_svg():
    star = path_from(star_points(512, STAR_CY, STAR_R))
    twinkles = "\n    ".join(
        f'<path d="{path_from(twinkle_points(x, y, r))}" fill="#fff" opacity=".65"/>'
        for x, y, r in TWINKLES
    )
    hexes = tuple("#%02x%02x%02x" % c for c in (GRAPE, ORCHID, BUBBLEGUM))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" role="img" aria-label="Questly">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{hexes[0]}"/>
      <stop offset=".5" stop-color="{hexes[1]}"/>
      <stop offset="1" stop-color="{hexes[2]}"/>
    </linearGradient>
  </defs>
  <rect width="{S}" height="{S}" rx="{CORNER * S:.0f}" fill="url(#g)"/>
  <g>
    <path d="{star}" fill="#fff"/>
    {twinkles}
  </g>
</svg>
'''


# --------------------------------------------------------------------------

def main():
    OUT.mkdir(parents=True, exist_ok=True)

    (OUT / "icon.svg").write_text(render_svg())
    print("  icon.svg")

    for name, size, maskable in [
        ("favicon-32.png", 32, False),
        ("favicon-48.png", 48, False),
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("apple-touch-icon.png", 180, False),
        ("icon-maskable-192.png", 192, True),
        ("icon-maskable-512.png", 512, True),
    ]:
        render_png(size, maskable).save(OUT / name, optimize=True)
        print(f"  {name}")


if __name__ == "__main__":
    main()
