"""Fuzzy matcher that merges open windows and installed-but-unopened apps."""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from ..backends.base import AppInfo, WindowInfo
from .config import PaletteConfig


@dataclass
class Result:
    name: str  # display name (e.g. "Safari — GitHub")
    subtitle: str
    icon_path: str | None
    score: float
    is_window: bool
    window_id: int | None = None
    bundle_id: str | None = None
    bundle_path: str | None = None


def _window_text(w: WindowInfo) -> str:
    if w.window_title and w.window_title != w.app_name:
        return f"{w.app_name} {w.window_title}"
    return w.app_name


def _app_text(a: AppInfo) -> str:
    return a.name


def match(
    query: str,
    windows: list[WindowInfo],
    apps: list[AppInfo],
    cfg: PaletteConfig,
) -> list[Result]:
    q = query.strip().lower()
    open_bundle_ids = {
        w.bundle_id for w in windows if w.bundle_id
    }

    win_results: list[Result] = []
    app_results: list[Result] = []

    for w in windows:
        text = _window_text(w)
        score = fuzz.WRatio(q, text.lower()) if q else 0.0
        if q and score < 30:
            continue
        win_results.append(
            Result(
                name=w.window_title or w.app_name,
                subtitle=w.app_name + (" (minimized)" if w.is_minimized else ""),
                icon_path=None,
                score=score,
                is_window=True,
                window_id=w.window_id,
                bundle_id=w.bundle_id,
            )
        )

    for a in apps:
        # Exclude apps that already have an open window.
        if a.bundle_id and a.bundle_id in open_bundle_ids:
            continue
        text = _app_text(a)
        score = fuzz.WRatio(q, text.lower()) if q else 0.0
        if q and score < 30:
            continue
        app_results.append(
            Result(
                name=a.name,
                subtitle="Application",
                icon_path=a.icon_path,
                score=score,
                is_window=False,
                bundle_id=a.bundle_id,
                bundle_path=a.bundle_path,
            )
        )

    win_results.sort(key=lambda r: r.score, reverse=True)
    app_results.sort(key=lambda r: r.score, reverse=True)

    # When the user is actively searching, rank strictly by relevance so a
    # high-scoring unlaunched app (e.g. "Docker") isn't buried under
    # loosely-matching open windows. With no query, honor windows_first so
    # open windows stay on top during the default browse experience.
    if not q and cfg.windows_first:
        merged = win_results + app_results
    else:
        merged = sorted(
            win_results + app_results, key=lambda r: r.score, reverse=True
        )
    return merged[: cfg.max_results]
