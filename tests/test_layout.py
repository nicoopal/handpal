from handpal.fonts import get_font
from handpal.layout import LayoutOptions, layout_text, pen_paths

FONT = get_font("EMS Readability")


def bounds(layout):
    pts = [p for word in layout.words for s in word for p in s]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def test_text_starts_at_origin_and_caps_have_requested_height():
    lay = layout_text(FONT, "H", LayoutOptions(letter_height=40), (100, 200))
    x0, y0, x1, y1 = bounds(lay)
    assert 100 <= x0 < 110
    assert abs(y0 - 200) < 1.5          # top of the H at the origin
    assert abs((y1 - y0) - 40) < 1.5    # H is exactly one capital height tall


def test_text_wraps_inside_the_box():
    text = "one two three four five six seven eight nine ten"
    lay = layout_text(FONT, text, LayoutOptions(letter_height=20, size_mode="fixed"), (0, 0), (150, 1000))
    x0, _, x1, _ = bounds(lay)
    assert x1 <= 150
    one_line = layout_text(FONT, text, LayoutOptions(letter_height=20), (0, 0))
    assert bounds(lay)[3] > bounds(one_line)[3]  # took more than one line


def test_shrink_mode_fits_the_box():
    opts = LayoutOptions(letter_height=60, size_mode="shrink")
    lay = layout_text(FONT, "This text is too large for the box", opts, (0, 0), (200, 60))
    assert lay.letter_height < 60
    assert not lay.overflow
    _, _, x1, y1 = bounds(lay)
    assert x1 <= 200 and y1 <= 60


def test_shrink_mode_keeps_size_when_it_fits():
    lay = layout_text(FONT, "Hi", LayoutOptions(letter_height=20), (0, 0), (500, 500))
    assert lay.letter_height == 20


def test_fill_mode_grows_text():
    lay = layout_text(FONT, "Hi", LayoutOptions(letter_height=20, size_mode="fill"), (0, 0), (500, 500))
    assert lay.letter_height > 100


def test_fixed_mode_reports_overflow():
    lay = layout_text(FONT, "Too big", LayoutOptions(letter_height=80, size_mode="fixed"), (0, 0), (50, 50))
    assert lay.overflow


def test_explicit_newlines_make_lines():
    lay = layout_text(FONT, "A\nB", LayoutOptions(letter_height=20, line_spacing=2), (0, 0))
    a, b = lay.words
    gap = min(p[1] for s in b for p in s) - min(p[1] for s in a for p in s)
    assert abs(gap - 40) < 1.5  # line height = 2 x letter height


def test_continuous_mode_draws_one_path_per_word():
    lay = layout_text(FONT, "Hi there", LayoutOptions(), (0, 0))
    assert len(pen_paths(lay, continuous=True)) == 2
    assert len(pen_paths(lay, continuous=False)) > 2
