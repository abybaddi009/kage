"""Settings dialog: edit hotkey bindings and palette options from the tray.

Saves to ``config.toml`` and signals the app to reload. Hotkey bindings are
captured by recording an actual key press (via :class:`ChordCaptureEdit`)
rather than typed as free text, so the resulting chord string always matches
what ``parse_chord`` expects.

The dialog uses a macOS System Settings-style layout: an iconized sidebar on
the left and grouped "card" rows on the right. Native controls (checkboxes,
combo boxes, buttons) are left unstyled so they match the OS; only the
containers are themed, with colors derived from the system palette so the
dialog follows light/dark mode automatically.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
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
from .theme import Tokens as _Tokens

# (config value, name, description) -- keep values in sync with
# SWITCHER_THEMES in config.py.
_SWITCHER_THEMES = [
    ("default", "Default", "Icons with a preview of the selected window"),
    ("window_previews", "Window Previews", "Every window shown as a thumbnail"),
]

# (config value, display label) -- keep in sync with SCREEN_PREFERENCES in config.py.
_SCREEN_PREFERENCES = [
    ("active", "Active Screen"),
    ("pointer", "Screen with Pointer"),
]

# (config value, display label) -- keep in sync with UI_SIZES in config.py.
_UI_SIZES = [
    ("small", "Small"),
    ("medium", "Medium"),
    ("large", "Large"),
]

# Sidebar sections: (title, icon glyph, icon tile color). Glyphs use the
# text presentation selector (U+FE0E) where needed so they take the white
# pen color instead of rendering as color emoji.
_SECTIONS = [
    ("General", "⚙︎", "#8e8e93"),
    ("Switcher", "❐", "#3478f6"),
    ("Shortcuts", "⌘", "#af52de"),
    ("About", "ℹ︎", "#f09a37"),
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

# Portable chord modifier -> macOS display name. parse_chord() accepts both
# forms, so the display value round-trips through save/load unchanged.
_MAC_MOD_DISPLAY = {
    "Alt": "Option",
    "Super": "Command",
    "Cmd": "Command",
    "Ctrl": "Control",
}


def _format_chord(chord: str) -> str:
    """Convert a portable chord string to platform-native display names.

    On macOS: Alt→Option, Super/Cmd→Command, Ctrl→Control. Other platforms
    show the portable names as-is. The result still parses via
    ``parse_chord()`` since it accepts both forms.
    """
    if sys.platform != "darwin":
        return chord
    parts = chord.split("+")
    return "+".join(_MAC_MOD_DISPLAY.get(p.strip(), p.strip()) for p in parts)


class ChordCaptureEdit(QLineEdit):
    """A read-only field that records a chord from an actual key press.

    Click "Record" (or call :meth:`start_recording`) to arm it; the next
    key press with at least one modifier is captured and formatted as a
    chord string using platform-native modifier names (e.g. ``Option+Tab``
    on macOS, ``Alt+Tab`` elsewhere). Escape or losing focus while
    recording cancels and restores the previous value.
    """

    chord_captured = Signal(str)

    def __init__(self, initial: str, parent=None) -> None:
        super().__init__(parent)
        self._recording = False
        self._pre_record_text = _format_chord(initial)
        self.setReadOnly(True)
        self.setText(_format_chord(initial))

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
        display = _format_chord(chord)
        self._recording = False
        self.setText(display)
        self.chord_captured.emit(display)


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
    row.setFixedWidth(270)
    return row, edit


class _SegmentedControl(QWidget):
    """A macOS-style segmented control: checkable toggle buttons in a
    single joined row, exactly one active at a time (exclusive radio group).

    ``value()`` returns the config value of the currently-checked button.
    Used for the UI Size picker so the user gets three joined buttons
    (Small | Medium | Large) instead of a dropdown.
    """

    value_changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], current: str, parent=None) -> None:
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._button_values: dict[QPushButton, str] = {}

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        tokens = _Tokens()
        for i, (value, label) in enumerate(options):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("value", value)
            # Joined-segment styling: shared border, no internal rounding so
            # adjacent buttons form one continuous pill; the checked state
            # uses the accent color so selection matches the rest of the app.
            left_r = 6 if i == 0 else 0
            right_r = 6 if i == len(options) - 1 else 0
            btn.setStyleSheet(
                "QPushButton{"
                f"background:{tokens.card_bg};"
                f"border:1px solid {tokens.card_border};"
                f"border-left-width:{0 if i > 0 else 1}px;"
                f"border-top-left-radius:{left_r}px;"
                f"border-bottom-left-radius:{left_r}px;"
                f"border-top-right-radius:{right_r}px;"
                f"border-bottom-right-radius:{right_r}px;"
                "padding:6px 14px;"
                "font-size:12px;"
                "min-width:60px;"
                "}"
                f"QPushButton:checked{{background:{tokens.accent};color:#ffffff;border-color:{tokens.accent};}}"
                "QPushButton:hover:!checked{background:" + tokens.hover + ";}"
            )
            if value == current:
                btn.setChecked(True)
            self._group.addButton(btn)
            self._button_values[btn] = value
            lay.addWidget(btn)

        self._group.buttonToggled.connect(self._on_toggled)

    def _on_toggled(self, button: QPushButton, checked: bool) -> None:
        if checked:
            self.value_changed.emit(self._button_values[button])

    def value(self) -> str:
        btn = self._group.checkedButton()
        if btn is None:
            return ""
        return self._button_values.get(btn, "")


def _section_icon(glyph: str, color: str) -> QIcon:
    """Paint a macOS System Settings-style icon tile: colored rounded
    square with a white glyph. Rendered at 2x for retina displays."""
    pm = QPixmap(40, 40)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(0, 0, 20, 20), 5, 5)
    p.setPen(QColor("#ffffff"))
    font = QFont()
    font.setPixelSize(12)
    p.setFont(font)
    p.drawText(QRectF(0, 0, 20, 20), Qt.AlignCenter, glyph)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------
# Theme picker (image cards)
# ---------------------------------------------------------------------------


class _ThemeCard(QFrame):
    """A clickable preview card for one switcher theme.

    Selection is shown as an accent border around the card (styled from the
    dialog-level stylesheet via the ``selected`` dynamic property) so the
    preview image stays visible.
    """

    def __init__(self, value: str, name: str, desc: str, image_path) -> None:
        super().__init__()
        self._value = value
        self.setObjectName("themeCard")
        self.setProperty("selected", False)
        self.setCursor(Qt.PointingHandCursor)

        self._pic = QLabel()
        self._pic.setAlignment(Qt.AlignCenter)
        self._pic.setFixedSize(200, 120)
        self._pic.setObjectName("muted")
        self.set_image(image_path)
        pic = self._pic

        title = QLabel(name)
        title.setAlignment(Qt.AlignCenter)
        f = title.font()
        f.setBold(True)
        title.setFont(f)

        sub = QLabel(desc)
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        sub.setAlignment(Qt.AlignCenter)
        f = sub.font()
        f.setPointSize(10)
        sub.setFont(f)
        sub.setMaximumWidth(200)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)
        lay.addWidget(pic)
        lay.addWidget(title)
        lay.addWidget(sub)

    def value(self) -> str:
        return self._value

    def set_image(self, image_path) -> None:
        pix = QPixmap(str(image_path)) if image_path is not None else QPixmap()
        if not pix.isNull():
            self._pic.setText("")
            self._pic.setPixmap(
                pix.scaled(200, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            self._pic.setPixmap(QPixmap())
            self._pic.setText("(no preview)")

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        # Re-polish so the [selected="true"] stylesheet rule takes effect.
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        if event.button() == Qt.LeftButton:
            self.parent().select(self._value)
        super().mousePressEvent(event)


class _ThemePicker(QWidget):
    """A horizontal row of theme cards; tracks the selected one."""

    selection_changed = Signal(str)

    def __init__(
        self, themes, expanded: bool = False, previews: bool = True, parent=None
    ) -> None:
        super().__init__(parent)
        self._cards: dict[str, _ThemeCard] = {}
        self._value = themes[0][0] if themes else ""
        self._expanded = bool(expanded)
        self._previews = bool(previews)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        for value, name, desc in themes:
            image_path = theme_preview_path(value, self._expanded, self._previews)
            card = _ThemeCard(value, name, desc, image_path)
            self._cards[value] = card
            lay.addWidget(card)
        lay.addStretch(1)
        self.select(self._value)

    def _refresh_images(self) -> None:
        for value, card in self._cards.items():
            card.set_image(theme_preview_path(value, self._expanded, self._previews))

    def set_expanded(self, expanded: bool) -> None:
        """Swap card images to the variant matching the expand-windows toggle."""
        expanded = bool(expanded)
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._refresh_images()

    def set_previews_enabled(self, previews: bool) -> None:
        """Swap card images to the variant matching the show-previews toggle."""
        previews = bool(previews)
        if previews == self._previews:
            return
        self._previews = previews
        self._refresh_images()

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
# Settings dialog (sidebar + stacked pages of grouped cards)
# ---------------------------------------------------------------------------


class _Card(QFrame):
    """A rounded group box holding settings rows with hairline separators."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(14, 2, 14, 2)
        self._lay.setSpacing(0)
        self._count = 0

    def _maybe_separator(self) -> None:
        if self._count:
            sep = QFrame()
            sep.setObjectName("separator")
            sep.setFixedHeight(1)
            self._lay.addWidget(sep)

    def add_row(self, label: str, widget: QWidget) -> None:
        """Label on the left, control right-aligned — macOS settings style."""
        self._maybe_separator()
        row = QHBoxLayout()
        row.setContentsMargins(0, 9, 0, 9)
        row.addWidget(QLabel(label))
        row.addStretch(1)
        row.addWidget(widget)
        self._lay.addLayout(row)
        self._count += 1

    def add_full(self, widget: QWidget) -> None:
        """A row spanning the card's full width (e.g. the theme picker)."""
        self._maybe_separator()
        row = QVBoxLayout()
        row.setContentsMargins(0, 10, 0, 10)
        row.addWidget(widget)
        self._lay.addLayout(row)
        self._count += 1


