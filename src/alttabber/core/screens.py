"""Shared helper for picking which QScreen the launcher/switcher open on."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint
from PySide6.QtGui import QCursor, QGuiApplication, QScreen

if TYPE_CHECKING:
    from ..backends.base import WindowProvider


def target_screen(
    preference: str,
    current: QScreen | None = None,
    window_provider: "WindowProvider | None" = None,
) -> QScreen | None:
    """Return the screen to show a popup window on for ``preference``.

    ``"pointer"`` resolves to the screen under the mouse cursor. ``"active"``
    resolves to the screen containing the frontmost window (via
    ``window_provider.frontmost_window_center()``), since ``current`` --
    typically a long-hidden popup's last-known screen -- has no relationship
    to where the user is currently working. Falls back to ``current``, then
    the primary screen, when the preferred lookup is unavailable.
    """
    if preference == "pointer":
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is not None:
            return screen
    elif window_provider is not None:
        center = window_provider.frontmost_window_center()
        if center is not None:
            screen = QGuiApplication.screenAt(QPoint(int(center[0]), int(center[1])))
            if screen is not None:
                return screen
    if current is not None:
        return current
    return QGuiApplication.primaryScreen()
