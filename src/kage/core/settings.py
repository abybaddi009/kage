"""Settings dialog: edit hotkey bindings and palette options from the tray.

Saves to ``config.toml`` and signals the app to reload. Chord strings are
free-form text; validation happens on reload via parse_chord (an invalid
chord shows a message but does not block saving).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QLineEdit,
)

from .config import Config, save_config


class SettingsDialog(QDialog):
    reloaded = Signal()

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kage Settings")
        self.setModal(True)
        self._config = config

        form = QFormLayout()

        hint = QLabel(
            "Chords use modifiers joined by '+': Super, Ctrl, Alt, Shift, Cmd.\n"
            "Examples: Super+A, Alt+Tab, Alt+`"
        )
        hint.setWordWrap(True)

        self._launcher = QLineEdit(config.hotkeys.launcher)
        self._app_switcher = QLineEdit(config.hotkeys.app_switcher)
        self._window_switcher = QLineEdit(config.hotkeys.window_switcher)
        form.addRow("Launcher hotkey", self._launcher)
        form.addRow("App switcher (Alt+Tab style)", self._app_switcher)
        form.addRow("Window switcher (per-app)", self._window_switcher)

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
