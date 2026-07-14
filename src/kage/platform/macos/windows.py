"""macOS WindowProvider: list open windows via CGWindowList and activate them.

Activation uses a combination of NSRunningApplication (bring the owning app
forward) and AXUIElement (raise a specific window when possible).
"""

from __future__ import annotations

from ...backends.base import WindowInfo, WindowProvider


def _import_quartz():
    from Quartz import (  # type: ignore
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
    )
    return (
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
    )


def _import_cocoa():
    from Cocoa import NSRunningApplication, NSWorkspace  # type: ignore
    return NSRunningApplication, NSWorkspace


# pid -> (bundle id, app name) cache, refreshed on demand.
_PID_CACHE: dict[int, tuple[str | None, str]] = {}


def _pid_info(pid: int) -> tuple[str | None, str]:
    if pid in _PID_CACHE:
        return _PID_CACHE[pid]
    NSRunningApplication, NSWorkspace = _import_cocoa()
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is None:
        ws = NSWorkspace.sharedWorkspace()
        info = ws.activeApplication()
        name = str(info.get("NSApplicationName", "")) if info else ""
        return (None, name)
    bundle_id = str(app.bundleIdentifier()) if app.bundleIdentifier() else None
    name = str(app.localizedName()) or bundle_id or "App"
    _PID_CACHE[pid] = (bundle_id, name)
    return (bundle_id, name)


class MacWindowProvider(WindowProvider):
    def list_windows(self) -> list[WindowInfo]:
        (
            CGWindowListCopyWindowInfo,
            kCGListOption,
            kCGNull,
        ) = _import_quartz()
        windows = CGWindowListCopyWindowInfo(kCGListOption, kCGNull)
        out: list[WindowInfo] = []
        if not windows:
            return out
        for w in windows:
            try:
                layer = int(w.get("kCGWindowLayer", 1))
            except (TypeError, ValueError):
                layer = 1
            if layer != 0:
                continue
            owner = w.get("kCGWindowOwnerName")
            pid = w.get("kCGWindowOwnerPID")
            wid = w.get("kCGWindowNumber")
            title = w.get("kCGWindowName")
            if wid is None or pid is None:
                continue
            # Skip windows with no on-screen bounds (purely off-screen helpers).
            bounds = w.get("kCGWindowBounds", {})
            if isinstance(bounds, dict):
                if not bounds.get("Width") or not bounds.get("Height"):
                    continue
            bundle_id, app_name = _pid_info(int(pid))
            name = app_name or (str(owner) if owner else "App")
            title_str = str(title) if title else ""
            out.append(
                WindowInfo(
                    app_name=name,
                    window_title=title_str,
                    window_id=int(wid),
                    bundle_id=bundle_id,
                    pid=int(pid),
                    is_minimized=False,
                )
            )
        return out

    def activate_window(self, window_id: int) -> bool:
        # Find the window info to get pid + title, then raise via AX and app.
        for w in self.list_windows():
            if w.window_id == window_id:
                return self._raise(pid=w.pid, title=w.window_title, bundle_id=w.bundle_id)
        return False

    def activate_app(self, bundle_id: str) -> bool:
        NSRunningApplication, _ = _import_cocoa()
        apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
        if apps and apps.count():
            app = apps.objectAtIndex_(0)
            self._activate_app(app)
            return True
        # Not running: ask NSWorkspace to launch it.
        try:
            from Cocoa import NSWorkspace  # type: ignore

            ws = NSWorkspace.sharedWorkspace()
            url = ws.URLForApplicationWithBundleIdentifier_(bundle_id)
            if url is None:
                return False
            ws.launchApplicationAtURL_options_configuration_error_(url, 0, None, None)
            return True
        except Exception:
            return False

    def _raise(self, pid: int, title: str, bundle_id: str | None) -> bool:
        NSRunningApplication, _ = _import_cocoa()
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        raised = self._ax_raise_window(pid, title)
        if app is not None:
            self._activate_app(app)
        if not raised and bundle_id:
            # Fall back to activating the whole app.
            return self.activate_app(bundle_id)
        return raised

    def _activate_app(self, app) -> None:
        try:
            from AppKit import (  # type: ignore
                NSApplicationActivateAllWindows,
                NSApplicationActivateIgnoringOtherApps,
            )
            app.activateWithOptions_(
                NSApplicationActivateAllWindows | NSApplicationActivateIgnoringOtherApps
            )
        except Exception:
            try:
                app.activateWithOptions_(1 << 1)  # IgnoringOtherApps fallback
            except Exception:
                pass

    def _ax_raise_window(self, pid: int, title: str) -> bool:
        try:
            from ApplicationServices import (  # type: ignore
                AXUIElementCreateApplication,
                AXUIElementCopyAttributeNames,
                AXUIElementCopyAttributeValue,
                AXUIElementCopyAttributeValues,
                kAXChildrenAttribute,
                kAXTitleAttribute,
                kAXRaiseAction,
            )
        except ImportError:
            return False
        app_el = AXUIElementCreateApplication(pid)
        try:
            children = AXUIElementCopyAttributeValue(app_el, kAXChildrenAttribute)
        except Exception:
            children = None
        if not children:
            return False
        # children is an NSArray of AXUIElements (windows).
        n = children.count() if hasattr(children, "count") else 0
        best = None
        for i in range(n):
            win = children.objectAtIndex_(i)
            try:
                t = AXUIElementCopyAttributeValue(win, kAXTitleAttribute)
            except Exception:
                t = None
            tstr = str(t) if t else ""
            if tstr and (tstr == title or title in tstr or tstr in title):
                best = win
                break
            if tstr and best is None:
                best = win
        if best is None:
            return False
        try:
            best.performAction_(kAXRaiseAction)
            return True
        except Exception:
            return False
