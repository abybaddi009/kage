"""Settings dialog: edit hotkey bindings and palette options from the tray.

Saves to ``config.toml`` and signals the app to reload. Hotkey bindings are
captured by recording an actual key press (via :class:`ChordCaptureEdit`)
rather than typed as free text, so the resulting chord string always matches
what ``parse_chord`` expects.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import Config, save_config

# Qt.Key -> chord key token, matching the names parse_chord()/_KEYCODES accept.
_KEY_NAMES: dict[int, str] = {
    Qt.Key_Tab: "tab",
    Qt.Key_Return: "return",
    Qt.Key_Enter: "enter",
    Qt.Key_Space: "space",
    Qt.Key_Escape: "escape",
    Qt.Key_QuoteLeft: "`",
    Qt.Key_Minus: "-",
    Qt.Key_Equal: "=",
    Qt.Key_BracketLeft: "[",
    Qt.Key_BracketRight: "]",
    Qt.Key_Backslash: "\\",
    Qt.Key_Semicolon: ";",
    Qt.Key_Apostrophe: "'",
    Qt.Key_Comma: ",",
    Qt.Key_Period: ".",
    Qt.Key_Slash: "/",
}
for _c in "abcdefghijklmnopqrstuvwxyz0123456789":
    _KEY_NAMES[getattr(Qt, f"Key_{_c.upper()}")] = _c

# Keys that are themselves modifiers: never treated as "the" key of a chord.
_MODIFIER_KEYS = {
    Qt.Key_Control,
    Qt.Key_Alt,
    Qt.Key_AltGr,
    Qt.Key_Shift,
    Qt.Key_Meta,
    Qt.Key_CapsLock,
}


class ChordCaptureEdit(QLineEdit):
    """A read-only field that records a chord from an actual key press.

    Click "Record" (or call :meth:`start_recording`) to arm it; the next
    key press with at least one modifier is captured and formatted as a
    Kage chord string (e.g. ``Alt+Tab``). Escape or losing focus while
    recording cancels and restores the previous value.
    """

    chord_captured = Signal(str)

    def __init__(self, initial: str, parent=None) -> None:
        super().__init__(parent)
        self._recording = False
        self._pre_record_text = initial
        self.setReadOnly(True)
        self.setText(initial)

    def start_recording(self) -> None:
        self._pre_record_text = self.text()
        self._recording = True
        self.setText("Press keys…")
        self.setFocus(Qt.OtherFocusReason)

    def _cancel_recording(self) -> None:
        self._recording = False
        self.setText(self._pre_record_text)

    def event(self, ev) -> bool:  # noqa: N802 - Qt override
        # QWidget's default event() consumes Tab/Backtab for focus traversal
        # before keyPressEvent ever sees them; intercept here so chords like
        # Alt+Tab can be recorded.
        if self._recording and ev.type() == QEvent.KeyPress:
            self._handle_key(ev)
            return True
        return super().event(ev)

    def focusOutEvent(self, ev) -> None:  # noqa: N802 - Qt override
        if self._recording:
            self._cancel_recording()
        super().focusOutEvent(ev)

    def _handle_key(self, ev) -> None:
        key = ev.key()
        if key in _MODIFIER_KEYS:
            return  # still waiting for a non-modifier key

        mods = ev.modifiers()
        if key == Qt.Key_Escape and mods == Qt.NoModifier:
            self._cancel_recording()
            return

        parts: list[str] = []
        if sys.platform == "darwin":
            # Qt swaps Control/Meta on macOS so cross-platform Ctrl+ shortcuts
            # land on Cmd; undo that swap to report the physical keys.
            if mods & Qt.ControlModifier:
                parts.append("Cmd")
            if mods & Qt.MetaModifier:
                parts.append("Ctrl")
        else:
            if mods & Qt.ControlModifier:
                parts.append("Ctrl")
            if mods & Qt.MetaModifier:
                parts.append("Super")
        if mods & Qt.AltModifier:
            parts.append("Alt")
        if mods & Qt.ShiftModifier:
            parts.append("Shift")

        key_str = _KEY_NAMES.get(key)
        if key_str is None or not parts:
            # Unsupported key, or no modifier held: keep waiting rather than
            # silently producing an invalid/unintended chord.
            return

        parts.append(key_str)
        chord = "+".join(parts)
        self._recording = False
        self.setText(chord)
        self.chord_captured.emit(chord)


def _chord_row(initial: str) -> tuple[QWidget, ChordCaptureEdit]:
    """Build a (line edit + Record button) row, returning the row widget."""
    edit = ChordCaptureEdit(initial)
    button = QPushButton("Record…")
    button.clicked.connect(edit.start_recording)

    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(edit, stretch=1)
    layout.addWidget(button)
    return row, edit


class SettingsDialog(QDialog):
    reloaded = Signal()

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kage Settings")
        self.setModal(True)
        self._config = config

        form = QFormLayout()

        hint = QLabel(
            "Click “Record…”, then press the key combo you want "
            "(e.g. hold Option and tap Tab for Alt+Tab)."
        )
        hint.setWordWrap(True)

        launcher_row, self._launcher = _chord_row(config.hotkeys.launcher)
        app_switcher_row, self._app_switcher = _chord_row(config.hotkeys.app_switcher)
        window_switcher_row, self._window_switcher = _chord_row(
            config.hotkeys.window_switcher
        )
        form.addRow("Launcher hotkey", launcher_row)
        form.addRow("App switcher (Alt+Tab style)", app_switcher_row)
        form.addRow("Window switcher (per-app)", window_switcher_row)

        self._max_results = QSpinBox()
        self._max_results.setRange(1, 100)
        self._max_results.setValue(config.palette.max_results)
        form.addRow("Max palette results", self._max_results)

        self._windows_first = QCheckBox("Open windows ranked above unopened apps")
        self._windows_first.setChecked(config.palette.windows_first)
        form.addRow("", self._windows_first)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        cfg = self._config
        cfg.hotkeys.launcher = self._launcher.text().strip()
        cfg.hotkeys.app_switcher = self._app_switcher.text().strip()
        cfg.hotkeys.window_switcher = self._window_switcher.text().strip()
        cfg.palette.max_results = self._max_results.value()
        cfg.palette.windows_first = self._windows_first.isChecked()
        try:
            save_config(cfg)
        except Exception as exc:  # pragma: no cover - filesystem error
            QMessageBox.warning(self, "Kage", f"Could not save config:\n{exc}")
            return
        self.accept()
        self.reloaded.emit()
