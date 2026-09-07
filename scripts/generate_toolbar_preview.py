# /// script
# dependencies = ["cairosvg>=2.8,<3"]
# ///
"""Render a review sheet from the exact SVG resources used by the toolbar."""

import xml.etree.ElementTree as ET
from pathlib import Path

import cairosvg

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "previews"
ICONS = (
    ("view-all", "View all", "Tutto il dato sperimentale"),
    ("view-active", "View active", "Solo punti non mascherati"),
    ("background-visual", "Visual only", "Anteprima senza sottrazione"),
    ("background-revert", "Revert background", "Ripristina il dato precedente"),
)


def main():
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    fragments = []
    for index, (name, title, subtitle) in enumerate(ICONS):
        resource = ET.parse(ROOT / "src" / "curvemole" / "resources" / f"{name}.svg").getroot()
        glyph = "".join(ET.tostring(child, encoding="unicode") for child in resource)
        x = 28 + index * 224
        fragments.append(f'''
        <rect x="{x}" y="92" width="212" height="245" rx="18" fill="#ffffff" stroke="#dbe3ec"/>
        <g transform="translate({x + 58} 120) scale(1.5)">{glyph}</g>
        <text x="{x + 106}" y="250" text-anchor="middle" font-size="18" font-weight="bold">{title}</text>
        <text x="{x + 106}" y="280" text-anchor="middle" font-size="12" fill="#536477">{subtitle}</text>
        <rect x="{x + 81}" y="371" width="50" height="50" rx="8" fill="#ffffff" stroke="#c9d5e2"/>
        <g transform="translate({x + 86} 376) scale(0.625)">{glyph}</g>''')
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="952" height="450" viewBox="0 0 952 450">
    <rect width="952" height="450" rx="20" fill="#f0f4f8"/>
    <g font-family="DejaVu Sans" fill="#172735">
    <text x="28" y="40" font-size="24" font-weight="bold">CurveMole · Nuovi pulsanti</text>
    <text x="28" y="66" font-size="14" fill="#536477">Icone reali · dettaglio ingrandito e formato barra da 40 px</text>
    ''' + "".join(fragments) + "</g></svg>"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source = OUTPUT / "toolbar-controls.svg"
    target = OUTPUT / "toolbar-controls.png"
    source.write_text(svg, encoding="utf-8")
    cairosvg.svg2png(url=str(source), write_to=str(target))
    print(target)


if __name__ == "__main__":
    main()
