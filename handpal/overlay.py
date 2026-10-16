"""Full-screen overlay to drag the box where the text goes."""

from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import win32

_MIN_BOX = 8  # physical pixels; smaller drags are treated as a cancel


class _ScreenOverlay(QWidget):
    def __init__(self, owner: "SelectionOverlay", screen):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.owner = owner
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.CrossCursor)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.start: QPoint | None = None
        self.end: QPoint | None = None

    def paintEvent(self, _):
        p = QPainter(self)
        # Fully transparent pixels don't get mouse events on Windows, so keep a light tint.
        p.fillRect(self.rect(), QColor(20, 30, 60, 70))
        if self.start and self.end:
            r = QRect(self.start, self.end).normalized()
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(r, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.fillRect(r, QColor(255, 255, 255, 1))
            p.setPen(QPen(QColor("#2f6bff"), 2, Qt.DashLine))
            p.drawRect(r)
        elif self.owner.hint:
            p.setPen(QColor("white"))
            f = QFont(self.font())
            f.setPointSize(14)
            p.setFont(f)
            p.drawText(self.rect().adjusted(0, 0, 0, -self.height() // 2), Qt.AlignCenter,
                       self.owner.hint)

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.owner.cancel()
            return
        if e.button() == Qt.LeftButton:
            self.start = self.end = e.position().toPoint()
            self.owner.phys_start = win32.message_pos()
            self.update()

    def mouseMoveEvent(self, e):
        if self.start:
            self.end = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.start:
            self.owner.finish(win32.message_pos())


class SelectionOverlay(QObject):
    """Emits selected(x, y, w, h) in physical screen pixels, or cancelled()."""

    selected = Signal(int, int, int, int)
    cancelled = Signal()

    def __init__(self, hint: str = ""):
        super().__init__()
        self.hint = hint
        self.phys_start: tuple[int, int] | None = None
        self._widgets: list[_ScreenOverlay] = []
        self._esc = QTimer(self)
        self._esc.timeout.connect(self._check_esc)

    def show(self) -> None:
        self.phys_start = None
        self._widgets = [_ScreenOverlay(self, s) for s in QGuiApplication.screens()]
        for w in self._widgets:
            w.show()
        if self._widgets:
            self._widgets[0].activateWindow()
            self._widgets[0].raise_()
        # Polled, because the overlay doesn't always get keyboard focus.
        self._esc.start(30)

    def _close(self) -> None:
        self._esc.stop()
        for w in self._widgets:
            w.close()
        self._widgets = []

    def _check_esc(self) -> None:
        if win32.key_down(win32.VK_ESCAPE):
            self.cancel()

    def cancel(self) -> None:
        self._close()
        self.cancelled.emit()

    def finish(self, phys_end: tuple[int, int]) -> None:
        start = self.phys_start
        self._close()
        if start is None:
            self.cancelled.emit()
            return
        x0, x1 = sorted((start[0], phys_end[0]))
        y0, y1 = sorted((start[1], phys_end[1]))
        if x1 - x0 < _MIN_BOX or y1 - y0 < _MIN_BOX:
            self.cancelled.emit()
            return
        self.selected.emit(x0, y0, x1 - x0, y1 - y0)
