"""macOS NSWindow level helpers for overlay visibility.

A Qt ``WindowStaysOnTopHint`` window sits at ``NSFloatingWindowLevel`` (3),
which is below macOS fullscreen apps. To appear above a fullscreen app two
things are needed:

1. Raise the NSWindow level to ``kCGPopUpMenuWindowLevel`` (101) or above.
2. Set the collection behavior so the window can appear on the fullscreen
   Space (``CanJoinAllSpaces | FullScreenAuxiliary``).

Without #2 the window is invisible even at a high level because it lives
on a different Space than the fullscreen app. Without #1 it lives on the
fullscreen Space but *below* the fullscreen window, so it still never shows.

These two steps run at different points in the show sequence, hence two
functions:

* :func:`prepare_for_fullscreen` sets the collection behavior and must run
  *before* ``move()``/``show()`` -- flipping ``CanJoinAllSpaces`` on an
  already-positioned window makes AppKit snap it onto the current main
  screen, discarding the frame that was set.
* :func:`raise_to_overlay_level` sets the window level and must run *after*
  ``show()`` -- Qt re-derives the NSWindow level from the widget's window
  flags on every ``show()`` (``WindowStaysOnTopHint`` -> floating level 3),
  so a level set beforehand is silently overwritten by the show. Setting it
  afterwards is what actually lifts the overlay above fullscreen content.
"""

from __future__ import annotations

import os
import sys

# kCGPopUpMenuWindowLevel -- above a fullscreen app's window (which sits at
# the normal level within its own Space) but below the screen-saver level.
_OVERLAY_WINDOW_LEVEL = 101

# Set ALTTABBER_DEBUG_SCREEN=1 in the environment to print, on every call,
# whether a fullscreen app was detected and whether the NSWindow level/
# collection-behavior escalation actually applied -- see core/screens.py
# for the matching screen-selection diagnostics.
_DEBUG = os.environ.get("ALTTABBER_DEBUG_SCREEN") == "1"


def _dbg(msg: str) -> None:
    if _DEBUG:
        print(f"[alttabber overlay] {msg}", file=sys.stderr)


def _frontmost_app_is_fullscreen() -> bool:
    """Whether the frontmost app's focused window is in native fullscreen.

    Used to gate the collection-behavior/level escalation below so it only
    ever touches the window on the (common) plain-desktop case -- no
    fullscreen app anywhere, including single-monitor setups, where the
    override isn't needed and risks interfering with normal window-server
    placement.
    """
    try:
        from ApplicationServices import (  # type: ignore
            AXUIElementCreateApplication,
            AXUIElementCopyAttributeValue,
            kAXFocusedWindowAttribute,
        )
        from Cocoa import NSWorkspace  # type: ignore
    except ImportError:
        _dbg("fullscreen check: Cocoa/ApplicationServices import failed")
        return False
    # "AXFullScreen" is passed as a literal string rather than importing
    # kAXFullScreenAttribute -- that constant isn't exported by pyobjc's
    # ApplicationServices bindings (unlike the older/common AX attributes
    # above), and AX attribute names are just NSString identifiers, so the
    # literal works identically to the (unavailable) constant.
    ax_fullscreen_attr = "AXFullScreen"
    try:
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front is None:
            _dbg("fullscreen check: no frontmost application")
            return False
        name = str(front.localizedName()) if front.localizedName() else "?"
        pid = int(front.processIdentifier())
        app_el = AXUIElementCreateApplication(pid)
        err, win = AXUIElementCopyAttributeValue(app_el, kAXFocusedWindowAttribute, None)
        if err != 0 or win is None:
            _dbg(f"fullscreen check: {name} (pid {pid}) no focused window (err={err})")
            return False
        err, fullscreen = AXUIElementCopyAttributeValue(win, ax_fullscreen_attr, None)
        if err != 0:
            _dbg(f"fullscreen check: {name} (pid {pid}) kAXFullScreenAttribute err={err}")
            return False
        _dbg(f"fullscreen check: {name} (pid {pid}) fullscreen={bool(fullscreen)}")
        return bool(fullscreen)
    except Exception as e:
        _dbg(f"fullscreen check: exception {e!r}")
        return False


def _ns_window(widget):
    """Return the NSWindow backing ``widget``, or None if unavailable."""
    try:
        import objc  # type: ignore

        ns_view = objc.objc_object(c_void_p=int(widget.winId()))
        return ns_view.window()
    except Exception as e:
        _dbg(f"_ns_window: exception {e!r}")
        return None


