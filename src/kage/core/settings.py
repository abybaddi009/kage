"""Settings dialog: edit hotkey bindings and palette options from the tray.

Saves to ``config.toml`` and signals the app to reload. Hotkey bindings are
captured by recording an actual key press (via :class:`ChordCaptureEdit`)
rather than typed as free text, so the resulting chord string always matches
what ``parse_chord`` expects.

The dialog uses a macOS System Settings-style sidebar (section list) with a
stacked content pane on the right. "Launch at login" lives in the General
section; the switcher theme is picked from image cards.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from .config import Config, save_config
from .paths import logo_path, theme_preview_path

# (config value, display label) -- keep in sync with SWITCHER_THEMES in config.py.
_SWITCHER_THEMES = [
    ("default", "Default (icons + selected-window preview)"),
    ("window_previews", "Window Previews (every window shown as a thumbnail)"),
]

# (config value, display label) -- keep in sync with SCREEN_PREFERENCES in config.py.
_SCREEN_PREFERENCES = [
    ("active", "Active Screen"),
    ("pointer", "Screen with Pointer"),
]

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


# ---------------------------------------------------------------------------
# Theme picker (image cards)
# ---------------------------------------------------------------------------


class _ThemeCard(QFrame):
    """A clickable preview card for one switcher theme."""

    def __init__(self, value: str, label: str, image_path) -> None:
        super().__init__()
        self._value = value
        self._selected = False
        self.setObjectName("themeCard")
        self.setCursor(Qt.PointingHandCursor)

        pic = QLabel()
        pic.setAlignment(Qt.AlignCenter)
        pix = QPixmap(str(image_path)) if image_path is not None else QPixmap()
        if not pix.isNull():
            pic.setPixmap(
                pix.scaled(
                    260, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
        else:
            pic.setFixedSize(260, 150)
            pic.setText("(no preview)")
            pic.setStyleSheet("color:#9ca3af;")

        text = QLabel(label)
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignCenter)
        f = text.font()
        f.setPointSize(10)
        text.setFont(f)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        lay.addWidget(pic)
        lay.addWidget(text)

        self._update_style()

    def value(self) -> str:
        return self._value

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self._update_style()

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        if event.button() == Qt.LeftButton:
            self.parent().select(self._value)
        super().mousePressEvent(event)

    def _update_style(self) -> None:
        if self._selected:
            self.setStyleSheet(
                "#themeCard{background:#3b82f6;border-radius:8px;}"
                "QLabel{color:#ffffff;}"
            )
        else:
            self.setStyleSheet(
                "#themeCard{background:rgba(255,255,255,16);border-radius:8px;}"
                "QLabel{color:#e5e7eb;}"
            )


class _ThemePicker(QWidget):
    """A horizontal row of theme cards; tracks the selected one."""

    selection_changed = Signal(str)

    def __init__(self, themes, parent=None) -> None:
        super().__init__(parent)
        self._cards: dict[str, _ThemeCard] = {}
        self._value = themes[0][0] if themes else ""

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        for value, label in themes:
            image_path = theme_preview_path(value)
            card = _ThemeCard(value, label, image_path)
            self._cards[value] = card
            lay.addWidget(card)
        lay.addStretch(1)
        self.select(self._value)

    def select(self, value: str) -> None:
        if value not in self._cards:
            return
        self._value = value
        for v, card in self._cards.items():
            card.set_selected(v == value)
        self.selection_changed.emit(value)

    def value(self) -> str:
        return self._value


# ---------------------------------------------------------------------------
# Settings dialog (sidebar + stacked pages)
# ---------------------------------------------------------------------------


class _Page(QFrame):
    """A content page with a header and a list of rows."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self.setStyleSheet(
            "#settingsPage{background:transparent;}"
        )
        header = QLabel(title)
        f = header.font()
        f.setPointSize(15)
        f.setBold(True)
        header.setFont(f)

        self._rows = QVBoxLayout(self)
        self._rows.setContentsMargins(18, 12, 18, 18)
        self._rows.setSpacing(14)
        self._rows.addWidget(header)

    def add_row(self, label: str, widget: QWidget) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setMinimumWidth(190)
        row.addWidget(lbl, alignment=Qt.AlignTop | Qt.AlignLeft)
        row.addWidget(widget, stretch=1)
        self._rows.addLayout(row)

    def add_stretch(self) -> None:
        self._rows.addStretch(1)


