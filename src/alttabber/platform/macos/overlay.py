"""macOS NSWindow level helpers for overlay visibility.

A Qt ``WindowStaysOnTopHint`` window sits at ``NSFloatingWindowLevel`` (3),
which is below macOS fullscreen apps. To appear above a fullscreen app two
things are needed:

1. Raise the NSWindow level to ``kCGPopUpMenuWindowLevel`` (101) or above.
2. Set the collection behavior so the window can appear on the fullscreen
   Space (``CanJoinAllSpaces | FullScreenAuxiliary``).

Without #2 the window is invisible even at a high level because it lives
on a different Space than the fullscreen app.
"""

from __future__ import annotations

import sys


def raise_above_fullscreen(widget) -> None:
    """Raise ``widget``'s NSWindow so it appears above fullscreen apps.

    No-op on non-macOS platforms or when the Cocoa bridge is unavailable.
    """
    if sys.platform != "darwin":
        return
    try:
        import objc  # type: ignore
        from AppKit import (  # type: ignore
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
        )
    except ImportError:
        return
    try:
        ns_view = objc.objc_object(c_void_p=int(widget.winId()))
        ns_window = ns_view.window()
        if ns_window is None:
            return
        # kCGPopUpMenuWindowLevel = 101 — above fullscreen (1000 uses a
        # separate Space mechanism; pop-up level appears over it).
        ns_window.setLevel_(101)
        ns_window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
    except Exception:
        pass
