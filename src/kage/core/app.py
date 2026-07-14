"""Kage application: resident Qt app wiring config, tray, and platform checks."""

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QVBoxLayout

from .config import Config, load_config
from .tray import TrayController


class AccessibilityDialog(QDialog):
    """First-run prompt guiding the user to grant Accessibility."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kage needs Accessibility")
        self.setModal(True)

        msg = (
            "Kage requires Accessibility permission to read the window list,\n"
            "activate windows, and listen for hotkeys.\n\n"
            "Open System Settings → Privacy & Security → Accessibility,\n"
            "enable Kage (or your terminal), then restart Kage."
        )
        label = QLabel(msg)
        label.setWordWrap(True)

        open_btn = QPushButton("Open System Settings…")
        open_btn.clicked.connect(self._open_settings)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(open_btn)
        layout.addWidget(close_btn)

    @Slot()
    def _open_settings(self) -> None:
        from ..platform.macos import accessibility

        accessibility.open_system_settings()


class KageApp(QObject):
    config_changed = Signal()

    def __init__(self, qt_app: QApplication) -> None:
        super().__init__()
        self.qt_app = qt_app
        self.config: Config = load_config()
        self._tray: TrayController | None = None

    def start(self) -> int:
        # Keep a hidden reference window so the app stays resident and can
        # present instant popups later (palette, switcher overlay).
        from PySide6.QtWidgets import QMainWindow

        self._hidden = QMainWindow()
        self._hidden.hide()

        # Accessibility check (macOS).
        if sys.platform == "darwin":
            from ..platform.macos import accessibility

            if not accessibility.is_trusted():
                accessibility.prompt()
                AccessibilityDialog().exec()

        self._tray = TrayController(self.qt_app)
        self._tray.settings_clicked.connect(self._on_settings)
        self._tray.reload_clicked.connect(self._on_reload)
        self._tray.quit_clicked.connect(self.qt_app.quit)

        if not QSystemTrayIcon_isAvailable():
            print(
                "Warning: no system tray available; Kage will run headless.",
                file=sys.stderr,
            )

        return self.qt_app.exec()

    @Slot()
    def _on_settings(self) -> None:
        # Placeholder until the Settings UI is built in Phase 4.
        if self._tray is not None:
            self._tray.show_message("Kage", "Settings UI coming soon.")

    @Slot()
    def _on_reload(self) -> None:
        self.config = load_config()
        self.config_changed.emit()
        if self._tray is not None:
            self._tray.show_message("Kage", "Configuration reloaded.")


def QSystemTrayIcon_isAvailable() -> bool:
    from PySide6.QtWidgets import QSystemTrayIcon

    return QSystemTrayIcon.isSystemTrayAvailable()
