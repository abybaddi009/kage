"""Launcher palette: frameless, centered, pre-built hidden window.

Text field + result list with icons. Shown by the global hotkey; Enter
activates the selected result (window or app); Esc hides.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..backends.base import AppProvider, WindowProvider
from .config import Config
from .matcher import Result, match
from .sources import load_sources


class PaletteWindow(QWidget):
    activate_window = Signal(int)  # window_id
    launch_app = Signal(str)        # bundle_path
    activate_app = Signal(str)     # bundle_id

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self._results: list[Result] = []
        self._window_provider: WindowProvider | None = None
        self._app_provider: AppProvider | None = None
        self._sources: list = load_sources()

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setFixedWidth(560)

        self._field = QLineEdit()
        self._field.setPlaceholderText("Search windows and applications…")
        self._field.setClearButtonEnabled(True)
        self._field.textChanged.connect(self._refresh)
        self._field.returnPressed.connect(self._activate_selected)
        self._field.textChanged.connect(self._reset_selection)

        self._list = QListWidget()
        self._list.setFocusPolicy(Qt.NoFocus)
        self._list.setUniformItemSizes(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        layout.addWidget(self._field)
        layout.addWidget(self._list)

        self._list.installEventFilter(self)

        self.hide()

    def set_providers(
        self,
        window_provider: WindowProvider,
        app_provider: AppProvider,
    ) -> None:
        self._window_provider = window_provider
        self._app_provider = app_provider

    # ---- show / hide ----

    def show_palette(self) -> None:
        self._field.clear()
        self._refresh("")
        self.adjustSize()
        screen = self.screen() if hasattr(self, "screen") else None
        if screen is None:
            from PySide6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()
        if screen is not None:
            sg = screen.availableGeometry()
            x = sg.center().x() - self.width() // 2
            y = int(sg.center().y() * 0.35) - self.height() // 2
            self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self._field.setFocus()

    def hide_palette(self) -> None:
        self.hide()

    # ---- events ----

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent

        if obj is self._list and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Escape:
                self.hide_palette()
                return True
            if key in (Qt.Key_Up, Qt.Key_Down):
                row = self._list.currentRow()
                n = self._list.count()
                if key == Qt.Key_Up:
                    row = row - 1 if row > 0 else n - 1
                else:
                    row = row + 1 if row < n - 1 else 0
                self._list.setCurrentRow(row)
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide_palette()
            return
        super().keyPressEvent(event)

    def _reset_selection(self, _text: str) -> None:
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    # ---- refresh ----

    def _refresh(self, text: str) -> None:
        if self._window_provider is None or self._app_provider is None:
            return
        try:
            windows = self._window_provider.list_windows()
            apps = self._app_provider.list_apps()
        except Exception:
            return
        self._results = match(text, windows, apps, self.config.palette)
        # Merge plugin result sources.
        for src in self._sources:
            try:
                self._results.extend(src.search(text))
            except Exception:
                continue
        self._results = self._results[: self.config.palette.max_results]
        self._list.clear()
        for r in self._results:
            item = QListWidgetItem(r.name)
            item.setToolTip(r.subtitle)
            if r.icon_path:
                pix = QPixmap(r.icon_path)
                if not pix.isNull():
                    item.setIcon(QIcon(pix))
            item.setData(Qt.UserRole, r.name)
            self._list.addItem(item)
        if self._results:
            self._list.setCurrentRow(0)

    def _activate_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._results):
            return
        r = self._results[row]
        if r.is_window and r.window_id is not None:
            self.activate_window.emit(r.window_id)
        elif r.bundle_id and not r.bundle_path:
            self.activate_app.emit(r.bundle_id)
        elif r.bundle_path:
            self.launch_app.emit(r.bundle_path)
        self.hide_palette()
