"""macOS AppProvider: enumerate installed .app bundles and launch them."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from ...backends.base import AppInfo, AppProvider


def _import_cocoa():
    from Cocoa import NSWorkspace, NSBundle, NSMutableDictionary  # type: ignore
    return NSWorkspace, NSBundle, NSMutableDictionary


def _import_quartz():
    from Quartz import CGImageDestinationCreateWithURL  # type: ignore
    return CGImageDestinationCreateWithURL


# Standard macOS application directories.
_APP_DIRS = (
    "/Applications",
    "/System/Applications",
    "/System/Applications/Utilities",
    "/Applications/Utilities",
    os.path.expanduser("~/Applications"),
)


class MacAppProvider(AppProvider):
    def __init__(self) -> None:
        self._nsworkspace = _import_cocoa()[0]
        self._icon_cache_dir = None
        try:
            from ...core.paths import data_dir

            self._icon_cache_dir = data_dir() / "icons"
            self._icon_cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def list_apps(self) -> list[AppInfo]:
        seen: set[str] = set()
        apps: list[AppInfo] = []
        for d in _APP_DIRS:
            base = Path(d)
            if not base.is_dir():
                continue
            try:
                entries = sorted(base.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry.suffix != ".app":
                    continue
                key = entry.resolve()
                if key in seen:
                    continue
                seen.add(key)
                info = self._describe(entry)
                if info is not None:
                    apps.append(info)
        return apps

    def _describe(self, path: Path) -> AppInfo | None:
        bundle_id = self._bundle_id(path)
        name = self._bundle_name(path) or path.stem
        icon = self._cache_icon(path)
        return AppInfo(
            name=name,
            bundle_path=str(path),
            bundle_id=bundle_id,
            icon_path=icon,
        )

    def _bundle_id(self, path: Path) -> str | None:
        try:
            info = self._read_plist(path, "CFBundleIdentifier")
            return str(info) if info else None
        except Exception:
            return None

    def _bundle_name(self, path: Path) -> str | None:
        try:
            info = self._read_plist(path, "CFBundleName")
            return str(info) if info else None
        except Exception:
            return None

    def _read_plist(self, path: Path, key: str):
        from Foundation import NSDictionary  # type: ignore

        plist_path = path / "Contents" / "Info.plist"
        if not plist_path.exists():
            return None
        d = NSDictionary.dictionaryWithContentsOfFile_(str(plist_path))
        if d is None:
            return None
        return d.objectForKey_(key)

    def _cache_icon(self, path: Path) -> str | None:
        if self._icon_cache_dir is None:
            return None
        try:
            NSWorkspace = self._nsworkspace
            icon = NSWorkspace.sharedWorkspace().iconForFile_(str(path))
            if icon is None:
                return None
            # Use file size + path as cache key (icon can change with the app).
            key = hashlib.md5(f"{path}:{path.stat().st_mtime_ns}".encode()).hexdigest()
            out = self._icon_cache_dir / f"{key}.png"
            if out.exists():
                return str(out)
            if _save_nsimage_as_png(icon, out):
                return str(out)
        except Exception:
            return None
        return None

    def launch(self, bundle_path: str) -> bool:
        try:
            ws = self._nsworkspace.sharedWorkspace()
            return bool(ws.launchApplication_(bundle_path))
        except Exception:
            return False


def _save_nsimage_as_png(nsimage, dest: Path) -> bool:
    """Write an NSImage to a PNG file. Returns success."""
    try:
        from AppKit import NSBitmapImageRep, NSPNGFileType  # type: ignore
        from Foundation import NSData  # type: ignore

        # Force the image to a 128x128 representation for consistent palette icons.
        size = nsimage.size()
        rep = NSBitmapImageRep.imageRepWithData_(nsimage.TIFFRepresentation())
        if rep is None:
            return False
        png = rep.representationUsingType_properties_(NSPNGFileType, None)
        if png is None:
            return False
        png.writeToFile_atomically_(str(dest), True)
        return True
    except Exception:
        return False
