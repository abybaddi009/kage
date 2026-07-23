"""Palette window/app ordering must mirror the switcher's MRU recency.

The palette previously fed ``list_windows``/``list_apps`` to the matcher in
the provider's natural order, so its results and overview grid were ordered
differently from Alt+Tab. After wiring the shared ``MRUTracker`` and
``WindowMRUTracker`` into the palette, both surfaces use the same recency.
"""

from __future__ import annotations
from types import SimpleNamespace

from kage.backends.base import AppInfo, AppProvider, WindowInfo, WindowProvider

from kage.core.mru import MRUTracker, WindowMRUTracker
from kage.core.palette import PaletteWindow


class _FakeWindowProvider(WindowProvider):
    def __init__(self, windows: list[WindowInfo]) -> None:
        self._windows = windows

    def list_windows(self) -> list[WindowInfo]:
        return list(self._windows)

    def activate_window(self, window_id: int) -> bool:
        return True

    def activate_app(self, bundle_id: str) -> bool:
        return True

    def capture_preview(self, window_id: int) -> bytes | None:
        return None


class _FakeAppProvider(AppProvider):
    def __init__(self, apps: list[AppInfo]) -> None:
        self._apps = apps

    def list_apps(self) -> list[AppInfo]:
        return list(self._apps)

    def launch(self, bundle_path: str) -> bool:
        return True

    def icon_for_bundle_id(self, bundle_id: str) -> str | None:
        return None


def _config():
    return SimpleNamespace(
        ui_size="medium",
        screen_preference="active",
        palette=SimpleNamespace(
            max_results=50, overview_enabled=False, windows_first=True
        ),
    )


def _windows():
    # Provider order: Safari(10), Notes(11), Mail(12).
    return [
        WindowInfo("Safari", "A", 10, bundle_id="com.safari"),
        WindowInfo("Notes", "B", 11, bundle_id="com.notes"),
        WindowInfo("Mail", "C", 12, bundle_id="com.mail"),
    ]


def _apps():
    return [
        AppInfo("Terminal", "/A", bundle_id="com.term"),
        AppInfo("Vim", "/B", bundle_id="com.vim"),
    ]


def test_windows_ordered_by_per_window_mru(qapp):
    pal = PaletteWindow(_config())
    pal.set_providers(_FakeWindowProvider(_windows()), _FakeAppProvider(_apps()))

    wmru = WindowMRUTracker()
    # Touch Safari first (older), then Mail (most recent). Notes untouched.
    wmru.touch(10)
    wmru.touch(12)
    mru = MRUTracker()
    pal.set_mru(mru, wmru)

    pal._refresh("")

    assert [w.window_id for w in pal._all_windows] == [12, 10, 11]


def test_apps_ordered_by_app_mru(qapp):
    pal = PaletteWindow(_config())
    pal.set_providers(_FakeWindowProvider(_windows()), _FakeAppProvider(_apps()))

    mru = MRUTracker()
    mru.touch("com.vim")  # Vim more recent than Terminal
    pal.set_mru(mru, WindowMRUTracker())

    pal._refresh("")

    names = [pal._list.item(i).text() for i in range(pal._list.count())]
    app_names = [n for n in names if n in {"Terminal", "Vim"}]
    assert app_names == ["Vim", "Terminal"]


def test_results_order_mirrors_mru(qapp):
    pal = PaletteWindow(_config())
    pal.set_providers(_FakeWindowProvider(_windows()), _FakeAppProvider(_apps()))

    wmru = WindowMRUTracker()
    wmru.touch(10)
    wmru.touch(12)
    mru = MRUTracker()
    mru.touch("com.vim")
    pal.set_mru(mru, wmru)

    pal._refresh("")

    # No query + windows_first: windows in per-window MRU order (Mail, Safari,
    # Notes), then apps in app-MRU order (Vim, Terminal).
    names = [pal._list.item(i).text() for i in range(pal._list.count())]
    assert names == ["C", "A", "B", "Vim", "Terminal"]


def test_without_mru_falls_back_to_provider_order(qapp):
    pal = PaletteWindow(_config())
    pal.set_providers(_FakeWindowProvider(_windows()), _FakeAppProvider(_apps()))

    pal._refresh("")

    assert [w.window_id for w in pal._all_windows] == [10, 11, 12]
