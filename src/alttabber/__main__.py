"""Alt-Tabber entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Alt-Tabber")
    app.setQuitOnLastWindowClosed(False)  # stay resident via tray

    from .core.app import AltTabberApp

    return AltTabberApp(app).start()


if __name__ == "__main__":
    raise SystemExit(main())
