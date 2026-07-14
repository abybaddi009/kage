"""Reliable window activation shared by the palette and switchers."""

from __future__ import annotations

from PySide6.QtCore import QTimer

from ..backends.base import WindowProvider

# Empirically determined on macOS (Sequoia, dual display, "Displays have
# separate Spaces"): once this process has shown its own overlay window, a
# single AX raise + kAXFocusedAttribute pass no longer moves key-window
# status to a *same-app* window on *another* display -- the app silently
# keeps its current key window. It fails even if the overlay is hidden
# first and even after a 600ms delay, but a second identical pass shortly
# after the first reliably lands (verified externally via System Events).
# The same call sequence from a process that never showed a window works
# first try, so this is an app-context quirk, not an AX-usage bug.
_RETRY_DELAY_MS = 400


def activate_window_reliably(window_provider: WindowProvider, window_id: int) -> bool:
    """Activate ``window_id`` now and re-assert it once shortly after."""
    ok = window_provider.activate_window(window_id)
    QTimer.singleShot(
        _RETRY_DELAY_MS, lambda: window_provider.activate_window(window_id)
    )
    return ok
