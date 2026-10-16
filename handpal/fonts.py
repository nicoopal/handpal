"""Single-stroke SVG fonts (EMS / Hershey).

Each glyph is a list of strokes; each stroke is a list of (x, y) points in font
units with y pointing up and the baseline at y = 0.
"""

from __future__ import annotations

import html
import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

FONTS_DIR = Path(__file__).parent / "fonts"

Point = tuple[float, float]
Stroke = list[Point]

# Size in font units of a flattened curve segment (fonts are 1000 units/em).
_CURVE_STEP = 6.0


@dataclass
class Glyph:
    advance: float
    strokes: list[Stroke] = field(default_factory=list)


@dataclass
class StrokeFont:
    name: str
    path: Path
    glyphs: dict[str, Glyph]
    default_advance: float
    cap_height: float
    descent: float

    def glyph(self, ch: str) -> Glyph | None:
        g = self.glyphs.get(ch)
        if g is not None:
            return g
        # "ẽ" -> "e", etc.: fall back to the base letter.
        base = unicodedata.normalize("NFD", ch)[:1]
        if base and base != ch and base in self.glyphs:
            return self.glyphs[base]
        return _extra_glyph(ch, self.cap_height)


_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point) -> list[Point]:
    approx = math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)
    n = max(2, int(approx / _CURVE_STEP))
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((
            u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
        ))
    return out


def _quad(p0: Point, p1: Point, p2: Point) -> list[Point]:
    c1 = (p0[0] + 2 / 3 * (p1[0] - p0[0]), p0[1] + 2 / 3 * (p1[1] - p0[1]))
    c2 = (p2[0] + 2 / 3 * (p1[0] - p2[0]), p2[1] + 2 / 3 * (p1[1] - p2[1]))
    return _cubic(p0, c1, c2, p2)


def parse_path(d: str) -> list[Stroke]:
    """Flatten an SVG path into polylines. Every M starts a new stroke."""
    tokens = _TOKEN.findall(d)
    strokes: list[Stroke] = []
    cur: Stroke = []
    pos: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    last_ctrl: Point | None = None
    cmd = ""
    i = 0

    def num() -> float:
        nonlocal i
        v = float(tokens[i])
        i += 1
        return v

    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                if cur:
                    cur.append(start)
                pos = start
                last_ctrl = None
                continue
        rel = cmd.islower()
        ox, oy = pos if rel else (0.0, 0.0)
        c = cmd.upper()
        if c == "M":
            pos = (ox + num(), oy + num())
            if len(cur) > 1:
                strokes.append(cur)
            cur = [pos]
            start = pos
            cmd = "l" if rel else "L"  # extra pairs after M are line-tos
            last_ctrl = None
        elif c == "L":
            pos = (ox + num(), oy + num())
            cur.append(pos)
            last_ctrl = None
        elif c == "H":
            pos = ((ox if rel else 0.0) + num(), pos[1])
            cur.append(pos)
            last_ctrl = None
        elif c == "V":
            pos = (pos[0], (oy if rel else 0.0) + num())
            cur.append(pos)
            last_ctrl = None
        elif c == "C":
            p1 = (ox + num(), oy + num())
            p2 = (ox + num(), oy + num())
            p3 = (ox + num(), oy + num())
            cur.extend(_cubic(pos, p1, p2, p3))
            pos, last_ctrl = p3, p2
        elif c == "S":
            p1 = (2 * pos[0] - last_ctrl[0], 2 * pos[1] - last_ctrl[1]) if last_ctrl else pos
            p2 = (ox + num(), oy + num())
            p3 = (ox + num(), oy + num())
            cur.extend(_cubic(pos, p1, p2, p3))
            pos, last_ctrl = p3, p2
        elif c == "Q":
            p1 = (ox + num(), oy + num())
            p2 = (ox + num(), oy + num())
            cur.extend(_quad(pos, p1, p2))
            pos, last_ctrl = p2, p1
        elif c == "T":
            p1 = (2 * pos[0] - last_ctrl[0], 2 * pos[1] - last_ctrl[1]) if last_ctrl else pos
            p2 = (ox + num(), oy + num())
            cur.extend(_quad(pos, p1, p2))
            pos, last_ctrl = p2, p1
        else:
            i += 1  # unsupported command (e.g. arcs): skip its numbers
    if len(cur) > 1:
        strokes.append(cur)
    return strokes


