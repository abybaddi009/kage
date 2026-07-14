"""Path helpers for Kage user data and config locations."""

from __future__ import annotations

import os
from pathlib import Path

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
