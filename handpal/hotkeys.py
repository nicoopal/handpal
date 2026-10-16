"""System-wide hotkeys via RegisterHotKey, on a thread with its own message loop."""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

from . import win32

_NAMED_KEYS = {
    "SPACE": 0x20, "PGUP": 0x21, "PGDOWN": 0x22, "END": 0x23, "HOME": 0x24,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28, "INS": 0x2D, "INSERT": 0x2D,
    "DEL": 0x2E, "DELETE": 0x2E, "PAUSE": 0x13, "BACKSPACE": 0x08, "TAB": 0x09,
    "RETURN": 0x0D, "ENTER": 0x0D,
}
_MODS = {"CTRL": win32.MOD_CONTROL, "ALT": win32.MOD_ALT, "SHIFT": win32.MOD_SHIFT,
         "META": win32.MOD_WIN, "WIN": win32.MOD_WIN}


def parse_hotkey(seq: str) -> tuple[int, int] | None:
    """'Ctrl+Shift+1' -> (modifiers, virtual key). None if it can't be used."""
    if not seq:
        return None
    parts = seq.split("+")
    # "Ctrl++" means the plus key.
    if seq.endswith("++"):
        parts = parts[:-2] + ["+"]
    mods = 0
    for p in parts[:-1]:
        m = _MODS.get(p.strip().upper())
        if m is None:
            return None
        mods |= m
    key = parts[-1].strip()
    up = key.upper()
    if up in _NAMED_KEYS:
        vk = _NAMED_KEYS[up]
    elif up.startswith("F") and up[1:].isdigit() and 1 <= int(up[1:]) <= 24:
        vk = 0x6F + int(up[1:])
    elif len(key) == 1:
        if key.isalnum() and key.isascii():
            vk = ord(up)
        else:
            scan = win32.user32.VkKeyScanW(key)
            if scan == -1:
                return None
            vk = scan & 0xFF
            # Qt records Ctrl+Shift+1 as "Ctrl+!": the shift state comes from the layout.
            shift_state = (scan >> 8) & 0xFF
            if shift_state & 1:
                mods |= win32.MOD_SHIFT
            if shift_state & 2:
                mods |= win32.MOD_CONTROL
            if shift_state & 4:
                mods |= win32.MOD_ALT
    else:
        return None
    return mods | win32.MOD_NOREPEAT, vk


class HotkeyManager(QObject):
    triggered = Signal(str)
    failed = Signal(str)   # hotkey text that Windows refused (already taken)

    def __init__(self):
        super().__init__()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()

    def set_hotkeys(self, mapping: dict[str, str]) -> None:
        """mapping: action id -> hotkey text. Replaces all current hotkeys."""
        self.stop()
        entries = []
        for action, seq in mapping.items():
            parsed = parse_hotkey(seq)
            if parsed:
                entries.append((action, seq, *parsed))
            elif seq:
                self.failed.emit(seq)
        self._ready.clear()
        self._thread = threading.Thread(target=self._loop, args=(entries,), daemon=True)
        self._thread.start()
        self._ready.wait(2)

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            win32.user32.PostThreadMessageW(self._thread_id, win32.WM_QUIT, 0, 0)
            self._thread.join(2)
        self._thread = None

    def _loop(self, entries) -> None:
        self._thread_id = win32.current_thread_id()
        ids: dict[int, str] = {}
        msg = wintypes.MSG()
        # Make sure the thread has a message queue before anyone posts to it.
        win32.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        for i, (action, seq, mods, vk) in enumerate(entries, start=1):
            if win32.user32.RegisterHotKey(None, i, mods, vk):
                ids[i] = action
            else:
                self.failed.emit(seq)
        self._ready.set()
        try:
            while win32.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == win32.WM_HOTKEY and msg.wParam in ids:
                    self.triggered.emit(ids[msg.wParam])
        finally:
            for i in ids:
                win32.user32.UnregisterHotKey(None, i)
