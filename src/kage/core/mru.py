"""Most-recently-used tracking of application activations.

Keeps an ordered list of app identifiers (bundle id when available, app name
otherwise) so the Alt+Tab switcher can present apps in usage order. The list
is persisted to ``data_dir/mru.json`` so ordering survives restarts.
"""

from __future__ import annotations

import json

from .paths import data_dir


class MRUTracker:
    def __init__(self, limit: int = 64) -> None:
        self._limit = limit
        self._items: list[str] = []
        self._path = data_dir() / "mru.json"
        self._load()

    def _load(self) -> None:
        try:
            data = self._path.read_text()
            items = json.loads(data)
            if isinstance(items, list):
                self._items = [str(x) for x in items][: self._limit]
        except Exception:
            self._items = []

    def _persist(self) -> None:
        try:
            self._path.write_text(json.dumps(self._items))
        except Exception:
            pass

    def touch(self, key: str) -> None:
        """Move ``key`` to the front of the MRU list."""
        if key in self._items:
            self._items.remove(key)
        self._items.insert(0, key)
        if len(self._items) > self._limit:
            self._items = self._items[: self._limit]
        self._persist()

    def order(self, keys: list[str]) -> list[str]:
        """Return ``keys`` ordered by MRU (most recent first).

        Keys not yet seen are appended after known ones, preserving their
        input order. The current frontmost app should be passed in so it
        ranks first.
        """
        known = [k for k in self._items if k in keys]
        extras = [k for k in keys if k not in self._items]
        return known + extras
