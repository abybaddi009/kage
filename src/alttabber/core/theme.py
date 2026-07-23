"""Shared UI theme tokens, derived from the system palette.

Any window that draws its own chrome (rather than relying on native Qt
widget styling) should pull its colors from :class:`Tokens` instead of
hardcoding hex values, so every window in the app tracks the same accent
color and (where applicable) the same light/dark appearance.
"""

from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication


class Tokens:
    def __init__(self) -> None:
        pal = QApplication.palette()
        self.dark = pal.color(QPalette.Window).lightness() < 128
        self.accent = pal.color(QPalette.Highlight).name()
        self.accent_text = pal.color(QPalette.HighlightedText).name()
        if self.dark:
            self.card_bg = "rgba(255,255,255,6%)"
            self.card_border = "rgba(255,255,255,10%)"
            self.separator = "rgba(255,255,255,9%)"
            self.sidebar_bg = "rgba(0,0,0,14%)"
            self.hover = "rgba(255,255,255,8%)"
            self.hover_border = "rgba(255,255,255,25%)"
            self.muted = "#98989d"
        else:
            self.card_bg = "#ffffff"
            self.card_border = "rgba(0,0,0,8%)"
            self.separator = "rgba(0,0,0,8%)"
            self.sidebar_bg = "rgba(0,0,0,4%)"
            self.hover = "rgba(0,0,0,5%)"
            self.hover_border = "rgba(0,0,0,20%)"
            self.muted = "#6e6e73"


# ---------------------------------------------------------------------------
# Overlay chrome (launcher palette, switcher): a fixed dark, translucent
# "vibrant" surface in the style of macOS Spotlight / KDE krunner, used for
# frameless popup windows that float above everything else. These stay dark
# regardless of the system appearance -- the readable-content chrome (Qt
# native widgets, Settings) is what follows light/dark via ``Tokens`` above
# -- but they still pull their *accent* color from ``Tokens`` so selection
# highlights match the rest of the app instead of a hardcoded blue.
OVERLAY_BG = "rgba(24,24,27,242)"
OVERLAY_PANEL_BG = "rgba(24,24,27,235)"
OVERLAY_FIELD_BG = "rgba(255,255,255,10%)"
OVERLAY_FIELD_BORDER = "rgba(255,255,255,15%)"
OVERLAY_HOVER = "rgba(255,255,255,12%)"
OVERLAY_SEPARATOR = "rgba(255,255,255,10%)"
OVERLAY_TEXT = "#e5e7eb"
OVERLAY_MUTED = "#9ca3af"


# ---------------------------------------------------------------------------
# UI size tiers: multipliers applied to base tile/icon/text sizes in the
# launcher palette (src/alttabber/core/palette.py) and the switcher overlay
# (src/alttabber/core/switcher.py). "small" is the historical default sizing.
# Keep in sync with UI_SIZES in config.py.
UI_SIZE_SCALES = {
    "small": 1.0,
    "medium": 1.2,
    "large": 1.4,
}


def ui_scale(level: str) -> float:
    """Return the scale factor for a UI size tier (falls back to 1.0)."""
    return UI_SIZE_SCALES.get(level, 1.0)
