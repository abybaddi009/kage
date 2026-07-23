"""Shared helper for picking which QScreen the launcher/switcher open on."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint
from PySide6.QtGui import QCursor, QGuiApplication, QScreen

if TYPE_CHECKING:
    from ..backends.base import WindowProvider

# Set ALTTABBER_DEBUG_SCREEN=1 in the environment to print, on every call,
# which branch of the lookup below fired and what it resolved to -- useful
# for diagnosing multi-monitor placement issues that can't be reproduced
# outside the user's actual hardware/Space configuration.
_DEBUG = os.environ.get("ALTTABBER_DEBUG_SCREEN") == "1"


def _dbg(msg: str) -> None:
    if _DEBUG:
        print(f"[alttabber screen] {msg}", file=sys.stderr)


def _screen_desc(screen: QScreen | None) -> str:
    if screen is None:
        return "None"
    g = screen.geometry()
    return f"{screen.name()!r} geom={g.x()},{g.y()} {g.width()}x{g.height()}"


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
    _dbg(f"preference={preference!r} current={_screen_desc(current)}")
    if preference == "pointer":
        pos = QCursor.pos()
        screen = QGuiApplication.screenAt(pos)
        _dbg(f"pointer branch: cursor={pos.x()},{pos.y()} -> {_screen_desc(screen)}")
        if screen is not None:
            return screen
    elif window_provider is not None:
        center = window_provider.frontmost_window_center()
        _dbg(f"active branch: frontmost_window_center()={center}")
        if center is not None:
            screen = QGuiApplication.screenAt(QPoint(int(center[0]), int(center[1])))
            _dbg(f"active branch: screenAt(center)={_screen_desc(screen)}")
            if screen is not None:
                return screen
    # Frontmost window not found (e.g. app in macOS native fullscreen on a
    # separate Space): fall back to the pointer position — the most reliable
    # indicator of where the user is working — before the stale ``current``
    # screen or the primary screen.
    pos = QCursor.pos()
    screen = QGuiApplication.screenAt(pos)
    _dbg(f"fallback: cursor={pos.x()},{pos.y()} -> {_screen_desc(screen)}")
    if screen is not None:
        return screen
    if current is not None:
        _dbg(f"fallback: using current={_screen_desc(current)}")
        return current
    screen = QGuiApplication.primaryScreen()
    _dbg(f"fallback: using primaryScreen={_screen_desc(screen)}")
    return screen
