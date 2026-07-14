"""Kage application: resident Qt app wiring config, tray, and platform checks."""

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QVBoxLayout

from .config import Config, load_config
from .mru import MRUTracker
from .tray import TrayController


class PermissionDialog(QDialog):
    """First-run prompt guiding the user to grant a required permission."""

    def __init__(self, title: str, message: str, open_settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._open_settings_cb = open_settings

        label = QLabel(message)
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
        self._open_settings_cb()


class KageApp(QObject):
    config_changed = Signal()

    def __init__(self, qt_app: QApplication) -> None:
        super().__init__()
        self.qt_app = qt_app
        self.config: Config = load_config()
        self._tray: TrayController | None = None
        self._palette: PaletteWindow | None = None
        self._window_provider = None
        self._app_provider = None
        self._hotkey_provider = None
        self._mru: MRUTracker | None = None
        self._app_switcher: SwitcherController | None = None
        self._window_switcher: SwitcherController | None = None

    def start(self) -> int:
        # Keep a hidden reference window so the app stays resident and can
        # present instant popups later (palette, switcher overlay).
        from PySide6.QtWidgets import QMainWindow

        self._hidden = QMainWindow()
        self._hidden.hide()

        # Permission checks (macOS): Accessibility for hotkeys/activation,
        # Screen Recording for window titles.
        if sys.platform == "darwin":
            from ..platform.macos import accessibility

            if not accessibility.is_trusted():
                accessibility.prompt()
                PermissionDialog(
                    "Kage needs Accessibility",
                    "Kage requires Accessibility permission to read the window list,\n"
                    "activate windows, and listen for hotkeys.\n\n"
                    "Open System Settings → Privacy & Security → Accessibility,\n"
                    "enable Kage (or your terminal), then restart Kage.",
                    accessibility.open_system_settings,
                ).exec()

            if not accessibility.screen_recording_trusted():
                accessibility.prompt_screen_recording()
                PermissionDialog(
                    "Kage needs Screen Recording",
                    "Kage requires Screen Recording permission to read window\n"
                    "titles (macOS hides them from other apps otherwise).\n\n"
                    "Open System Settings → Privacy & Security → Screen Recording,\n"
                    "enable Kage (or your terminal), then restart Kage.",
                    accessibility.open_screen_recording_settings,
                ).exec()

        # Build the pre-built palette window (hidden until the hotkey fires).
        self._build_palette()

        self._tray = TrayController(self.qt_app)
        self._tray.settings_clicked.connect(self._on_settings)
        self._tray.reload_clicked.connect(self._on_reload)
        self._tray.quit_clicked.connect(self.qt_app.quit)
        self._tray.launch_at_login_toggled.connect(self._on_launch_at_login)

        if not QSystemTrayIcon_isAvailable():
            print(
                "Warning: no system tray available; Kage will run headless.",
                file=sys.stderr,
            )
        else:
            # Reflect current launch-at-login state into the tray checkbox.
            self._sync_launch_at_login()

        return self.qt_app.exec()

    def _build_palette(self) -> None:
        from .palette import PaletteWindow

        self._palette = PaletteWindow(self.config)

        if sys.platform == "darwin":
            from ..platform.macos.apps import MacAppProvider
            from ..platform.macos.windows import MacWindowProvider
            from ..platform.macos.hotkeys import MacHotkeyProvider

            self._window_provider = MacWindowProvider()
            self._app_provider = MacAppProvider()
            self._hotkey_provider = MacHotkeyProvider()
        else:
            print(
                f"Warning: no platform backends for {sys.platform!r} yet.",
                file=sys.stderr,
            )
            return

        self._palette.set_providers(self._window_provider, self._app_provider)
        # Palette -> backend activation.
        self._palette.activate_window.connect(self._on_activate_window)
        self._palette.launch_app.connect(self._on_launch_app)
        self._palette.activate_app.connect(self._on_activate_app)

        # MRU tracking shared by palette + switchers.
        self._mru = MRUTracker()

        # Alt+Tab app switcher overlay.
        from .switcher import SwitcherController

        self._app_switcher = SwitcherController(
            self._window_provider, self._app_provider, self._mru,
            mode="apps", config=self.config,
        )
        self._hotkey_provider.register_switcher(
            self.config.hotkeys.app_switcher, self._app_switcher
        )

        # Alt+` per-app window switcher overlay (reuses the same UI filtered
        # to the frontmost app's windows via AXUIElement).
        self._window_switcher = SwitcherController(
            self._window_provider, self._app_provider, self._mru,
            mode="windows", config=self.config,
        )
        self._hotkey_provider.register_switcher(
            self.config.hotkeys.window_switcher, self._window_switcher
        )

        # Register the launcher hotkey.
        self._hotkey_provider.register(
            self.config.hotkeys.launcher, self._palette.show_palette
        )
        self._hotkey_provider.start()

    @Slot(int)
    def _on_activate_window(self, window_id: int) -> None:
        if self._window_provider is not None:
            from .activation import activate_window_reliably

            activate_window_reliably(self._window_provider, window_id)
            if self._mru is not None:
                for w in self._window_provider.list_windows():
                    if w.window_id == window_id:
                        self._mru.touch(w.bundle_id or w.app_name)
                        break

    @Slot(str)
    def _on_launch_app(self, bundle_path: str) -> None:
        if self._app_provider is not None:
            self._app_provider.launch(bundle_path)

    @Slot(str)
    def _on_activate_app(self, bundle_id: str) -> None:
        if self._window_provider is not None:
            self._window_provider.activate_app(bundle_id)
        if self._mru is not None:
            self._mru.touch(bundle_id)

    @Slot()
    def _on_settings(self) -> None:
        from .settings import SettingsDialog

        dlg = SettingsDialog(self.config, parent=self._hidden)
        dlg.reloaded.connect(self._on_reload)
        dlg.exec()

    def _sync_launch_at_login(self) -> None:
        if self._tray is None or sys.platform != "darwin":
            return
        try:
            from ..platform.macos import launch_at_login

            self._tray.set_launch_at_login_checked(launch_at_login.is_launch_at_login())
        except Exception:
            pass

    @Slot(bool)
    def _on_launch_at_login(self, enabled: bool) -> None:
        if sys.platform != "darwin":
            return
        try:
            from ..platform.macos import launch_at_login

            ok = launch_at_login.set_launch_at_login(enabled)
            self._tray.set_launch_at_login_checked(ok and enabled)
            if not ok and self._tray is not None:
                self._tray.show_message(
                    "Kage",
                    "Could not set launch-at-login. "
                    "This works best when Kage is packaged as an app.",
                )
        except Exception:
            pass

    @Slot()
    def _on_reload(self) -> None:
        old_launch = self.config.hotkeys.launcher
        old_switch = self.config.hotkeys.app_switcher
        old_win = self.config.hotkeys.window_switcher
        self.config = load_config()
        if self._hotkey_provider is not None and self._palette is not None:
            if self.config.hotkeys.launcher != old_launch:
                try:
                    self._hotkey_provider.unregister(old_launch)
                except Exception:
                    pass
                self._hotkey_provider.register(
                    self.config.hotkeys.launcher, self._palette.show_palette
                )
            if self.config.hotkeys.app_switcher != old_switch and self._app_switcher is not None:
                try:
                    self._hotkey_provider.unregister(old_switch)
                except Exception:
                    pass
                self._hotkey_provider.register_switcher(
                    self.config.hotkeys.app_switcher, self._app_switcher
                )
            if self.config.hotkeys.window_switcher != old_win and self._window_switcher is not None:
                try:
                    self._hotkey_provider.unregister(old_win)
                except Exception:
                    pass
                self._hotkey_provider.register_switcher(
                    self.config.hotkeys.window_switcher, self._window_switcher
                )
        self._palette.config = self.config if self._palette else None
        if self._app_switcher is not None:
            self._app_switcher.config = self.config
        if self._window_switcher is not None:
            self._window_switcher.config = self.config
        self.config_changed.emit()
        if self._tray is not None:
            self._tray.show_message("Kage", "Configuration reloaded.")


def QSystemTrayIcon_isAvailable() -> bool:
    from PySide6.QtWidgets import QSystemTrayIcon

    return QSystemTrayIcon.isSystemTrayAvailable()
