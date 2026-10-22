"""Build FastAlgo brand assets: SVG mark, glyph, wordmarks, PNG and ICO renders.

The wordmark is set in Manrope (SIL Open Font License 1.1) and converted to
outlines, so the app never loads the font. Download the variable font first:
https://raw.githubusercontent.com/google/fonts/main/ofl/manrope/Manrope%5Bwght%5D.ttf

Usage:
    uv run python scripts/brand/build_brand_assets.py <Manrope.ttf> frontend/src/brand/assets

Geometry and colours are specified in docs/design/brand/design-language.md
section 5. Change them there first, then here.
"""

import sys
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image, ImageDraw

INK = "#162537"  # ink-800, tile
INK_TEXT = "#0C121A"  # ink-950, wordmark on light
LIGHT_TEXT = "#F2F5F8"  # wordmark on dark
PULSE = "#3BCFCF"  # pulse-300, chevrons on the tile
PULSE_GLYPH = "#009D9E"  # pulse-500, glyph on unknown backgrounds

# Mark geometry on a 64-unit grid.
TILE_R = 14
STROKE = 6
OUTER = [(26, 16), (48, 16), (48, 38)]
INNER = [(16, 28), (36, 28), (36, 48)]
INNER_OPACITY = 0.5


def pts(p):
    return "M" + " L".join(f"{x} {y}" for x, y in p)


def chevrons_svg(color):
    common = f'fill="none" stroke="{color}" stroke-width="{STROKE}" stroke-linecap="round" stroke-linejoin="round"'
    return (
        f'<path d="{pts(INNER)}" {common} stroke-opacity="{INNER_OPACITY}"/>'
        f'<path d="{pts(OUTER)}" {common}/>'
    )


def mark_svg():
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="FastAlgo">'
        f'<rect width="64" height="64" rx="{TILE_R}" fill="{INK}"/>'
        f"{chevrons_svg(PULSE)}</svg>\n"
    )


def glyph_svg():
    # Chevrons only, cropped to their stroke bounds (13..51), for watermarks.
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="13 13 38 38" role="img" aria-label="FastAlgo">'
        f"{chevrons_svg(PULSE_GLYPH)}</svg>\n"
    )


def text_paths(font_path):
    """Return (svg_fragment, width, (ymin, ymax)) for 'fast' bold + 'algo' medium, in font units."""
    out = []
    x = 0.0
    ymin, ymax = 0.0, 0.0
    for text, weight in (("fast", 800), ("algo", 500)):
        f = TTFont(font_path)
        inst = instantiateVariableFont(f, {"wght": weight})
        gs = inst.getGlyphSet()
        cmap = inst.getBestCmap()
        hmtx = inst["hmtx"]
        upm = inst["head"].unitsPerEm
        tracking = -0.01 * upm
        for ch in text:
            name = cmap[ord(ch)]
            pen = SVGPathPen(gs)
            # Flip Y: font units are y-up, SVG is y-down.
            gs[name].draw(TransformPen(pen, (1, 0, 0, -1, x, 0)))
            bp = BoundsPen(gs)
            gs[name].draw(bp)
            if bp.bounds:
                ymin = min(ymin, bp.bounds[1])
                ymax = max(ymax, bp.bounds[3])
            out.append(pen.getCommands())
            x += hmtx[name][0] + tracking
    return " ".join(out), x, (ymin, ymax), upm


def wordmark_svg(font_path, text_color):
    d, width_units, (ymin, ymax), upm = text_paths(font_path)
    # Tile is 64 high. Ascender height of the text = 36 units, centred on the tile.
    scale = 36 / ymax
    gap = 16
    text_x = 64 + gap
    # Baseline so that the ascender block (0..ymax) is centred at y=32, descender hangs below.
    baseline = 32 + (ymax * scale) / 2
    total_w = text_x + width_units * scale + 4
    total_h = max(64, baseline + (-ymin) * scale + 2)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w:.1f} {total_h:.1f}" role="img" aria-label="FastAlgo">'
        f'<rect width="64" height="64" rx="{TILE_R}" fill="{INK}"/>'
        f"{chevrons_svg(PULSE)}"
        f'<g transform="translate({text_x} {baseline:.2f}) scale({scale:.5f})" fill="{text_color}"><path d="{d}"/></g>'
        "</svg>\n"
    )


def hex_rgba(h, a=255):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def render_mark(size, full_bleed=False, ss=8):
    """Raster the mark at `size` px. full_bleed: square ink plate, chevrons scaled to 80%."""
    big = size * ss
    u = big / 64
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if full_bleed:
        d.rectangle([0, 0, big, big], fill=hex_rgba(INK))
    else:
        d.rounded_rectangle([0, 0, big - 1, big - 1], radius=TILE_R * u, fill=hex_rgba(INK))

    def chev(points, alpha):
        layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        if full_bleed:
            # Shrink the 13..51 artwork toward the centre so iOS corner rounding never clips it.
            k = 0.86
            points = [(32 + (x - 32) * k, 32 + (y - 32) * k) for x, y in points]
        p = [(x * u, y * u) for x, y in points]
        w = STROKE * u * (0.86 if full_bleed else 1)
        col = hex_rgba(PULSE)
        ld.line(p, fill=col, width=round(w), joint="curve")
        r = w / 2
        for cx, cy in (p[0], p[-1]):
            ld.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
        if alpha < 255:
            a = layer.getchannel("A").point(lambda v: v * alpha // 255)
            layer.putalpha(a)
        return layer

    img = Image.alpha_composite(img, chev(INNER, round(255 * INNER_OPACITY)))
    img = Image.alpha_composite(img, chev(OUTER, 255))
    return img.resize((size, size), Image.LANCZOS)


def main():
    font_path, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    (out / "fastalgo-mark.svg").write_text(mark_svg(), encoding="utf-8")
    (out / "fastalgo-glyph.svg").write_text(glyph_svg(), encoding="utf-8")
    (out / "fastalgo-wordmark-light.svg").write_text(
        wordmark_svg(font_path, INK_TEXT), encoding="utf-8"
    )
    (out / "fastalgo-wordmark-dark.svg").write_text(
        wordmark_svg(font_path, LIGHT_TEXT), encoding="utf-8"
    )

    render_mark(512).save(out / "logo.png")
    render_mark(192).save(out / "android-chrome-192x192.png")
    render_mark(180, full_bleed=True).convert("RGB").save(out / "apple-touch-icon.png")
    icons = [render_mark(s, ss=16) for s in (48, 32, 16)]
    icons[0].save(
        out / "favicon.ico", sizes=[(48, 48), (32, 32), (16, 16)], append_images=icons[1:]
    )
    for f in sorted(out.iterdir()):
        print(f.name, f.stat().st_size)


if __name__ == "__main__":
    main()
