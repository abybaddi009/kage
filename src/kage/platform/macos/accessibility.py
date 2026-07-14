"""macOS Accessibility permission detection and first-run prompt.

The CGEventTap (hotkeys / modifier-release) and AXUIElement (window activation)
both require the process to be granted Accessibility permission in System
Settings -> Privacy & Security -> Accessibility.
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
