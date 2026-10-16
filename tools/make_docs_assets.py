"""Regenerates the images used by the README and the app icon.

    python tools/make_docs_assets.py

Writes docs/demo.svg (animated handwriting), docs/fonts.png, docs/app.png and
assets/handpal.ico.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QTimer, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from handpal.config import Config  # noqa: E402
from handpal.fonts import available_fonts, get_font  # noqa: E402
from handpal.layout import LayoutOptions, layout_text, pen_paths  # noqa: E402
from handpal.ui import MainWindow, make_icon  # noqa: E402

INK = "#1f3fbf"
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"


def demo_svg(path: Path) -> None:
    """Animated SVG of Handpal writing, stroke by stroke, looping."""
    w, h, pad = 760, 230, 36
    font = get_font("EMS Readability")
    lay = layout_text(font, "Hello! Handpal writes\nfor you, like a hand would ✓",
                      LayoutOptions(letter_height=42, line_spacing=1.9), (pad, pad + 6))
    paths = pen_paths(lay, continuous=False)

    speed, pause = 900.0, 0.05     # px/s while drawing, seconds between strokes
    timeline, t = [], 0.6
    for p in paths:
        length = sum(math.dist(a, b) for a, b in zip(p, p[1:])) or 1.0
        timeline.append((t, t + length / speed, length))
        t += length / speed + pause
    total = t + 2.5                # hold the finished text before looping

    css, els = [], []
    for i, (p, (start, end, length)) in enumerate(zip(paths, timeline)):
        s, e = 100 * start / total, 100 * end / total
        # Hidden until its turn: round caps would otherwise show a dot at the start.
        css.append(f"@keyframes k{i}{{0%,{s:.3f}%{{stroke-dashoffset:{length:.1f};opacity:0}}"
                   f"{s + 0.01:.3f}%{{opacity:1}}"
                   f"{e:.3f}%,100%{{stroke-dashoffset:0;opacity:1}}}}"
                   f".p{i}{{stroke-dasharray:{length:.1f};stroke-dashoffset:{length:.1f};"
                   f"animation:k{i} {total:.2f}s linear infinite}}")
        d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in p)
        els.append(f'<path class="p{i}" d="{d}"/>')

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
<style>path{{fill:none;stroke:{INK};stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round}}{''.join(css)}</style>
<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="14" fill="#ffffff" stroke="#d8dce6" stroke-width="2"/>
{chr(10).join(els)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def fonts_png(path: Path) -> None:
    names = list(available_fonts())
    row_h, w = 64, 980
    img = QImage(w, row_h * len(names) + 24, QImage.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    label_pen = QPen(QColor("#6b7280"))
    ink = QPen(QColor(INK), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    y = 12
    for name in names:
        p.setPen(label_pen)
        p.drawText(20, y + 34, name)
        lay = layout_text(get_font(name), "Quick notes ✓ ¿Qué tal? → 2026",
                          LayoutOptions(letter_height=26), (230, y + 12))
        p.setPen(ink)
        for s in pen_paths(lay, False):
            qp = QPainterPath(QPointF(*s[0]))
            for pt in s[1:]:
                qp.lineTo(*pt)
            p.drawPath(qp)
        y += row_h
    p.end()
    img.save(str(path))


def app_png(app: QApplication, path: Path) -> None:
    window = MainWindow(Config())
    window.resize(640, 600)
    window.show()

    def grab():
        # A running Handpal holds the shortcuts; keep that warning out of the screenshot.
        window.statusBar().showMessage("Press Esc or move the mouse to stop writing at any time.")
        window.grab().save(str(path))
        window.quit()

    QTimer.singleShot(800, grab)
    app.exec()


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    ASSETS.mkdir(exist_ok=True)
    app = QApplication(sys.argv)
    make_icon().pixmap(256, 256).save(str(ASSETS / "handpal.ico"))
    make_icon().pixmap(128, 128).save(str(DOCS / "icon.png"))
    demo_svg(DOCS / "demo.svg")
    fonts_png(DOCS / "fonts.png")
    app_png(app, DOCS / "app.png")
    print("Wrote", ", ".join(str(p.relative_to(ROOT)) for p in
                             [DOCS / "demo.svg", DOCS / "fonts.png", DOCS / "app.png",
                              DOCS / "icon.png", ASSETS / "handpal.ico"]))


if __name__ == "__main__":
    main()
