"""Path helpers for Kage user data and config locations."""

from __future__ import annotations

import os
from pathlib import Path
from importlib import resources

APP_NAME = "kage"


def config_dir() -> Path:
    """Directory holding user config (e.g. ~/.config/kage)."""
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


def theme_preview_path(theme: str) -> Path | None:
    """Path to the bundled preview screenshot for a switcher theme."""
    names = {"default": "default.png", "window_previews": "thumbnails.png"}
    file_name = names.get(theme)
    if file_name is None:
        return None
    try:
        with resources.files("kage.assets").joinpath(file_name) as p:
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
    """Path to the bundled Kage logo, or None if unavailable.

    Resolves through ``importlib.resources`` so it works both in a
    source checkout and inside a PyInstaller-frozen app (where the file
    lives under ``sys._MEIPASS``). Falls back to the repo-level
    ``assets/logo.png`` when running from a development checkout that
    has not installed the package data.
    """
    try:
        with resources.files("kage.assets").joinpath("logo.png") as p:
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
