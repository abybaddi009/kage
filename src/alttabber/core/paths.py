"""Path helpers for Alt-Tabber user data and config locations."""

from __future__ import annotations

import os
from pathlib import Path
from importlib import resources

APP_NAME = "alttabber"


def config_dir() -> Path:
    """Directory holding user config (e.g. ~/.config/alttabber)."""
    env = os.environ.get("XDG_CONFIG_HOME")
    base = Path(env) if env else Path.home() / ".config"
    return base / APP_NAME


def config_file() -> Path:
    return config_dir() / "config.toml"


def data_dir() -> Path:
    """Directory for runtime data (cache, state)."""
    env = os.environ.get("XDG_DATA_HOME")
    base = Path(env) if env else Path.home() / ".local" / "share"
    return base / APP_NAME


def theme_preview_path(
    theme: str, expanded: bool = False, previews: bool = True
) -> Path | None:
    """Path to the bundled preview screenshot for a switcher theme.

    ``expanded`` selects the variant matching the "show every window as
    its own entry" setting, and ``previews`` the "show a live preview
    while switching" setting, so the settings theme cards can mirror both.
    ``previews`` only affects the "default" theme -- "window_previews"
    always shows a thumbnail per tile regardless of that setting.
    """
    if theme == "default" and not previews:
        file_name = (
            "default-expanded-no-preview.png" if expanded else "default-no-preview.png"
        )
    else:
        names = {
            ("default", False): "default.png",
            ("default", True): "default-expanded.png",
            ("window_previews", False): "thumbnails.png",
            ("window_previews", True): "thumbnails-expanded.png",
        }
        file_name = names.get((theme, expanded))
    if file_name is None:
        return None
    try:
        with resources.files("alttabber.assets").joinpath(file_name) as p:
            resolved = Path(str(p))
            if resolved.is_file():
                return resolved
    except (ModuleNotFoundError, FileNotFoundError, TypeError):
        pass
    here = Path(__file__).resolve()
    for parent in (here.parent.parent.parent, here.parent.parent.parent.parent):
        candidate = parent / "assets" / file_name
        if candidate.is_file():
            return candidate
    return None


def logo_path() -> Path | None:
    """Path to the bundled Alt-Tabber logo, or None if unavailable.

    Resolves through ``importlib.resources`` so it works both in a
    source checkout and inside a PyInstaller-frozen app (where the file
    lives under ``sys._MEIPASS``). Falls back to the repo-level
    ``assets/logo.png`` when running from a development checkout that
    has not installed the package data.
    """
    try:
        with resources.files("alttabber.assets").joinpath("logo.png") as p:
            resolved = Path(str(p))
            if resolved.is_file():
                return resolved
    except (ModuleNotFoundError, FileNotFoundError, TypeError):
        pass
    # Development fallback: repo-level assets directory.
    here = Path(__file__).resolve()
    for parent in (here.parent.parent.parent, here.parent.parent.parent.parent):
        candidate = parent / "assets" / "logo.png"
        if candidate.is_file():
            return candidate
    return None


def close_icon_path() -> Path | None:
    """Path to the bundled close-button icon, or None if unavailable.
    Resolves via ``importlib.resources`` (frozen app) with a repo-level
    ``assets/close.png`` fallback for development checkouts.
    """
    try:
        with resources.files("alttabber.assets").joinpath("close.png") as p:
            resolved = Path(str(p))
            if resolved.is_file():
                return resolved
    except (ModuleNotFoundError, FileNotFoundError, TypeError):
        pass
    here = Path(__file__).resolve()
    for parent in (here.parent.parent.parent, here.parent.parent.parent.parent):
        candidate = parent / "assets" / "close.png"
        if candidate.is_file():
            return candidate
    return None
