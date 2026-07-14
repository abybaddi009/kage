"""Abstract platform backend interfaces.

The core never imports platform modules directly; it only talks to these
interfaces. Each platform (macos/, wayland/, ...) supplies concrete
implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class WindowInfo:
    app_name: str
    window_title: str
    window_id: int  # platform-specific id (CGWindowID on macOS)
    bundle_id: str | None = None
    pid: int | None = None
    is_minimized: bool = False


@dataclass
class AppInfo:
    name: str
    bundle_path: str
    bundle_id: str | None = None
    icon_path: str | None = None  # path to an icon image usable by Qt


class WindowProvider(ABC):
    @abstractmethod
    def list_windows(self) -> list[WindowInfo]:
        """Return all open windows (across Spaces)."""

    @abstractmethod
    def activate_window(self, window_id: int) -> bool:
        """Bring a specific window to the front. Return success."""

    @abstractmethod
    def activate_app(self, bundle_id: str) -> bool:
        """Activate the frontmost window of an app by bundle id."""

    def frontmost_bundle_id(self) -> str | None:
        """Return the bundle id of the currently frontmost application.

        Concrete backends should override; the default returns None so
        callers can degrade gracefully.
        """
        return None

    def list_app_windows(self, bundle_id: str) -> list[WindowInfo]:
        """Return windows belonging to a single application.

        Default implementation filters ``list_windows`` by bundle id (or
        app name when bundle id is unavailable). Backends with richer
        per-app enumeration (e.g. AXUIElement on macOS) should override.
        """
        out: list[WindowInfo] = []
        for w in self.list_windows():
            if (w.bundle_id and w.bundle_id == bundle_id) or (
                not w.bundle_id and not bundle_id
            ):
                out.append(w)
        return out


class AppProvider(ABC):
    @abstractmethod
    def list_apps(self) -> list[AppInfo]:
        """Enumerate installed applications."""

    @abstractmethod
    def launch(self, bundle_path: str) -> bool:
        """Launch an application by bundle path. Return success."""

    def icon_for_bundle_id(self, bundle_id: str) -> str | None:
        """Return a cached icon path for ``bundle_id`` or None.

        Default scans ``list_apps``; backends may override for speed.
        """
        for app in self.list_apps():
            if app.bundle_id == bundle_id:
                return app.icon_path
        return None


class SwitcherHandler(ABC):
    """Callback interface for hold-to-cycle hotkeys (Alt+Tab style).

    The HotkeyProvider calls these in response to raw key/modifier events
    while the switcher chord is active. Implementations drive the switcher
    overlay and activation logic.
    """

    @abstractmethod
    def on_trigger(self) -> None:
        """The switcher chord was just pressed: show the overlay."""

    @abstractmethod
    def on_cycle(self, reverse: bool) -> None:
        """Tab (forward) or Shift+Tab (backward) while modifiers held."""

    @abstractmethod
    def on_commit(self) -> None:
        """The modifier was released: activate the selection and hide."""

    @abstractmethod
    def on_cancel(self) -> None:
        """Escape (or another cancel) was pressed: hide without activating."""


class HotkeyProvider(ABC):
    @abstractmethod
    def register(self, chord: str, callback) -> None:
        """Register a discrete chord (e.g. 'Super+A') with a callback."""

    @abstractmethod
    def register_switcher(self, chord: str, handler: SwitcherHandler) -> None:
        """Register a hold-to-cycle switcher chord with a handler."""

    @abstractmethod
    def unregister(self, chord: str) -> None: ...

    @abstractmethod
    def start(self) -> None:
        """Begin listening for hotkeys / modifier-release events."""

    @abstractmethod
    def stop(self) -> None: ...
