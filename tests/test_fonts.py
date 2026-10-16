import pytest

from handpal.fonts import available_fonts, get_font, parse_path


def test_all_bundled_fonts_load():
    fonts = available_fonts()
    assert len(fonts) >= 9
    for name in fonts:
        font = get_font(name)
        assert font.cap_height > 0
        assert font.glyph("A").strokes


@pytest.mark.parametrize("ch", list("áéíóúñÑü¿¡"))
def test_spanish_characters_are_covered(ch):
    assert get_font("EMS Readability").glyph(ch).strokes


@pytest.mark.parametrize("ch", list("✓✗→←↑↓•"))
def test_annotation_symbols_fall_back_to_builtins(ch):
    assert get_font("EMS Readability").glyph(ch).strokes


def test_unknown_character_has_no_glyph():
    assert get_font("EMS Readability").glyph("中") is None


def test_parse_path_splits_strokes_on_move():
    strokes = parse_path("M 0 0 L 10 0 M 0 5 L 10 5 L 10 10")
    assert strokes == [[(0, 0), (10, 0)], [(0, 5), (10, 5), (10, 10)]]


def test_parse_path_relative_and_close():
    strokes = parse_path("m 1 1 l 4 0 l 0 4 z")
    assert strokes == [[(1, 1), (5, 1), (5, 5), (1, 1)]]


def test_parse_path_flattens_curves():
    (stroke,) = parse_path("M 0 0 C 0 100 100 100 100 0")
    assert len(stroke) > 5
    assert stroke[-1] == pytest.approx((100, 0))
