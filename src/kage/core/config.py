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


@dataclass
class Config:
    hotkeys: HotkeyBindings = field(default_factory=HotkeyBindings)
    palette: PaletteConfig = field(default_factory=PaletteConfig)
    # If True, kage quits when the tray is removed rather than staying resident.
    quit_on_tray_close: bool = False


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

    if "quit_on_tray_close" in data:
        cfg.quit_on_tray_close = bool(data["quit_on_tray_close"])
    return cfg
