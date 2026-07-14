"""System tray icon for Kage.

Menu: Settings (placeholder), Reload config, Quit.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


def _make_icon() -> QIcon:
    """A simple placeholder icon so the tray works without bundled assets."""
    pix = QPixmap(32, 32)
    pix.fill()
    from PySide6.QtGui import QColor, QPainter

    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setBrush(QColor("#3b82f6"))
    painter.setPen(QColor("#1d4ed8"))
    painter.drawEllipse(4, 4, 24, 24)
    painter.setPen(QColor("#ffffff"))
    font = painter.font()
    font.setPointSize(14)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pix.rect(), 0x84, "K")  # AlignCenter
    painter.end()
    return QIcon(pix)


class TrayController(QObject):
    settings_clicked = Signal()
    reload_clicked = Signal()
    quit_clicked = Signal()
    launch_at_login_toggled = Signal(bool)

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._tray = QSystemTrayIcon(_make_icon(), parent=app)
        self._tray.setToolTip("Kage")
        self._build_menu()
        self._tray.show()

    def _build_menu(self) -> None:
        menu = QMenu()

        act_settings = QAction("Settings…", menu)
        act_settings.triggered.connect(self.settings_clicked.emit)
        menu.addAction(act_settings)

        self._act_login = QAction("Launch at login", menu)
        self._act_login.setCheckable(True)
        self._act_login.toggled.connect(self.launch_at_login_toggled.emit)
        menu.addAction(self._act_login)

        menu.addSeparator()

        act_reload = QAction("Reload config", menu)
        act_reload.triggered.connect(self.reload_clicked.emit)
        menu.addAction(act_reload)

        act_quit = QAction("Quit Kage", menu)
        act_quit.triggered.connect(self.quit_clicked.emit)
        menu.addAction(act_quit)

        self._tray.setContextMenu(menu)

    def set_launch_at_login_checked(self, on: bool) -> None:
        # Block signals to avoid a feedback loop when reflecting platform state.
        self._act_login.blockSignals(True)
        self._act_login.setChecked(on)
        self._act_login.blockSignals(False)

    def show_message(self, title: str, body: str) -> None:
        self._tray.showMessage(title, body, QSystemTrayIcon.Information, 4000)
