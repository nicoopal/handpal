import pytest

from handpal import win32
from handpal.drawer import _MAX_CORNER_S, _corner_dwells
from handpal.hotkeys import parse_hotkey

CTRL, SHIFT, ALT, WIN, NOREP = (win32.MOD_CONTROL, win32.MOD_SHIFT, win32.MOD_ALT,
                                win32.MOD_WIN, win32.MOD_NOREPEAT)


@pytest.mark.parametrize("text, expected", [
    ("Ctrl+Shift+E", (CTRL | SHIFT | NOREP, ord("E"))),
    ("Ctrl+Shift+1", (CTRL | SHIFT | NOREP, ord("1"))),
    ("Alt+F9", (ALT | NOREP, 0x78)),
    ("Meta+Space", (WIN | NOREP, 0x20)),
])
def test_parse_hotkey(text, expected):
    assert parse_hotkey(text) == expected


@pytest.mark.parametrize("text", ["", "Ctrl+", "Hyper+A", "Ctrl+NotAKey"])
def test_parse_hotkey_rejects_invalid(text):
    assert parse_hotkey(text) is None


def test_straight_lines_need_no_pause():
    assert _corner_dwells([(0, 0), (5, 0), (10, 0), (20, 0)]) == [0, 0, 0, 0]


def test_sharp_corners_pause_for_a_frame():
    dwell = _corner_dwells([(0, 0), (10, 0), (0, 0)])  # a full reversal
    assert dwell[1] == pytest.approx(_MAX_CORNER_S)
    right_angle = _corner_dwells([(0, 0), (10, 0), (10, 10)])[1]
    assert 0 < right_angle <= _MAX_CORNER_S
