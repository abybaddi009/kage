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


class AppProvider(ABC):
    @abstractmethod
    def list_apps(self) -> list[AppInfo]:
        """Enumerate installed applications."""

    @abstractmethod
    def launch(self, bundle_path: str) -> bool:
        """Launch an application by bundle path. Return success."""


class HotkeyProvider(ABC):
    @abstractmethod
    def register(self, chord: str, callback) -> None:
        """Register a chord (e.g. 'Super+A') with a callback."""

    @abstractmethod
    def unregister(self, chord: str) -> None: ...

    @abstractmethod
    def start(self) -> None:
        """Begin listening for hotkeys / modifier-release events."""

    @abstractmethod
    def stop(self) -> None: ...
