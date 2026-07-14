"""macOS Accessibility and Screen Recording permission detection + first-run prompt.

The CGEventTap (hotkeys / modifier-release) and AXUIElement (window activation)
both require Accessibility permission (System Settings -> Privacy & Security ->
Accessibility). Separately, since macOS 10.15, reading window *titles* via
CGWindowListCopyWindowInfo requires Screen Recording permission (System Settings
-> Privacy & Security -> Screen Recording) -- without it, kCGWindowName comes
back nil for every window owned by another process, even with Accessibility
granted.
"""

from __future__ import annotations

import subprocess
import sys


def _import_api_options():
    """Return (API Options, NSWorkspace, NSRunningApplication) or None."""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions  # type: ignore
        from Cocoa import NSURL  # type: ignore
    except ImportError:
        return None
    return AXIsProcessTrustedWithOptions, NSURL


def is_trusted() -> bool:
    """True if this process already has Accessibility permission."""
    apis = _import_api_options()
    if apis is None:
        return False
    AXIsProcessTrustedWithOptions, _ = apis
    try:
        from ApplicationServices import kAXTrustedCheckOptionPrompt  # type: ignore
        opts = {kAXTrustedCheckOptionPrompt: False}
        return bool(AXIsProcessTrustedWithOptions(opts))
    except Exception:
        # Fallback: non-options API
        try:
            from ApplicationServices import AXIsProcessTrusted  # type: ignore
            return bool(AXIsProcessTrusted())
        except Exception:
            return False


def prompt() -> bool:
    """Trigger the system Accessibility prompt (non-blocking).

    Returns True if already trusted, False otherwise (the system will show
    the prompt UI and the user must toggle the switch and restart kage).
    """
    apis = _import_api_options()
    if apis is None:
        return False
    AXIsProcessTrustedWithOptions, _ = apis
    try:
        from ApplicationServices import kAXTrustedCheckOptionPrompt  # type: ignore
        opts = {kAXTrustedCheckOptionPrompt: True}
        return bool(AXIsProcessTrustedWithOptions(opts))
    except Exception:
        return False


def open_system_settings() -> None:
    """Open System Settings -> Privacy & Security -> Accessibility."""
    # macOS 13+: use the x-apple-asset URL
    url = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
    try:
        subprocess.Popen(["open", url])
    except FileNotFoundError:
        print(f"Open manually: {url}", file=sys.stderr)


def screen_recording_trusted() -> bool:
    """True if this process already has Screen Recording permission.

    Needed to read window titles (kCGWindowName) for windows owned by other
    processes; without it CGWindowListCopyWindowInfo returns nil titles.
    """
    try:
        from Quartz import CGPreflightScreenCaptureAccess  # type: ignore
    except ImportError:
        return False
    try:
        return bool(CGPreflightScreenCaptureAccess())
    except Exception:
        return False


def prompt_screen_recording() -> bool:
    """Trigger the system Screen Recording prompt (non-blocking).

    Returns True if already trusted. Otherwise the system shows its own
    prompt; the user must toggle the switch and restart Kage (macOS does not
    let an app self-refresh this grant without a relaunch).
    """
    try:
        from Quartz import (  # type: ignore
            CGPreflightScreenCaptureAccess,
            CGRequestScreenCaptureAccess,
        )
    except ImportError:
        return False
    try:
        if CGPreflightScreenCaptureAccess():
            return True
        CGRequestScreenCaptureAccess()
        return False
    except Exception:
        return False


def open_screen_recording_settings() -> None:
    """Open System Settings -> Privacy & Security -> Screen Recording."""
    url = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
    try:
        subprocess.Popen(["open", url])
    except FileNotFoundError:
        print(f"Open manually: {url}", file=sys.stderr)