class SettingsDialog(QDialog):
    reloaded = Signal()

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kage Settings")
        self.setModal(True)
        self._config = config
        self._launch_at_login_init = self._is_launch_at_login()

        # ---- General page ----
        general = _Page("General")

        self._launch_at_login = QCheckBox("Launch Kage at login")
        self._launch_at_login.setChecked(self._launch_at_login_init)
        general.add_row("", self._launch_at_login)

        self._screen_preference = QComboBox()
        for value, label in _SCREEN_PREFERENCES:
            self._screen_preference.addItem(label, value)
        idx = self._screen_preference.findData(config.screen_preference)
        self._screen_preference.setCurrentIndex(idx if idx >= 0 else 0)
        general.add_row("Open launcher/switcher on", self._screen_preference)

        self._max_results = QSpinBox()
        self._max_results.setRange(1, 100)
        self._max_results.setValue(config.palette.max_results)
        general.add_row("Max palette results", self._max_results)

        self._windows_first = QCheckBox("Open windows ranked above unopened apps")
        self._windows_first.setChecked(config.palette.windows_first)
        general.add_row("", self._windows_first)
        general.add_stretch()

        # ---- Switcher page ----
        switcher = _Page("Switcher")

        self._theme_picker = _ThemePicker(_SWITCHER_THEMES)
        self._theme_picker.select(config.switcher.theme)
        switcher.add_row("Theme", self._theme_picker)

        self._expand_windows = QCheckBox(
            "Show every window as its own entry in Alt+Tab"
        )
        self._expand_windows.setChecked(config.switcher.expand_windows)
        switcher.add_row("", self._expand_windows)

        self._show_previews = QCheckBox(
            "Show a live preview while switching"
        )
        self._show_previews.setChecked(config.switcher.show_previews)
        switcher.add_row("", self._show_previews)
        switcher.add_stretch()

        # ---- Shortcuts page ----
        shortcuts = _Page("Shortcuts")
        hint = QLabel(
            "Click “Record…”, then press the key combo you want "
            "(e.g. hold Option and tap Tab for Alt+Tab)."
        )
        hint.setWordWrap(True)
        shortcuts._rows.addWidget(hint)

        launcher_row, self._launcher = _chord_row(config.hotkeys.launcher)
        app_switcher_row, self._app_switcher = _chord_row(config.hotkeys.app_switcher)
        window_switcher_row, self._window_switcher = _chord_row(
            config.hotkeys.window_switcher
        )
        shortcuts.add_row("Launcher hotkey", launcher_row)
        shortcuts.add_row("App switcher (Alt+Tab style)", app_switcher_row)
        shortcuts.add_row("Window switcher (per-app)", window_switcher_row)
        shortcuts.add_stretch()

        # ---- About page ----
        about = _Page("About")
        logo_lbl = QLabel()
        logo = logo_path()
        pix = QPixmap(str(logo)) if logo is not None else QPixmap()
        if not pix.isNull():
            logo_lbl.setPixmap(
                pix.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        logo_lbl.setAlignment(Qt.AlignCenter)
        about._rows.addWidget(logo_lbl, alignment=Qt.AlignHCenter)

        name_lbl = QLabel("Kage")
        f = name_lbl.font()
        f.setPointSize(18)
        f.setBold(True)
        name_lbl.setFont(f)
        name_lbl.setAlignment(Qt.AlignCenter)
        about._rows.addWidget(name_lbl)

        version_lbl = QLabel(f"Version {__version__}")
        version_lbl.setAlignment(Qt.AlignCenter)
        version_lbl.setStyleSheet("color:#9ca3af;")
        about._rows.addWidget(version_lbl)

        bundle_lbl = QLabel("dev.baddi.abhishek.Kage")
        bundle_lbl.setAlignment(Qt.AlignCenter)
        bundle_lbl.setStyleSheet("color:#9ca3af;")
        about._rows.addWidget(bundle_lbl)
        about.add_stretch()

        # ---- Sidebar + stack ----
        self._stack = QStackedWidget()
        self._stack.addWidget(general)
        self._stack.addWidget(switcher)
        self._stack.addWidget(shortcuts)
        self._stack.addWidget(about)

        self._sidebar = QListWidget()
        self._sidebar.setFixedWidth(160)
        self._sidebar.setCurrentRow(0)
        self._sidebar.currentRowChanged.connect(self._stack.setCurrentIndex)
        for title in ("General", "Switcher", "Shortcuts", "About"):
            QListWidgetItem(title, self._sidebar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._sidebar)
        body.addWidget(self._stack, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(body)
        layout.addWidget(buttons)

        # Keep the sidebar styling clean so the dialog feels native.
        self._sidebar.setStyleSheet(
            "QListWidget{background:#1f1f23;border:none;}"
            "QListWidget::item{padding:10px 14px;}"
            "QListWidget::item:selected{background:#3b82f6;color:#ffffff;}"
        )

        self.resize(720, 480)

    @staticmethod
    def _is_launch_at_login() -> bool:
        if sys.platform != "darwin":
            return False
        try:
            from ..platform.macos import launch_at_login

            return launch_at_login.is_launch_at_login()
        except Exception:
            return False

    def _on_save(self) -> None:
        cfg = self._config
        cfg.hotkeys.launcher = self._launcher.text().strip()
        cfg.hotkeys.app_switcher = self._app_switcher.text().strip()
        cfg.hotkeys.window_switcher = self._window_switcher.text().strip()
        cfg.palette.max_results = self._max_results.value()
        cfg.palette.windows_first = self._windows_first.isChecked()
        cfg.switcher.expand_windows = self._expand_windows.isChecked()
        cfg.switcher.show_previews = self._show_previews.isChecked()
        cfg.switcher.theme = self._theme_picker.value()
        cfg.screen_preference = self._screen_preference.currentData()
        try:
            save_config(cfg)
        except Exception as exc:  # pragma: no cover - filesystem error
            QMessageBox.warning(self, "Kage", f"Could not save config:\n{exc}")
            return

        if self._launch_at_login.isChecked() != self._launch_at_login_init:
            self._apply_launch_at_login(self._launch_at_login.isChecked())

        self.accept()
        self.reloaded.emit()

    @staticmethod
    def _apply_launch_at_login(enabled: bool) -> None:
        if sys.platform != "darwin":
            return
        try:
            from ..platform.macos import launch_at_login

            launch_at_login.set_launch_at_login(enabled)
        except Exception:
            pass
