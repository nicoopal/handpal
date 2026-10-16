"""Turns text into pen strokes in screen pixels."""

from __future__ import annotations

from dataclasses import dataclass

from .fonts import Point, Stroke, StrokeFont

MIN_LETTER_HEIGHT = 6.0


@dataclass
class LayoutOptions:
    letter_height: float = 28.0   # capital-letter height in pixels
    line_spacing: float = 1.7     # line height as a multiple of the letter height
    letter_spacing: float = 0.0   # extra space between letters, fraction of letter height
    size_mode: str = "shrink"     # "fixed" | "shrink" (only if it doesn't fit) | "fill"


@dataclass
class Layout:
    words: list[list[Stroke]]     # strokes grouped by word, in writing order
    width: float
    height: float
    letter_height: float
    overflow: bool                # text does not fit in the box


def _word_width(font: StrokeFont, word: str, scale: float, spacing: float) -> float:
    w = 0.0
    for ch in word:
        g = font.glyph(ch)
        w += (g.advance if g else font.default_advance) * scale + spacing
    return w


def _wrap(font: StrokeFont, text: str, scale: float, spacing: float,
          max_width: float | None) -> list[list[str]]:
    space = _word_width(font, " ", scale, spacing)
    lines: list[list[str]] = []
    for para in text.split("\n"):
        line: list[str] = []
        line_w = 0.0
        for word in para.split():
            ww = _word_width(font, word, scale, spacing)
            if max_width is not None and ww > max_width:
                # A word longer than the box: break it into pieces that fit.
                pieces, cur = [], ""
                for ch in word:
                    if cur and _word_width(font, cur + ch, scale, spacing) > max_width:
                        pieces.append(cur)
                        cur = ""
                    cur += ch
                pieces.append(cur)
            else:
                pieces = [word]
            for piece in pieces:
                pw = _word_width(font, piece, scale, spacing)
                needed = pw if not line else line_w + space + pw
                if line and max_width is not None and needed > max_width:
                    lines.append(line)
                    line, line_w = [piece], pw
                else:
                    line.append(piece)
                    line_w = needed
        lines.append(line)
    return lines


def _measure(font: StrokeFont, text: str, letter_height: float, opts: LayoutOptions,
             max_width: float | None):
    scale = letter_height / font.cap_height
    spacing = opts.letter_spacing * letter_height
    lines = _wrap(font, text, scale, spacing, max_width)
    space = _word_width(font, " ", scale, spacing)
    width = max((sum(_word_width(font, w, scale, spacing) for w in ln) + space * max(0, len(ln) - 1)
                 for ln in lines), default=0.0)
    line_h = letter_height * opts.line_spacing
    height = letter_height + line_h * (len(lines) - 1) + font.descent * scale
    return lines, width, height


def layout_text(font: StrokeFont, text: str, opts: LayoutOptions, origin: Point,
                box_size: tuple[float, float] | None = None) -> Layout:
    """Lay out text with its top-left corner at origin.

    With box_size, lines wrap at the box width and size_mode decides whether the
    letter height is adapted to the box height.
    """
    max_w = box_size[0] if box_size else None
    lh = max(MIN_LETTER_HEIGHT, opts.letter_height)
    lines, width, height = _measure(font, text, lh, opts, max_w)

    if box_size and opts.size_mode != "fixed":
        box_h = box_size[1]
        fits = lambda h: _measure(font, text, h, opts, max_w)[2] <= box_h  # noqa: E731
        if opts.size_mode == "fill" or not fits(lh):
            lo, hi = MIN_LETTER_HEIGHT, max(lh, box_h) if opts.size_mode == "fill" else lh
            if fits(hi):
                lo = hi
            for _ in range(24):
                if hi - lo < 0.25:
                    break
                mid = (lo + hi) / 2
                if fits(mid):
                    lo = mid
                else:
                    hi = mid
            lh = lo
            lines, width, height = _measure(font, text, lh, opts, max_w)

    overflow = bool(box_size) and (height > box_size[1] + 0.5 or width > box_size[0] + 0.5)
    scale = lh / font.cap_height
    spacing = opts.letter_spacing * lh
    space = _word_width(font, " ", scale, spacing)
    line_h = lh * opts.line_spacing
    ox, oy = origin

    words: list[list[Stroke]] = []
    baseline = oy + lh
    for line in lines:
        x = ox
        for word in line:
            strokes: list[Stroke] = []
            for ch in word:
                g = font.glyph(ch)
                if g is None:
                    x += font.default_advance * scale + spacing
                    continue
                for s in g.strokes:
                    pts = _simplify([(x + px * scale, baseline - py * scale) for px, py in s])
                    if pts:
                        strokes.append(pts)
                x += g.advance * scale + spacing
            if strokes:
                words.append(strokes)
            x += space
        baseline += line_h
    return Layout(words, width, height, lh, overflow)


def _simplify(pts: Stroke, min_dist: float = 0.8) -> Stroke:
    """Drop points that are closer than min_dist pixels to the previous kept one."""
    if not pts:
        return pts
    out = [pts[0]]
    for p in pts[1:-1]:
        if abs(p[0] - out[-1][0]) + abs(p[1] - out[-1][1]) >= min_dist:
            out.append(p)
    if len(pts) > 1:
        out.append(pts[-1])
    # A stroke that collapsed to a single spot (a dot) is kept as a tiny tap.
    return out


def pen_paths(layout: Layout, continuous: bool) -> list[Stroke]:
    """Paths drawn with the button held down.

    Stroke mode lifts the pen between strokes (print). Continuous mode keeps it
    down for a whole word, so strokes get joined (meant for cursive fonts).
    """
    if not continuous:
        return [s for word in layout.words for s in word]
    return [[p for s in word for p in s] for word in layout.words]