def prepare_for_fullscreen(widget) -> bool:
    """Set ``widget``'s collection behavior so it can live on a fullscreen Space.

    Returns ``True`` if a fullscreen app was detected and the behavior was
    applied (in which case the caller must also call
    :func:`raise_to_overlay_level` after ``show()``), ``False`` otherwise --
    a no-op on non-macOS, when the Cocoa bridge is unavailable, or when no
    app is currently in native fullscreen (the ordinary case, incl.
    single-monitor, where the escalation isn't needed and could interfere
    with normal display).

    Must run *before* ``move()``/``show()``: flipping ``CanJoinAllSpaces``
    on an already-positioned NSWindow makes AppKit snap it onto the current
    main screen, ignoring the frame set beforehand.
    """
    if sys.platform != "darwin":
        return False
    if not _frontmost_app_is_fullscreen():
        _dbg("prepare_for_fullscreen: skipped (no fullscreen app detected)")
        return False
    try:
        from AppKit import (  # type: ignore
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowCollectionBehaviorMoveToActiveSpace,
            NSWindowStyleMaskNonactivatingPanel,
        )
    except ImportError:
        _dbg("prepare_for_fullscreen: AppKit import failed")
        return False
    ns_window = _ns_window(widget)
    if ns_window is None:
        _dbg("prepare_for_fullscreen: widget has no NSWindow")
        return False
    try:
        # THE decisive bit for showing over a foreign app's fullscreen Space:
        # the panel's styleMask must be NSWindowStyleMaskNonactivatingPanel
        # (0x80). Qt gives a Qt.Tool panel a titled-family mask
        # (closable|miniaturizable|resizable); with that mask the WindowServer
        # refuses to composite the window onto another app's fullscreen Space
        # no matter the level/collectionBehavior. Switching to the
        # non-activating-panel mask -- which is what a bare NSPanel built for
        # this uses -- is what actually makes it appear. Set before show; it
        # persists across later shows, and is benign off fullscreen (the
        # overlays are frameless and sized programmatically, so dropping the
        # resizable/closable bits changes nothing visible).
        ns_window.setStyleMask_(NSWindowStyleMaskNonactivatingPanel)
        # To show over another app's native-fullscreen Space, collectionBehavior
        # must be CanJoinAllSpaces *alone*. FullScreenAuxiliary is for a window
        # accompanying its OWN app's fullscreen window; OR-ing it in alongside
        # CanJoinAllSpaces stops the panel appearing over a *foreign* app's
        # fullscreen Space (the bug we hit). MoveToActiveSpace must also be
        # cleared -- Qt sets it by default and AppKit refuses to combine it with
        # CanJoinAllSpaces (raises NSInternalInconsistencyException). Everything
        # else Qt set is preserved.
        existing = ns_window.collectionBehavior()
        ns_window.setCollectionBehavior_(
            (
                existing
                & ~NSWindowCollectionBehaviorMoveToActiveSpace
                & ~NSWindowCollectionBehaviorFullScreenAuxiliary
            )
            | NSWindowCollectionBehaviorCanJoinAllSpaces
        )
        # Qt.Tool windows are backed by an NSPanel. A *floating, non-activating*
        # panel that keeps itself out of hide-on-deactivate is how an accessory
        # app (no dock icon, never the active app) shows a key panel over a
        # fullscreen Space without activating itself. Guarded by
        # respondsToSelector so a plain NSWindow backing is simply skipped.
        floating = False
        if ns_window.respondsToSelector_(b"setFloatingPanel:"):
            ns_window.setFloatingPanel_(True)
            floating = True
        if ns_window.respondsToSelector_(b"setHidesOnDeactivate:"):
            ns_window.setHidesOnDeactivate_(False)
        _dbg(
            f"prepare_for_fullscreen: styleMask={ns_window.styleMask()} "
            f"collectionBehavior={existing}->{ns_window.collectionBehavior()} "
            f"floatingPanel={floating}"
        )
        return True
    except Exception as e:
        _dbg(f"prepare_for_fullscreen: exception {e!r}")
        return False


def raise_to_overlay_level(widget) -> None:
    """Raise ``widget``'s NSWindow above fullscreen content.

    Must run *after* ``show()``/``raise_()``: Qt re-derives the NSWindow
    level from the widget's window flags during ``show()``
    (``WindowStaysOnTopHint`` -> ``NSFloatingWindowLevel`` == 3, which is
    below a fullscreen app), so a level set before the show is silently
    overwritten. Call this only when :func:`prepare_for_fullscreen` returned
    ``True`` (i.e. a fullscreen app is present).
    """
    if sys.platform != "darwin":
        return
    ns_window = _ns_window(widget)
    if ns_window is None:
        _dbg("raise_to_overlay_level: widget has no NSWindow")
        return
    try:
        from AppKit import NSApplication  # type: ignore
    except ImportError:
        _dbg("raise_to_overlay_level: AppKit import failed")
        return
    try:
        before = ns_window.level()
        ns_window.setLevel_(_OVERLAY_WINDOW_LEVEL)
        # Activating the app is the piece that actually gets a background/
        # accessory app's CanJoinAllSpaces window composited onto another app's
        # current fullscreen Space -- level + collection behavior + key status
        # alone left the panel stuck on the underlying desktop Space (visible
        # only after manually leaving fullscreen). activateIgnoringOtherApps_
        # pulls this app (and thus the panel) onto the frontmost Space.
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        # makeKeyAndOrderFront: on a floating non-activating panel this makes
        # the panel key so it takes keyboard focus, without needing a dock icon.
        ns_window.makeKeyAndOrderFront_(None)
        _dbg(
            f"raise_to_overlay_level: level {before}->{ns_window.level()} "
            f"(target {_OVERLAY_WINDOW_LEVEL}), activated app, made key and ordered front"
        )
    except Exception as e:
        _dbg(f"raise_to_overlay_level: exception {e!r}")
