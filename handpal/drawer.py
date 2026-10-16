"""Draws pen paths with the real mouse: press, drag, release."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

from . import win32
from .fonts import Stroke

# If the cursor ends up this far from where we put it, the user grabbed the mouse.
_TAKEOVER_PX = 15
_STEP_PX = 2.0

# Browsers (and so web whiteboards) only sample the mouse once per frame and join
# the samples with straight lines. Corners and curves therefore get time: at most
# _TURN_PER_FRAME degrees of direction change per frame, and a sharp corner holds
# the cursor still for about a frame so that it gets sampled exactly there.
_FRAME_S = 1 / 60
_TURN_PER_FRAME = 45.0
_MAX_CORNER_S = 1.5 * _FRAME_S


def _corner_dwells(path: Stroke) -> list[float]:
    """Seconds to wait at each point of the path."""
    dwell = [0.0] * len(path)
    for i in range(1, len(path) - 1):
        (x0, y0), (x1, y1), (x2, y2) = path[i - 1], path[i], path[i + 1]
        a1 = math.atan2(y1 - y0, x1 - x0)
        a2 = math.atan2(y2 - y1, x2 - x1)
        turn = abs(math.degrees((a2 - a1 + math.pi) % (2 * math.pi) - math.pi))
        dwell[i] = min(_MAX_CORNER_S, turn / _TURN_PER_FRAME * _FRAME_S)
    return dwell


@dataclass
class DrawSettings:
    speed: float = 600.0          # pixels per second while the button is down
    press_delay_ms: float = 6.0   # pause after moving to a stroke start / after pressing
    stroke_pause_ms: float = 8.0  # pause after releasing, before the next stroke


class Drawer(threading.Thread):
    """Runs in the background; on_finish gets "done", "aborted" or an error text."""

    def __init__(self, paths: list[Stroke], settings: DrawSettings,
                 on_finish: Callable[[str], None]):
        super().__init__(daemon=True)
        self.paths = paths
        self.settings = settings
        self.on_finish = on_finish
        self._cancel = threading.Event()
        self._expected: tuple[float, float] | None = None
        self._pressed = False

    def stop(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        result = "done"
        try:
            for path in self.paths:
                if not self._draw(path):
                    result = "aborted"
                    break
        except Exception as e:  # never leave the button pressed
            result = f"error: {e}"
        finally:
            if self._pressed:
                win32.left_up()
        self.on_finish(result)

    def _interrupted(self) -> bool:
        if self._cancel.is_set() or win32.key_down(win32.VK_ESCAPE):
            return True
        if self._expected is not None:
            x, y = win32.cursor_pos()
            if abs(x - self._expected[0]) > _TAKEOVER_PX or abs(y - self._expected[1]) > _TAKEOVER_PX:
                return True
        return False

    def _move(self, x: float, y: float) -> None:
        win32.move_to(x, y)
        self._expected = (x, y)

    def _wait(self, ms: float) -> bool:
        end = time.perf_counter() + ms / 1000
        while time.perf_counter() < end:
            if self._interrupted():
                return False
            time.sleep(min(0.005, max(0.0, end - time.perf_counter())))
        return not self._interrupted()

    def _draw(self, path: Stroke) -> bool:
        s = self.settings
        if len(path) == 1:  # a dot: make it a tiny drag so apps register it
            path = [path[0], (path[0][0] + 1, path[0][1])]
        self._move(*path[0])
        if not self._wait(s.press_delay_ms):
            return False
        win32.left_down()
        self._pressed = True
        if not self._wait(s.press_delay_ms):
            return False

        dwell = _corner_dwells(path)
        target = time.perf_counter()
        for k, (a, b) in enumerate(zip(path, path[1:])):
            seg = math.dist(a, b)
            steps = max(1, math.ceil(seg / _STEP_PX))
            for i in range(1, steps + 1):
                if self._interrupted():
                    return False
                t = i / steps
                self._move(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                target += seg / steps / s.speed
                if i == steps:
                    target += dwell[k + 1]
                delay = target - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)

        # Hold the last point for a frame so it gets sampled before the release.
        if not self._wait(_FRAME_S * 1000):
            return False
        win32.left_up()
        self._pressed = False
        return self._wait(s.stroke_pause_ms)