def load_font(path: Path) -> StrokeFont:
    root = ET.parse(path).getroot()
    ns = {"svg": "http://www.w3.org/2000/svg"}
    font_el = root.find(".//svg:font", ns)
    face = root.find(".//svg:font-face", ns)
    default_adv = float(font_el.get("horiz-adv-x", "500"))
    name = face.get("font-family", path.stem) if face is not None else path.stem
    descent = abs(float(face.get("descent", "-200"))) if face is not None else 200.0

    glyphs: dict[str, Glyph] = {}
    for g in root.iterfind(".//svg:glyph", ns):
        uni = g.get("unicode")
        if uni is None:
            continue
        uni = html.unescape(uni)
        if len(uni) != 1:
            continue  # ligatures are not used
        adv = float(g.get("horiz-adv-x", default_adv))
        glyphs[uni] = Glyph(adv, parse_path(g.get("d", "")))

    # The cap-height in these files is a placeholder; measure "H" instead.
    cap = 700.0
    if "H" in glyphs and glyphs["H"].strokes:
        cap = max(y for s in glyphs["H"].strokes for _, y in s)
    return StrokeFont(name, path, glyphs, default_adv, cap, descent)


def available_fonts() -> dict[str, Path]:
    """Font family name -> file, sorted with the clearest print fonts first."""
    preferred = ["EMSReadability", "HersheySans1", "EMSTech", "EMSOsmotron",
                 "EMSNixish", "EMSFelix", "EMSElfin", "EMSAllure", "HersheyScript1"]
    files = sorted(FONTS_DIR.glob("*.svg"),
                   key=lambda p: (preferred.index(p.stem) if p.stem in preferred else 99, p.stem))
    out: dict[str, Path] = {}
    for p in files:
        m = re.search(r'font-family="([^"]+)"', p.read_text(encoding="utf-8", errors="ignore"))
        out[m.group(1) if m else p.stem] = p
    return out


_cache: dict[Path, StrokeFont] = {}


def get_font(name: str) -> StrokeFont:
    fonts = available_fonts()
    path = fonts.get(name) or next(iter(fonts.values()))
    if path not in _cache:
        _cache[path] = load_font(path)
    return _cache[path]


# Symbols handy for annotations that the fonts lack, drawn on a cap-height grid
# (x and y as fractions of cap height).
_EXTRA = {
    "✓": (0.95, [[(0.05, 0.45), (0.32, 0.12), (0.85, 0.95)]]),
    "✔": (0.95, [[(0.05, 0.45), (0.32, 0.12), (0.85, 0.95)]]),
    "✗": (0.85, [[(0.1, 0.9), (0.75, 0.05)], [(0.1, 0.05), (0.75, 0.9)]]),
    "✘": (0.85, [[(0.1, 0.9), (0.75, 0.05)], [(0.1, 0.05), (0.75, 0.9)]]),
    "→": (1.2, [[(0.1, 0.45), (1.05, 0.45)], [(0.75, 0.72), (1.05, 0.45), (0.75, 0.18)]]),
    "←": (1.2, [[(1.05, 0.45), (0.1, 0.45)], [(0.4, 0.72), (0.1, 0.45), (0.4, 0.18)]]),
    "↑": (0.8, [[(0.4, 0.0), (0.4, 0.95)], [(0.12, 0.65), (0.4, 0.95), (0.68, 0.65)]]),
    "↓": (0.8, [[(0.4, 0.95), (0.4, 0.0)], [(0.12, 0.3), (0.4, 0.0), (0.68, 0.3)]]),
    "•": (0.6, [[(0.22, 0.45), (0.38, 0.45), (0.38, 0.29), (0.22, 0.29), (0.22, 0.45)]]),
}


def _extra_glyph(ch: str, cap: float) -> Glyph | None:
    spec = _EXTRA.get(ch)
    if spec is None:
        return None
    adv, strokes = spec
    return Glyph(adv * cap, [[(x * cap, y * cap) for x, y in s] for s in strokes])
