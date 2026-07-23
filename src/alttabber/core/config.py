"""Configuration loader: defaults merged with user config.toml override.

Shortcut bindings live here from day one so that platform hotkey providers can
read them uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - py<3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]

from .paths import config_file


@dataclass
class HotkeyBindings:
    # Chord strings use a portable notation: modifiers joined by '+'.
    # Modifiers: Super, Ctrl, Alt (Option), Shift, Cmd (macOS command).
    # On macOS Alt == Option; the literal key follows the modifier list.
    launcher: str = "Super+A"
    app_switcher: str = "Alt+Tab"
    window_switcher: str = "Alt+`"


@dataclass
class PaletteConfig:
    # Maximum results shown in the launcher palette.
    max_results: int = 12
    # Open windows are ranked above unopened apps regardless of score.
    windows_first: bool = True
    # Show a KDE-style grid of live window thumbnails below the palette
    # results. Typing filters both the result list and the thumbnail grid.
    overview_enabled: bool = True
    # Maximum thumbnail tiles per row in the overview grid.
    overview_columns: int = 4


SWITCHER_THEMES = ("default", "window_previews")


@dataclass
class SwitcherConfig:
    # Alt+Tab lists every window of every app as its own flat entry (with
    # real titles) instead of grouping by app. When False (default), Alt+Tab
    # shows one entry per app and Alt+` drills into that app's windows.
    expand_windows: bool = False
    # Show a live thumbnail of the currently-selected window/app while
    # cycling in the Alt+Tab / Alt+` overlay.
    show_previews: bool = True
    # Visual theme for the switcher overlay. "default": icon tiles plus one
    # large preview of the current selection. "window_previews": every
    # visible window is its own tile showing its own screenshot with the
    # title below (implies showing every window, not grouped by app).
    theme: str = "default"


SCREEN_PREFERENCES = ("active", "pointer")

# UI size tiers: scale tile/icon/text size in the launcher palette and
# switcher overlay. See src/alttabber/core/theme.py:UI_SIZE_SCALES.
UI_SIZES = ("small", "medium", "large")


@dataclass
class Config:
    hotkeys: HotkeyBindings = field(default_factory=HotkeyBindings)
    palette: PaletteConfig = field(default_factory=PaletteConfig)
    switcher: SwitcherConfig = field(default_factory=SwitcherConfig)
    # If True, alttabber quits when the tray is removed rather than staying resident.
    quit_on_tray_close: bool = False
    # Which screen the launcher palette and switcher overlay open on: "active"
    # (the screen the window last occupied, falling back to the primary
    # screen) or "pointer" (the screen currently under the mouse cursor).
    screen_preference: str = "active"
    # UI size tier: scales tile/icon/text size in the palette overview grid
    # and the Alt-Tab switcher. One of UI_SIZES.
    ui_size: str = "small"


def load_config(path: Path | None = None) -> Config:
    """Load configuration: start from defaults, overlay user config.toml."""
    cfg = Config()
    path = path or config_file()
    if not path.exists():
        return cfg
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return _merge(cfg, data)


def _merge(cfg: Config, data: dict) -> Config:
    hk = data.get("hotkeys")
    if isinstance(hk, dict):
        if "launcher" in hk:
            cfg.hotkeys.launcher = str(hk["launcher"])
        if "app_switcher" in hk:
            cfg.hotkeys.app_switcher = str(hk["app_switcher"])
        if "window_switcher" in hk:
            cfg.hotkeys.window_switcher = str(hk["window_switcher"])

    pal = data.get("palette")
    if isinstance(pal, dict):
        if "max_results" in pal:
            cfg.palette.max_results = int(pal["max_results"])
        if "windows_first" in pal:
            cfg.palette.windows_first = bool(pal["windows_first"])
        if "overview_enabled" in pal:
            cfg.palette.overview_enabled = bool(pal["overview_enabled"])
        if "overview_columns" in pal:
            cfg.palette.overview_columns = int(pal["overview_columns"])

    sw = data.get("switcher")
    if isinstance(sw, dict):
        if "expand_windows" in sw:
            cfg.switcher.expand_windows = bool(sw["expand_windows"])
        if "show_previews" in sw:
            cfg.switcher.show_previews = bool(sw["show_previews"])
        if "theme" in sw and str(sw["theme"]) in SWITCHER_THEMES:
            cfg.switcher.theme = str(sw["theme"])

    if "quit_on_tray_close" in data:
        cfg.quit_on_tray_close = bool(data["quit_on_tray_close"])

    if "screen_preference" in data and str(data["screen_preference"]) in SCREEN_PREFERENCES:
        cfg.screen_preference = str(data["screen_preference"])
    if "ui_size" in data and str(data["ui_size"]) in UI_SIZES:
        cfg.ui_size = str(data["ui_size"])
    return cfg


def save_config(cfg: Config, path: Path | None = None) -> None:
    """Write ``cfg`` to ``config.toml`` (creating the directory)."""
    path = path or config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Alt-Tabber configuration. Edit and use Reload config from the tray.",
        "",
        f"quit_on_tray_close = {'true' if cfg.quit_on_tray_close else 'false'}",
        f'screen_preference = {_toml_str(cfg.screen_preference)}',
        f'ui_size = {_toml_str(cfg.ui_size)}',
        "",
        "[hotkeys]",
        f'launcher = {_toml_str(cfg.hotkeys.launcher)}',
        f'app_switcher = {_toml_str(cfg.hotkeys.app_switcher)}',
        f'window_switcher = {_toml_str(cfg.hotkeys.window_switcher)}',
        "",
        "[palette]",
        f"max_results = {int(cfg.palette.max_results)}",
        f"windows_first = {'true' if cfg.palette.windows_first else 'false'}",
        f"overview_enabled = {'true' if cfg.palette.overview_enabled else 'false'}",
        f"overview_columns = {int(cfg.palette.overview_columns)}",
        "",
        "[switcher]",
        f"expand_windows = {'true' if cfg.switcher.expand_windows else 'false'}",
        f"show_previews = {'true' if cfg.switcher.show_previews else 'false'}",
        f'theme = {_toml_str(cfg.switcher.theme)}',
        "",
    ]
    path.write_text("\n".join(lines))


def _toml_str(s: str) -> str:
    """Quote a string for TOML (basic strings, escaping backslashes)."""
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
