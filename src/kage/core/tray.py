"""System tray icon for Kage.

Menu: About, Settings, Reload config, Quit.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


def _make_icon() -> QIcon:
    """The Kage tray icon, loaded from the bundled logo when available.

    Falls back to a drawn placeholder when the logo asset is missing
    (e.g. running from a checkout without the assets installed).
    """
    from .paths import logo_path

    logo = logo_path()
    if logo is not None:
        icon = QIcon(str(logo))
        if not icon.isNull():
            return icon
    # Placeholder fallback.
    pix = QPixmap(32, 32)
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
    about_clicked = Signal()
    settings_clicked = Signal()
    reload_clicked = Signal()
    quit_clicked = Signal()

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._tray = QSystemTrayIcon(_make_icon(), parent=app)
        self._tray.setToolTip("Kage")
        self._build_menu()
        self._tray.show()

    def _build_menu(self) -> None:
        menu = QMenu()

        act_about = QAction("About Kage", menu)
        act_about.triggered.connect(self.about_clicked.emit)
        menu.addAction(act_about)

        menu.addSeparator()

        act_settings = QAction("Settings…", menu)
        act_settings.triggered.connect(self.settings_clicked.emit)
        menu.addAction(act_settings)

        act_reload = QAction("Reload config", menu)
        act_reload.triggered.connect(self.reload_clicked.emit)
        menu.addAction(act_reload)

        menu.addSeparator()

        act_quit = QAction("Quit Kage", menu)
        act_quit.triggered.connect(self.quit_clicked.emit)
        menu.addAction(act_quit)

        self._tray.setContextMenu(menu)

    def show_message(self, title: str, body: str) -> None:
        self._tray.showMessage(title, body, QSystemTrayIcon.Information, 4000)
