"""Shared pytest fixtures for the kage test suite.

PySide6 widgets require a running ``QApplication``. We create a single
session-scoped instance so tests don't each pay the startup cost and don't
conflict over the global ``qApp``.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
