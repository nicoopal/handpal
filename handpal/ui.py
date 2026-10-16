"""Main window, tray icon and the logic tying text, box and mouse together."""

from __future__ import annotations

import sys
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPainterPath,
                           QPen, QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QKeySequenceEdit, QLabel, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton, QSlider, QSpinBox,
                               QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from . import win32
from .config import Config, Snippet
from .drawer import Drawer, DrawSettings
from .fonts import available_fonts, get_font
from .hotkeys import HotkeyManager
from .layout import LayoutOptions, layout_text, pen_paths
from .overlay import SelectionOverlay

INK = QColor("#1f3fbf")

SIZE_MODES = [("shrink", "Shrink to fit"), ("fixed", "Fixed size"),
              ("fill", "Fill the box")]
DRAW_MODES = [(False, "Stroke by stroke (print)"), (True, "One line per word (cursive)")]
TARGETS = [("cursor", "At the mouse"), ("box", "Pick a box")]

# Modifier keys that must be released before clicking (Ctrl+click means something else).
_MODIFIER_VKS = (0x10, 0x11, 0x12, 0x5B, 0x5C)


def make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(INK)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setPen(QPen(QColor("white"), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    path = QPainterPath(QPointF(14, 42))
    path.cubicTo(20, 18, 26, 18, 28, 44)
    path.cubicTo(32, 26, 40, 20, 44, 40)
    path.lineTo(52, 22)
    p.drawPath(path)
    p.end()
    return QIcon(pm)


def hotkey_text(seq: QKeySequence) -> str:
    return seq.toString(QKeySequence.PortableText).split(",")[0].strip()


def make_key_edit(value: str) -> QKeySequenceEdit:
    edit = QKeySequenceEdit(QKeySequence(value))
    if hasattr(edit, "setMaximumSequenceLength"):
        edit.setMaximumSequenceLength(1)
    if hasattr(edit, "setClearButtonEnabled"):
        edit.setClearButtonEnabled(True)
    return edit


class Preview(QWidget):
    """Shows the text as it will be written."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(150)
        self.text = ""
        self.cfg: Config | None = None

    def set_content(self, text: str, cfg: Config) -> None:
        self.text, self.cfg = text, cfg
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        p.setPen(QPen(QColor("#d8dce6"), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if not self.cfg:
            return
        # Physical pixels vs. widget pixels: draw at the real on-screen size.
        dpr = self.devicePixelRatioF()
        opts = _layout_options(self.cfg)
        opts.size_mode = "fixed"
        m = 12
        lay = layout_text(get_font(self.cfg.font), self.text, opts, (0, 0),
                          ((self.width() - 2 * m) * dpr, 10_000))
        p.translate(m, m)
        p.scale(1 / dpr, 1 / dpr)
        p.setPen(QPen(INK, 2 * dpr, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for path in pen_paths(lay, self.cfg.continuous):
            if len(path) == 1:
                p.drawPoint(QPointF(*path[0]))
            else:
                qp = QPainterPath(QPointF(*path[0]))
                for pt in path[1:]:
                    qp.lineTo(*pt)
                p.drawPath(qp)


def _layout_options(cfg: Config, letter_height: float | None = None) -> LayoutOptions:
    return LayoutOptions(letter_height=letter_height or cfg.letter_height,
                         line_spacing=cfg.line_spacing, letter_spacing=cfg.letter_spacing,
                         size_mode=cfg.size_mode)


class SnippetDialog(QDialog):
    def __init__(self, parent, snippet: Snippet | None):
        super().__init__(parent)
        self.setWindowTitle("Saved phrase")
        s = snippet or Snippet("")
        self.text = QPlainTextEdit(s.text)
        self.text.setPlaceholderText("Text to write (multiple lines are fine)")
        self.key = make_key_edit(s.hotkey)
        self.target = QComboBox()
        for value, label in TARGETS:
            self.target.addItem(label, value)
        self.target.setCurrentIndex(max(0, [t for t, _ in TARGETS].index(s.target)
                                        if s.target in dict(TARGETS) else 0))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(0, 400)
        self.height_spin.setSuffix(" px")
        self.height_spin.setSpecialValueText("Default")
        self.height_spin.setValue(int(s.letter_height))

        form = QFormLayout(self)
        form.addRow("Text", self.text)
        form.addRow("Shortcut", self.key)
        form.addRow("Where to write", self.target)
        form.addRow("Letter height", self.height_spin)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(420, 260)

    def snippet(self) -> Snippet:
        return Snippet(self.text.toPlainText().strip(), hotkey_text(self.key.keySequence()),
                       self.target.currentData(), float(self.height_spin.value()))


class MainWindow(QMainWindow):
    draw_finished = Signal(str)

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.drawer: Drawer | None = None
        self.overlay: SelectionOverlay | None = None
        self.restore_after_draw = False
        self.pending_text = ""
        self.pending_height: float | None = None
        self.quitting = False

        self.setWindowTitle("Handpal")
        self.setWindowIcon(make_icon())
        self.resize(640, 620)

        self.hotkeys = HotkeyManager()
        self.hotkeys.triggered.connect(self.on_hotkey)
        self.hotkeys.failed.connect(
            lambda k: self.statusBar().showMessage(f"Shortcut {k} could not be registered (is another app using it?)", 8000))
        self.draw_finished.connect(self.on_draw_finished)

        self.save_timer = QTimer(self, singleShot=True, interval=600)
        self.save_timer.timeout.connect(self.cfg.save)

        tabs = QTabWidget()
        tabs.addTab(self._build_write_tab(), "Write")
        tabs.addTab(self._build_snippets_tab(), "Phrases")
        tabs.addTab(self._build_hotkeys_tab(), "Shortcuts")
        self.setCentralWidget(tabs)
        self._build_tray()
        self.refresh_preview()
        self.apply_hotkeys()
        self.statusBar().showMessage("Press Esc or move the mouse to stop writing at any time.")

    # ---------- UI ----------

    def _build_write_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self.text_edit = QPlainTextEdit(self.cfg.text)
        self.text_edit.setPlaceholderText("Type what you want Handpal to write…")
        self.text_edit.setMaximumHeight(110)
        self.text_edit.textChanged.connect(self.on_settings_changed)
        lay.addWidget(self.text_edit)

        self.preview = Preview()
        lay.addWidget(self.preview, 1)

        form = QFormLayout()
        self.font_combo = QComboBox()
        self.font_combo.addItems(list(available_fonts()))
        self.font_combo.setCurrentText(self.cfg.font)
        self.font_combo.currentTextChanged.connect(self.on_settings_changed)
        form.addRow("Font", self.font_combo)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(6, 400)
        self.height_spin.setSuffix(" px")
        self.height_spin.setValue(int(self.cfg.letter_height))
        self.height_spin.valueChanged.connect(self.on_settings_changed)
        self.size_combo = QComboBox()
        for value, label in SIZE_MODES:
            self.size_combo.addItem(label, value)
        self.size_combo.setCurrentIndex([v for v, _ in SIZE_MODES].index(self.cfg.size_mode)
                                        if self.cfg.size_mode in dict(SIZE_MODES) else 0)
        self.size_combo.currentIndexChanged.connect(self.on_settings_changed)
        row = QHBoxLayout()
        row.addWidget(self.height_spin)
        row.addWidget(QLabel("in a box:"))
        row.addWidget(self.size_combo, 1)
        form.addRow("Capital height", row)

        self.spacing_spin = QDoubleSpinBox()
        self.spacing_spin.setRange(1.0, 4.0)
        self.spacing_spin.setSingleStep(0.1)
        self.spacing_spin.setValue(self.cfg.line_spacing)
        self.spacing_spin.valueChanged.connect(self.on_settings_changed)
        self.letter_spacing_spin = QDoubleSpinBox()
        self.letter_spacing_spin.setRange(-0.2, 1.0)
        self.letter_spacing_spin.setSingleStep(0.05)
        self.letter_spacing_spin.setValue(self.cfg.letter_spacing)
        self.letter_spacing_spin.valueChanged.connect(self.on_settings_changed)
        row = QHBoxLayout()
        row.addWidget(self.spacing_spin)
        row.addWidget(QLabel("letter spacing:"))
        row.addWidget(self.letter_spacing_spin)
        row.addStretch(1)
        form.addRow("Line spacing", row)

        self.mode_combo = QComboBox()
        for value, label in DRAW_MODES:
            self.mode_combo.addItem(label, value)
        self.mode_combo.setCurrentIndex(1 if self.cfg.continuous else 0)
        self.mode_combo.currentIndexChanged.connect(self.on_settings_changed)
        form.addRow("Pen mode", self.mode_combo)

        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(100, 3000)
        self.speed_slider.setSingleStep(50)
        self.speed_slider.setValue(int(self.cfg.speed))
        self.speed_label = QLabel()
        self.speed_slider.valueChanged.connect(self.on_settings_changed)
        row = QHBoxLayout()
        row.addWidget(self.speed_slider, 1)
        row.addWidget(self.speed_label)
        form.addRow("Speed", row)
        lay.addLayout(form)

        buttons = QHBoxLayout()
        self.box_button = QPushButton()
        self.box_button.setMinimumHeight(40)
        f = self.box_button.font()
        f.setPointSize(f.pointSize() + 1)
        f.setBold(True)
        self.box_button.setFont(f)
        self.box_button.clicked.connect(lambda: self.start_box(self.text_edit.toPlainText()))
        buttons.addWidget(self.box_button, 1)
        lay.addLayout(buttons)
        return w

    def _build_snippets_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Phrases written with a shortcut, from any app."))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Shortcut", "Text", "Where"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.doubleClicked.connect(self.edit_snippet)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        for label, slot in (("Add", self.add_snippet), ("Edit", self.edit_snippet),
                            ("Delete", self.delete_snippet)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.refresh_table()
        return w

    def _build_hotkeys_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.key_box = make_key_edit(self.cfg.hotkey_box)
        self.key_cursor = make_key_edit(self.cfg.hotkey_cursor)
        self.key_box.editingFinished.connect(self.on_hotkeys_edited)
        self.key_cursor.editingFinished.connect(self.on_hotkeys_edited)
        for edit in (self.key_box, self.key_cursor):
            if hasattr(edit, "keySequenceChanged"):
                edit.keySequenceChanged.connect(lambda _=None: self.on_hotkeys_edited())
        form.addRow("Write the text in a box", self.key_box)
        form.addRow("Write the text at the mouse", self.key_cursor)
        note = QLabel("To stop writing: press <b>Esc</b>, or just move the mouse.<br>"
                      "Each phrase's shortcut is set in the <i>Phrases</i> tab.<br>"
                      "Before writing, pick the pen tool in your whiteboard.")
        note.setWordWrap(True)
        form.addRow(note)
        return w

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip("Handpal")
        menu = QMenu()
        menu.addAction("Open Handpal", self.show_window)
        menu.addAction("Write in a box", lambda: self.start_box(self.cfg.text))
        menu.addSeparator()
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.show_window() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self._tray_menu = menu

    # ---------- settings ----------

    def on_settings_changed(self) -> None:
        c = self.cfg
        c.text = self.text_edit.toPlainText()
        c.font = self.font_combo.currentText()
        c.letter_height = float(self.height_spin.value())
        c.size_mode = self.size_combo.currentData()
        c.line_spacing = self.spacing_spin.value()
        c.letter_spacing = self.letter_spacing_spin.value()
        c.continuous = bool(self.mode_combo.currentData())
        c.speed = float(self.speed_slider.value())
        self.refresh_preview()
        self.save_timer.start()

    def refresh_preview(self) -> None:
        self.speed_label.setText(f"{int(self.cfg.speed)} px/s")
        key = self.cfg.hotkey_box
        self.box_button.setText("✍  Pick a box and write" + (f"   ({key})" if key else ""))
        self.preview.set_content(self.cfg.text, self.cfg)

    def on_hotkeys_edited(self) -> None:
        box = hotkey_text(self.key_box.keySequence())
        cur = hotkey_text(self.key_cursor.keySequence())
        if (box, cur) == (self.cfg.hotkey_box, self.cfg.hotkey_cursor):
            return
        self.cfg.hotkey_box, self.cfg.hotkey_cursor = box, cur
        self.apply_hotkeys()
        self.refresh_preview()
        self.save_timer.start()

    def apply_hotkeys(self) -> None:
        mapping = {"box": self.cfg.hotkey_box, "cursor": self.cfg.hotkey_cursor}
        for i, s in enumerate(self.cfg.snippets):
            if s.hotkey:
                mapping[f"snippet:{i}"] = s.hotkey
        seen: dict[str, str] = {}
        for action, key in list(mapping.items()):
            if key and key in seen:
                self.statusBar().showMessage(f"Shortcut {key} is used twice; only the first one works.", 8000)
                del mapping[action]
            elif key:
                seen[key] = action
        self.hotkeys.set_hotkeys(mapping)

    # ---------- snippets ----------

    def refresh_table(self) -> None:
        self.table.setRowCount(len(self.cfg.snippets))
        for i, s in enumerate(self.cfg.snippets):
            self.table.setItem(i, 0, QTableWidgetItem(s.hotkey or "—"))
            self.table.setItem(i, 1, QTableWidgetItem(s.text.replace("\n", " ⏎ ")))
            self.table.setItem(i, 2, QTableWidgetItem(dict(TARGETS).get(s.target, s.target)))
        self.table.resizeColumnToContents(0)
        self.table.resizeColumnToContents(2)

    def _snippets_changed(self) -> None:
        self.refresh_table()
        self.apply_hotkeys()
        self.cfg.save()

    def add_snippet(self) -> None:
        dlg = SnippetDialog(self, None)
        if dlg.exec() and dlg.snippet().text:
            self.cfg.snippets.append(dlg.snippet())
            self._snippets_changed()

    def edit_snippet(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        dlg = SnippetDialog(self, self.cfg.snippets[row])
        if dlg.exec() and dlg.snippet().text:
            self.cfg.snippets[row] = dlg.snippet()
            self._snippets_changed()

    def delete_snippet(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        s = self.cfg.snippets[row]
        if QMessageBox.question(self, "Delete phrase", f"Delete \"{s.text}\"?") == QMessageBox.Yes:
            del self.cfg.snippets[row]
            self._snippets_changed()

    # ---------- writing ----------

    def busy(self) -> bool:
        return self.drawer is not None or self.overlay is not None

    def on_hotkey(self, action: str) -> None:
        if self.busy():
            return
        if action == "box":
            self.start_box(self.cfg.text)
        elif action == "cursor":
            self.start_cursor(self.cfg.text)
        elif action.startswith("snippet:"):
            i = int(action.split(":", 1)[1])
            if i < len(self.cfg.snippets):
                s = self.cfg.snippets[i]
                height = s.letter_height or None
                if s.target == "box":
                    self.start_box(s.text, height)
                else:
                    self.start_cursor(s.text, height)

    def _hide_for_drawing(self) -> None:
        self.restore_after_draw = self.isVisible() and not self.isMinimized()
        if self.restore_after_draw:
            self.hide()

    def start_box(self, text: str, letter_height: float | None = None) -> None:
        if self.busy() or not text.strip():
            return
        self.pending_text, self.pending_height = text, letter_height
        self._hide_for_drawing()
        self.overlay = SelectionOverlay("Drag to mark where to write\n(Esc or right-click to cancel)")
        self.overlay.selected.connect(self.on_box_selected)
        self.overlay.cancelled.connect(self.on_box_cancelled)
        # Let the main window disappear before covering the screen.
        QTimer.singleShot(120, self.overlay.show)

    def on_box_cancelled(self) -> None:
        self.overlay = None
        self._restore_window()

    def on_box_selected(self, x: int, y: int, w: int, h: int) -> None:
        self.overlay = None
        font = get_font(self.cfg.font)
        lay = layout_text(font, self.pending_text, _layout_options(self.cfg, self.pending_height),
                          (x, y), (w, h))
        if lay.overflow:
            self.tray.showMessage("Handpal", "The text does not fully fit in the box.",
                                  QSystemTrayIcon.Warning, 3000)
        # Give the overlay time to vanish so the clicks reach the app below.
        QTimer.singleShot(200, lambda: self._draw(pen_paths(lay, self.cfg.continuous)))

    def start_cursor(self, text: str, letter_height: float | None = None) -> None:
        if self.busy() or not text.strip():
            return
        x, y = win32.cursor_pos()
        font = get_font(self.cfg.font)
        opts = _layout_options(self.cfg, letter_height)
        lay = layout_text(font, text, opts, (x, y))
        self._hide_for_drawing()
        self._draw(pen_paths(lay, self.cfg.continuous), wait_modifiers=True)

    def _draw(self, paths, wait_modifiers: bool = False) -> None:
        if not paths:
            self._restore_window()
            return
        settings = DrawSettings(speed=self.cfg.speed, stroke_pause_ms=self.cfg.stroke_pause_ms)

        def finish(result: str) -> None:
            self.draw_finished.emit(result)

        self.drawer = Drawer(paths, settings, finish)
        if wait_modifiers:
            # A hotkey like Ctrl+Shift+1 is still held: clicking now would be Ctrl+click.
            self._wait_modifiers_then(self.drawer.start, time.monotonic() + 3)
        else:
            self.drawer.start()

    def _wait_modifiers_then(self, fn, deadline: float) -> None:
        if any(win32.key_down(vk) for vk in _MODIFIER_VKS) and time.monotonic() < deadline:
            QTimer.singleShot(20, lambda: self._wait_modifiers_then(fn, deadline))
        else:
            QTimer.singleShot(60, fn)

    def on_draw_finished(self, result: str) -> None:
        self.drawer = None
        if result == "aborted":
            self.statusBar().showMessage("Writing stopped.", 5000)
        elif result.startswith("error"):
            self.tray.showMessage("Handpal", result, QSystemTrayIcon.Critical, 5000)
        self._restore_window()

    def _restore_window(self) -> None:
        if self.restore_after_draw:
            self.restore_after_draw = False
            self.show_window()

    # ---------- window ----------

    def show_window(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):
        if self.quitting:
            e.accept()
            return
        e.ignore()
        self.hide()
        if not getattr(self, "_told_tray", False):
            self._told_tray = True
            self.tray.showMessage("Handpal is still running",
                                  "Shortcuts keep working. To quit, use the tray icon.",
                                  QSystemTrayIcon.Information, 4000)

    def quit(self) -> None:
        self.quitting = True
        if self.drawer:
            self.drawer.stop()
        self.hotkeys.stop()
        self.cfg.save()
        QApplication.quit()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Handpal")
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(Config.load())
    window.show()
    sys.exit(app.exec())
