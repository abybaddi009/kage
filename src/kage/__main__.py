"""Kage entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Kage")
    app.setQuitOnLastWindowClosed(False)  # stay resident via tray

    from .core.app import KageApp

    return KageApp(app).start()


if __name__ == "__main__":
    raise SystemExit(main())