class _Page(QWidget):
    """A content page: title, optional subtitle, then grouped cards."""

    def __init__(self, title: str, subtitle: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(26, 22, 26, 22)
        self._lay.setSpacing(10)

        header = QLabel(title)
        f = header.font()
        f.setPointSize(15)
        f.setBold(True)
        header.setFont(f)
        self._lay.addWidget(header)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("muted")
            sub.setWordWrap(True)
            self._lay.addWidget(sub)

        self._card: _Card | None = None

    def card(self) -> _Card:
        if self._card is None:
            self._card = _Card()
            self._lay.addWidget(self._card)
        return self._card

    def new_card(self) -> None:
        """Close the current group; the next row starts a fresh card."""
        self._card = None

    def add_row(self, label: str, widget: QWidget) -> None:
        self.card().add_row(label, widget)

    def add_full(self, widget: QWidget) -> None:
        self.card().add_full(widget)

    def add_widget(self, widget: QWidget, center: bool = False) -> None:
        if center:
            self._lay.addWidget(widget, alignment=Qt.AlignHCenter)
        else:
            self._lay.addWidget(widget)

    def add_stretch(self) -> None:
        self._lay.addStretch(1)


class SettingsDialog(QDialog):
    reloaded = Signal()

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Alt-Tabber Settings")
        self.setModal(True)
        self._config = config
        self._launch_at_login_init = self._is_launch_at_login()
        tokens = _Tokens()

        # ---- General page ----
        general = _Page("General")

        self._launch_at_login = QCheckBox()
        self._launch_at_login.setChecked(self._launch_at_login_init)
        general.add_row("Launch Alt-Tabber at login", self._launch_at_login)

        self._screen_preference = QComboBox()
        for value, label in _SCREEN_PREFERENCES:
            self._screen_preference.addItem(label, value)
        idx = self._screen_preference.findData(config.screen_preference)
        self._screen_preference.setCurrentIndex(idx if idx >= 0 else 0)
        general.add_row("Open launcher and switcher on", self._screen_preference)

        self._ui_size = _SegmentedControl(_UI_SIZES, config.ui_size)
        general.add_row("UI size", self._ui_size)

        self._max_results = QSpinBox()
        self._max_results.setRange(1, 100)
        self._max_results.setValue(config.palette.max_results)
        general.add_row("Maximum palette results", self._max_results)

        self._windows_first = QCheckBox()
        self._windows_first.setChecked(config.palette.windows_first)
        general.add_row(
            "Rank open windows above unopened apps", self._windows_first
        )

        self._overview_enabled = QCheckBox()
        self._overview_enabled.setChecked(config.palette.overview_enabled)
        general.add_row(
            "Show open windows overview grid", self._overview_enabled
        )

        self._overview_columns = QSpinBox()
        self._overview_columns.setRange(2, 8)
        self._overview_columns.setValue(config.palette.overview_columns)
        general.add_row("Overview tiles per row", self._overview_columns)
        general.add_stretch()

        # ---- Switcher page ----
        switcher = _Page("Switcher", "Choose how the switcher looks and behaves.")

        self._theme_picker = _ThemePicker(
            _SWITCHER_THEMES,
            expanded=config.switcher.expand_windows,
            previews=config.switcher.show_previews,
        )
        self._theme_picker.select(config.switcher.theme)
        switcher.add_full(self._theme_picker)

        self._expand_windows = QCheckBox()
        self._expand_windows.setChecked(config.switcher.expand_windows)
        self._expand_windows.toggled.connect(self._theme_picker.set_expanded)
        switcher.add_row(
            "Show every window as its own entry", self._expand_windows
        )

        self._show_previews = QCheckBox()
        self._show_previews.setChecked(config.switcher.show_previews)
        self._show_previews.toggled.connect(self._theme_picker.set_previews_enabled)
        switcher.add_row(
            "Show a live preview while switching", self._show_previews
        )
        switcher.add_stretch()

        # ---- Shortcuts page ----
        shortcuts = _Page(
            "Shortcuts",
            "Click “Record…”, then press the key combo you want "
            "(e.g. hold Option and tap Tab for Alt+Tab).",
        )

        launcher_row, self._launcher = _chord_row(config.hotkeys.launcher)
        app_switcher_row, self._app_switcher = _chord_row(config.hotkeys.app_switcher)
        window_switcher_row, self._window_switcher = _chord_row(
            config.hotkeys.window_switcher
        )
        shortcuts.add_row("Launcher", launcher_row)
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
        about.add_widget(logo_lbl, center=True)

        name_lbl = QLabel("Alt-Tabber")
        f = name_lbl.font()
        f.setPointSize(18)
        f.setBold(True)
        name_lbl.setFont(f)
        name_lbl.setAlignment(Qt.AlignCenter)
        about.add_widget(name_lbl)

        version_lbl = QLabel(f"Version {__version__}")
        version_lbl.setObjectName("muted")
        version_lbl.setAlignment(Qt.AlignCenter)
        about.add_widget(version_lbl)

        bundle_lbl = QLabel("dev.baddi.abhishek.AltTabber")
        bundle_lbl.setObjectName("muted")
        bundle_lbl.setAlignment(Qt.AlignCenter)
        about.add_widget(bundle_lbl)
        about.add_stretch()

        # ---- Sidebar + stack ----
        self._stack = QStackedWidget()
        self._stack.addWidget(general)
        self._stack.addWidget(switcher)
        self._stack.addWidget(shortcuts)
        self._stack.addWidget(about)

        self._sidebar = QListWidget()
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(185)
        self._sidebar.setIconSize(QSize(20, 20))
        self._sidebar.setFocusPolicy(Qt.NoFocus)
        for title, glyph, color in _SECTIONS:
            QListWidgetItem(_section_icon(glyph, color), title, self._sidebar)
        self._sidebar.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._sidebar.setCurrentRow(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._sidebar)
        body.addWidget(self._stack, stretch=1)

        # ---- Footer (hairline + inset Save/Cancel) ----
        footer_line = QFrame()
        footer_line.setObjectName("separator")
        footer_line.setFixedHeight(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        footer = QWidget()
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(16, 10, 16, 12)
        footer_lay.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(body, stretch=1)
        layout.addWidget(footer_line)
        layout.addWidget(footer)

        self.setStyleSheet(
            f"""
            #sidebar {{
                background: {tokens.sidebar_bg};
                border: none;
                outline: 0;
                padding: 8px 0;
            }}
            #sidebar::item {{
                padding: 5px 8px;
                margin: 1px 8px;
                border-radius: 6px;
            }}
            #sidebar::item:selected {{
                background: {tokens.accent};
                color: #ffffff;
            }}
            #sidebar::item:hover:!selected {{
                background: {tokens.hover};
            }}
            QFrame#card {{
                background: {tokens.card_bg};
                border: 1px solid {tokens.card_border};
                border-radius: 10px;
            }}
            QFrame#separator {{
                background: {tokens.separator};
                border: none;
            }}
            QLabel#muted {{
                color: {tokens.muted};
            }}
            QFrame#themeCard {{
                background: {tokens.card_bg};
                border: 2px solid transparent;
                border-radius: 10px;
            }}
            QFrame#themeCard:hover {{
                border-color: {tokens.hover_border};
            }}
            QFrame#themeCard[selected="true"],
            QFrame#themeCard[selected="true"]:hover {{
                border-color: {tokens.accent};
            }}
            """
        )

        self.resize(760, 520)

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
        cfg.palette.overview_enabled = self._overview_enabled.isChecked()
        cfg.palette.overview_columns = self._overview_columns.value()
        cfg.switcher.expand_windows = self._expand_windows.isChecked()
        cfg.switcher.show_previews = self._show_previews.isChecked()
        cfg.switcher.theme = self._theme_picker.value()
        cfg.screen_preference = self._screen_preference.currentData()
        cfg.ui_size = self._ui_size.value() or "small"
        try:
            save_config(cfg)
        except Exception as exc:  # pragma: no cover - filesystem error
            QMessageBox.warning(self, "Alt-Tabber", f"Could not save config:\n{exc}")
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
