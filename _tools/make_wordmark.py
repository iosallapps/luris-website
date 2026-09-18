"""Outline the LURIS wordmark into SVG paths.

    python3 _tools/make_wordmark.py      -> _tools/fragments/wordmark.svg

The app draws the wordmark as SF Rounded Heavy, uppercase, tracked 0.12 em, in the
accent gradient (Luris/Core/DesignSystem/BrandWordmark.swift). Web browsers only have
SF Rounded on Apple devices (ui-rounded falls back to a square sans on Windows and
Android), so the site ships the letters as outlines. This script reads the system's
SF Rounded variable font at its Heavy instance and writes a <symbol id="wordmark">
that _tools/build_pages.py puts in every page's icon sprite. Run it on a Mac; the output is
committed, so nobody else needs the font.
"""
import os

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fragments", "wordmark.svg")
FONT = "/System/Library/Fonts/SFNSRounded.ttf"
TEXT = "LURIS"
HEAVY = {"wght": 858.4, "GRAD": 400}   # the font's own "Heavy" named instance
TRACKING_EM = 0.12


def main():
    font = instantiateVariableFont(TTFont(FONT), HEAVY)
    upm = font["head"].unitsPerEm
    cmap = font.getBestCmap()
    glyphs = font.getGlyphSet()
    tracking = TRACKING_EM * upm

    # draw each glyph flipped (font y goes up, SVG y goes down) at its pen position
    pens, x = [], 0.0
    for index, char in enumerate(TEXT):
        name = cmap[ord(char)]
        pens.append((name, x))
        x += glyphs[name].width + (tracking if index < len(TEXT) - 1 else 0)

    bounds = BoundsPen(glyphs)
    for name, gx in pens:
        glyphs[name].draw(TransformPen(bounds, (1, 0, 0, -1, gx, 0)))
    x0, y0, x1, y1 = bounds.bounds

    svg_pen = SVGPathPen(glyphs, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
    for name, gx in pens:
        glyphs[name].draw(TransformPen(svg_pen, (1, 0, 0, -1, gx - x0, -y0)))
    width, height = x1 - x0, y1 - y0
    symbol = (
        f'<symbol id="wordmark" viewBox="0 0 {width:.0f} {height:.0f}">'
        f'<path fill="url(#wordmark-gradient)" d="{svg_pen.getCommands()}"/></symbol>\n'
    )
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as handle:
        handle.write(symbol)
    print(f"{OUT}: viewBox {width:.0f}x{height:.0f}, {len(symbol)} bytes")


if __name__ == "__main__":
    main()
