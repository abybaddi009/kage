"""Alt+Tab style app switcher and per-app window switcher.

*SwitcherOverlay* is a frameless, horizontal icon strip shown instantly on
the switcher hotkey. *SwitcherController* implements ``SwitcherHandler`` and
drives the overlay + activation, reusing MRU ordering for apps and AX
window enumeration for per-app windows.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ..backends.base import AppProvider, WindowInfo, WindowProvider
from .mru import MRUTracker


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class _AppEntry:
    key: str  # bundle_id or app_name
    name: str
    icon_path: str | None
    bundle_id: str | None


@dataclass
class _WindowEntry:
    window_id: int
    title: str
    app_name: str
    icon_path: str | None
    bundle_id: str | None


# ---------------------------------------------------------------------------
# Overlay widget
# ---------------------------------------------------------------------------


class _ItemWidget(QFrame):
    """A single icon+label tile; highlights when selected."""

    def __init__(self, icon_path: str | None, label: str) -> None:
        super().__init__()
        self._selected = False
        self.setObjectName("switcherItem")

        icon_lbl = QLabel()
        pix = QPixmap(icon_path) if icon_path else QPixmap()
        if not pix.isNull():
            icon_lbl.setPixmap(
                pix.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            icon_lbl.setFixedSize(64, 64)
            icon_lbl.setText("▢")
            icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setAlignment(Qt.AlignCenter)

        text_lbl = QLabel(label)
        text_lbl.setWordWrap(True)
        text_lbl.setAlignment(Qt.AlignCenter)
        f = QFont()
        f.setPointSize(11)
        text_lbl.setFont(f)
        text_lbl.setMaximumWidth(96)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        lay.addWidget(icon_lbl)
        lay.addWidget(text_lbl)

        self.setFixedSize(108, 110)
        self._update_style()

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self._update_style()

    def _update_style(self) -> None:
        if self._selected:
            self.setStyleSheet(
                "_ItemWidget{background:#3b82f6;border-radius:8px;}"
                "QLabel{color:#ffffff;}"
            )
        else:
            self.setStyleSheet(
                "_ItemWidget{background:rgba(255,255,255,16);border-radius:8px;}"
                "QLabel{color:#e5e7eb;}"
            )


class SwitcherOverlay(QWidget):
    activate_app = Signal(str)  # bundle_id (or app key when no bundle id)
    activate_window = Signal(int)  # window_id

    def __init__(self) -> None:
        super().__init__()
        self._entries: list = []  # _AppEntry | _WindowEntry
        self._mode = "apps"  # "apps" | "windows"
        self._index = 0

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        self._container = QFrame()
        self._container.setObjectName("switcherBox")
        self._container.setStyleSheet(
            "#switcherBox{background:rgba(24,24,27,235);border-radius:14px;}"
        )

        self._strip_layout = QHBoxLayout(self._container)
        self._strip_layout.setContentsMargins(12, 12, 12, 12)
        self._strip_layout.setSpacing(8)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._container)

        self.hide()

    # ---- population ----

    def set_apps(self, entries: list[_AppEntry], select_index: int = 0) -> None:
        self._mode = "apps"
        self._entries = entries
        self._rebuild()
        self._select(min(select_index, max(0, len(entries) - 1)))

    def set_windows(self, entries: list[_WindowEntry], select_index: int = 0) -> None:
        self._mode = "windows"
        self._entries = entries
        self._rebuild()
        self._select(min(select_index, max(0, len(entries) - 1)))

    def _rebuild(self) -> None:
        while self._strip_layout.count():
            it = self._strip_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        for e in self._entries:
            if isinstance(e, _AppEntry):
                tile = _ItemWidget(e.icon_path, e.name)
            else:
                tile = _ItemWidget(e.icon_path, e.title or e.app_name)
            self._strip_layout.addWidget(tile)

    def _select(self, index: int) -> None:
        self._index = index
        for i in range(self._strip_layout.count()):
            w = self._strip_layout.itemAt(i).widget()
            if isinstance(w, _ItemWidget):
                w.set_selected(i == index)

    # ---- navigation ----

    def cycle(self, reverse: bool = False) -> None:
        n = len(self._entries)
        if n == 0:
            return
        if reverse:
            self._index = (self._index - 1) % n
        else:
            self._index = (self._index + 1) % n
        self._select(self._index)

    def commit(self) -> None:
        if not self._entries:
            self.hide()
            return
        e = self._entries[self._index]
        if self._mode == "apps" and isinstance(e, _AppEntry):
            self.activate_app.emit(e.bundle_id or e.key)
        elif isinstance(e, _WindowEntry):
            self.activate_window.emit(e.window_id)
        self.hide()

    # ---- show / hide ----

    def show_overlay(self) -> None:
        self.adjustSize()
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            sg = screen.availableGeometry()
            x = sg.center().x() - self.width() // 2
            y = int(sg.center().y() * 0.4) - self.height() // 2
            self.move(x, y)
        self.show()
        self.raise_()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Controller (implements SwitcherHandler)
# ---------------------------------------------------------------------------


class SwitcherController:
    """Drives the overlay for both the app switcher and window switcher.

    ``mode`` selects whether the overlay shows running apps (Alt+Tab) or the
    windows of the active app (Alt+`).
    """

    def __init__(
        self,
        window_provider: WindowProvider,
        app_provider: AppProvider,
        mru: MRUTracker,
        mode: str = "apps",
    ) -> None:
        self._wp = window_provider
        self._ap = app_provider
        self._mru = mru
        self._mode = mode
        self.overlay = SwitcherOverlay()
        self.overlay.activate_app.connect(self._on_activate_app)
        self.overlay.activate_window.connect(self._on_activate_window)

    # ---- build entries ----

    def _running_apps(self) -> list[_AppEntry]:
        windows = self._wp.list_windows()
        # Group by bundle_id (fallback app_name) to get distinct running apps.
        keys: dict[str, _AppEntry] = {}
        for w in windows:
            key = w.bundle_id or w.app_name
            if key in keys:
                continue
            icon = None
            if w.bundle_id:
                icon = self._ap.icon_for_bundle_id(w.bundle_id)
            keys[key] = _AppEntry(
                key=key,
                name=w.app_name,
                icon_path=icon,
                bundle_id=w.bundle_id,
            )
        all_keys = list(keys.values())
        ordered_keys = self._mru.order([e.key for e in all_keys])
        key_to_entry = {e.key: e for e in all_keys}
        return [key_to_entry[k] for k in ordered_keys if k in key_to_entry]

    def _app_windows(self) -> list[_WindowEntry]:
        bid = self._wp.frontmost_bundle_id()
        if not bid:
            return []
        wins = self._wp.list_app_windows(bid)
        icon = self._ap.icon_for_bundle_id(bid)
        out: list[_WindowEntry] = []
        seen: set[int] = set()
        for w in wins:
            if w.window_id in seen:
                continue
            seen.add(w.window_id)
            title = w.window_title or w.app_name
            out.append(
                _WindowEntry(
                    window_id=w.window_id,
                    title=title,
                    app_name=w.app_name,
                    icon_path=icon,
                    bundle_id=bid,
                )
            )
        return out

    # ---- SwitcherHandler interface ----

    def on_trigger(self) -> None:
        if self._mode == "apps":
            entries = self._running_apps()
            # Start on the *previous* app (index 1) when possible, since
            # index 0 is the current frontmost.
            start = 1 if len(entries) > 1 else 0
            self.overlay.set_apps(entries, select_index=start)
        else:
            entries = self._app_windows()
            self.overlay.set_windows(entries, select_index=0)
        self.overlay.show_overlay()

    def on_cycle(self, reverse: bool) -> None:
        self.overlay.cycle(reverse)

    def on_commit(self) -> None:
        self.overlay.commit()

    def on_cancel(self) -> None:
        self.overlay.hide()

    # ---- activation ----

    def _on_activate_app(self, key_or_bid: str) -> None:
        # ``key`` may be a bundle id (preferred) or an app name fallback.
        # Heuristic: if it looks like a bundle id (contains '.'), activate
        # by bundle id; otherwise scan running windows for a matching app.
        self._mru.touch(key_or_bid)
        if "." in key_or_bid:
            self._wp.activate_app(key_or_bid)
            return
        # Fallback: find a window whose app_name matches and raise its app.
        for w in self._wp.list_windows():
            if w.app_name == key_or_bid:
                if w.bundle_id:
                    self._wp.activate_app(w.bundle_id)
                else:
                    self._wp.activate_window(w.window_id)
                return

    def _on_activate_window(self, window_id: int) -> None:
        self._wp.activate_window(window_id)
