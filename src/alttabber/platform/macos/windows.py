"""macOS WindowProvider: list open windows via CGWindowList and activate them.

Activation uses a combination of NSRunningApplication (bring the owning app
forward) and AXUIElement (raise a specific window when possible).
"""

from __future__ import annotations

from ...backends.base import WindowInfo, WindowProvider

# Private CGWindowID <-> AXUIElement bridge. AX only exposes windows by
# title/children order, which is ambiguous when two windows of the same app
# share a title (or both have none) -- _AXUIElementGetWindow gives us the
# real kCGWindowNumber for a given AXUIElement so activation can match on
# identity instead of guessing from title text.
_AX_GET_WINDOW = None
_AX_GET_WINDOW_LOAD_FAILED = False


def _ax_get_window_fn():
    global _AX_GET_WINDOW, _AX_GET_WINDOW_LOAD_FAILED
    if _AX_GET_WINDOW is not None or _AX_GET_WINDOW_LOAD_FAILED:
        return _AX_GET_WINDOW
    try:
        import ctypes

        lib = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        fn = lib._AXUIElementGetWindow
        fn.restype = ctypes.c_int32
        fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        _AX_GET_WINDOW = fn
    except Exception:
        _AX_GET_WINDOW_LOAD_FAILED = True
    return _AX_GET_WINDOW


def _ax_attr(element, attribute):
    """AXUIElementCopyAttributeValue wrapper.

    This pyobjc binding surfaces the (AXError, value) out-param pair, so it
    must be called with a placeholder third argument -- calling it as if it
    returned the value directly raises TypeError, which prior code caught
    and silently treated as "no value", making every AX call here a no-op.
    """
    from ApplicationServices import AXUIElementCopyAttributeValue  # type: ignore

    err, value = AXUIElementCopyAttributeValue(element, attribute, None)
    if err != 0:
        return None
    return value


def _ax_set_focused(ref) -> None:
    """Explicitly set AXFocused=true on a window ref.

    kAXRaiseAction only reorders the window within its own app/process --
    it does not move the system's keyboard focus off the currently active
    display. With "Displays have separate Spaces" (the default), a window
    on another monitor stays inert to Cmd-Tab-style raise/activate calls
    alone; setting kAXFocusedAttribute directly asks the Accessibility
    runloop to give that specific window system-wide keyboard focus, which
    is what actually shifts focus (and the menu bar) onto its display.
    """
    try:
        from ApplicationServices import (  # type: ignore
            AXUIElementSetAttributeValue,
            kAXFocusedAttribute,
        )

        AXUIElementSetAttributeValue(ref, kAXFocusedAttribute, True)
    except Exception:
        pass


def _ax_cg_window_id(ax_ref) -> int | None:
    """Resolve an AXUIElement window ref to its real CGWindowID, if possible."""
    fn = _ax_get_window_fn()
    if fn is None:
        return None
    try:
        import ctypes
        import objc

        ptr = objc.pyobjc_id(ax_ref)
        wid = ctypes.c_uint32(0)
        err = fn(ctypes.c_void_p(ptr), ctypes.byref(wid))
        if err == 0:
            return int(wid.value)
    except Exception:
        pass
    return None


def _import_cocoa():
    from Cocoa import NSRunningApplication, NSWorkspace  # type: ignore
    return NSRunningApplication, NSWorkspace


class MacWindowProvider(WindowProvider):
    def __init__(self) -> None:
        # Strong-reference cache of AXUIElement window refs keyed by the
        # synthetic window_id we hand out in list_app_windows(). Keeps
        # the objc object alive so activate_window() can raise it later.
        self._ax_refs: dict[int, object] = {}
        self._ax_counter = 0
        self._windows_cache: list[WindowInfo] | None = None
        self._windows_cache_at: float = 0.0
        # Lower-cased title substrings to hide (from Config.excluded_window_titles,
        # set by the app on load/reload). A window is dropped if its title
        # contains any of these -- see _apply_exclusions().
        self._excluded_titles: list[str] = []

    def set_excluded_titles(self, titles: list[str]) -> None:
        """Replace the window-title exclusion patterns (case-insensitive)."""
        self._excluded_titles = [t.strip().lower() for t in titles if t.strip()]
        # Drop the cache so the new patterns take effect on the next enumeration.
        self._windows_cache = None

    def _apply_exclusions(self, windows: list[WindowInfo]) -> list[WindowInfo]:
        """Drop windows whose title contains any configured exclusion pattern."""
        if not self._excluded_titles:
            return windows
        out = []
        for w in windows:
            title = (w.window_title or "").lower()
            if any(pat in title for pat in self._excluded_titles):
                continue
            out.append(w)
        return out

    # AX enumeration is a round trip per running app (~15 apps took ~0.75s
    # in testing), which is fine once but far too slow to redo on every
    # keystroke in the palette or every call within a single switcher
    # trigger. A short cache absorbs bursts of calls without meaningfully
    # risking staleness (windows rarely open/close within this window).
    _WINDOWS_CACHE_TTL = 0.25

    def list_windows(self) -> list[WindowInfo]:
        """Enumerate windows of every regular (Dock-visible) running app via AX.

        CGWindowListCopyWindowInfo only reports windows the compositor is
        actively drawing, which silently excludes minimized windows. AX's
        per-app window list has no such restriction, so it's the primary
        source here; minimized windows come back with is_minimized=True.

        AX enumeration of a *background* app's windows is unreliable while
        any app is in native fullscreen -- most reliably it drops the
        fullscreen window itself once its owning app stops being frontmost,
        but it can also silently return an incomplete/empty list for other,
        unrelated background apps while some app elsewhere is fullscreen.
        ``_cg_supplement()`` fills in anything CGWindowList can see (the
        window server's own compositing list, which doesn't share this AX
        blind spot) that the AX pass above missed.
        """
        import time

        now = time.monotonic()
        if (
            self._windows_cache is not None
            and (now - self._windows_cache_at) < self._WINDOWS_CACHE_TTL
        ):
            return self._windows_cache
        try:
            from AppKit import NSApplicationActivationPolicyRegular  # type: ignore
        except ImportError:
            return []
        NSRunningApplication, NSWorkspace = _import_cocoa()
        out: list[WindowInfo] = []
        known_apps: dict[int, tuple[str, str | None]] = {}
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            try:
                if app.activationPolicy() != NSApplicationActivationPolicyRegular:
                    continue
            except Exception:
                continue
            pid = int(app.processIdentifier())
            bundle_id = str(app.bundleIdentifier()) if app.bundleIdentifier() else None
            name = str(app.localizedName()) if app.localizedName() else (bundle_id or "App")
            known_apps[pid] = (name, bundle_id)
            out.extend(self._ax_windows(pid, app_name=name, bundle_id=bundle_id))
        out.extend(self._cg_supplement(out, known_apps))
        out = self._apply_exclusions(out)
        self._windows_cache = out
        self._windows_cache_at = now
        return out

    def _cg_supplement(
        self,
        existing: list[WindowInfo],
        known_apps: dict[int, tuple[str, str | None]],
    ) -> list[WindowInfo]:
        """Return windows CGWindowList sees that the AX pass missed.

        Only fills gaps -- ``existing`` (AX) stays the source of truth for
        anything it did find, since only it can supply an AX ref for raise
        and minimized-window info. Entries added here have no AX ref, so
        activation falls back to the pid/title-based raise path (and
        ultimately to whole-app activation) -- see ``activate_window()``.
        """
        try:
            from Quartz import (  # type: ignore
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionAll,
                kCGNullWindowID,
            )
        except ImportError:
            return []
        # kCGWindowListOptionAll, *not* ...OnScreenOnly: while an app is in
        # native fullscreen, every other app's windows live on a different
        # Space, so the on-screen list reports only the fullscreen Space's
        # own windows and backfills nothing -- exactly the windows AX also
        # goes blind on. The All list is the only source that still sees
        # windows across Spaces in that state.
        info_list = CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID)
        if not info_list:
            return []
        # Dedup against AX both by CGWindowID and by (pid, title): a
        # minimized window AX reported under a synthetic negative id (it
        # couldn't resolve a CGWindowID for it) would otherwise reappear
        # here under its real positive id as a bogus non-minimized duplicate.
        seen_ids = {w.window_id for w in existing}
        seen_pid_title = {(w.pid, (w.window_title or "").strip()) for w in existing}
        extra: list[WindowInfo] = []
        for info in info_list:
            if int(info.get("kCGWindowLayer", -1)) != 0:
                continue
            pid = int(info.get("kCGWindowOwnerPID", -1))
            app_info = known_apps.get(pid)
            if app_info is None:
                continue
            wid = int(info.get("kCGWindowNumber", -1))
            if wid <= 0 or wid in seen_ids:
                continue
            # The All list reports many layer-0 *backing surfaces* per real
            # window: title-less toolbar/tab strips (screen-width x ~30px),
            # tiny drag/icon surfaces (64x64, 1x1), zero-alpha overlays (e.g.
            # a fullscreen window's menu-bar strip), and empty placeholder
            # shells. A genuinely switchable window carries a non-empty
            # title, a real size, and non-zero alpha -- filter on all three.
            title = str(info.get("kCGWindowName") or "").strip()
            if not title:
                continue
            try:
                alpha = float(info.get("kCGWindowAlpha", 1.0))
            except (TypeError, ValueError):
                alpha = 1.0
            if alpha <= 0.0:
                continue
            bounds = info.get("kCGWindowBounds") or {}
            if int(bounds.get("Width", 0)) < 60 or int(bounds.get("Height", 0)) < 60:
                continue
            if (pid, title) in seen_pid_title:
                continue
            name, bundle_id = app_info
            extra.append(
                WindowInfo(
                    app_name=name,
                    window_title=title,
                    window_id=wid,
                    bundle_id=bundle_id,
                    pid=pid,
                    is_minimized=False,
                )
            )
            seen_ids.add(wid)
            seen_pid_title.add((pid, title))
        return extra

    def frontmost_bundle_id(self) -> str | None:
        try:
            from Cocoa import NSWorkspace  # type: ignore

            front = NSWorkspace.sharedWorkspace().frontmostApplication()
            bid = front.bundleIdentifier() if front else None
            return str(bid) if bid else None
        except Exception:
            return None

    def frontmost_window_center(self) -> tuple[float, float] | None:
        """Center point, in global (Quartz/Qt) screen coordinates, of the
        frontmost app's focused window -- used to pick which monitor the
        launcher/switcher opens on in a multi-display setup.

        Deliberately does *not* derive this from ``CGWindowListCopyWindowInfo``
        bounds. That API has a long-standing bug where a window's bounds for
        a native-fullscreen window on a secondary display are frequently
        reported relative to the *primary* display's frame instead of the
        actual display it occupies -- so a numerically "valid" center point
        can still map to the wrong ``QScreen``.

        Also deliberately does *not* use ``NSScreen.mainScreen()`` (tried
        first): that's scoped to the *calling process's own* key window, not
        the system-wide frontmost app -- since this app is a background/
        accessory app with no key window of its own most of the time, it
        just reflected stale/irrelevant state instead of the other app's
        display.

        Instead this reads the frontmost app's ``kAXFocusedWindowAttribute``
        position/size directly via Accessibility. AX position/size use the
        same top-left/Y-down global coordinate space as CGWindowList and Qt
        (no flip needed), but are queried live from the focused app itself
        rather than reconstructed from the window server's compositing list,
        so they aren't subject to the CGWindowList fullscreen-bounds bug.
        Querying only the frontmost (active) app also sidesteps the separate
        AX limitation where *background* apps' windows can fail to enumerate
        while some app is in fullscreen (see ``_cg_supplement()``) -- the
        frontmost app's own AX tree is the one case that's reliably present.
        """
        import os
        import sys

        debug = os.environ.get("ALTTABBER_DEBUG_SCREEN") == "1"

        def dbg(msg: str) -> None:
            if debug:
                print(f"[alttabber windows] {msg}", file=sys.stderr)

        try:
            from ApplicationServices import (  # type: ignore
                AXUIElementCreateApplication,
                AXUIElementCopyAttributeValue,
                AXValueGetValue,
                kAXFocusedWindowAttribute,
                kAXPositionAttribute,
                kAXSizeAttribute,
                kAXValueCGPointType,
                kAXValueCGSizeType,
            )
            from Cocoa import NSWorkspace  # type: ignore
        except ImportError:
            dbg("frontmost_window_center: Cocoa/ApplicationServices import failed")
            return None
        try:
            front = NSWorkspace.sharedWorkspace().frontmostApplication()
            if front is None:
                dbg("frontmost_window_center: no frontmost application")
                return None
            name = str(front.localizedName()) if front.localizedName() else "?"
            pid = int(front.processIdentifier())
            app_el = AXUIElementCreateApplication(pid)
            err, win = AXUIElementCopyAttributeValue(
                app_el, kAXFocusedWindowAttribute, None
            )
            if err != 0 or win is None:
                dbg(f"frontmost_window_center: {name} (pid {pid}) no focused window (err={err})")
                return None
            err, pos_ref = AXUIElementCopyAttributeValue(win, kAXPositionAttribute, None)
            if err != 0 or pos_ref is None:
                dbg(f"frontmost_window_center: {name} (pid {pid}) no position (err={err})")
                return None
            err, size_ref = AXUIElementCopyAttributeValue(win, kAXSizeAttribute, None)
            if err != 0 or size_ref is None:
                dbg(f"frontmost_window_center: {name} (pid {pid}) no size (err={err})")
                return None
            # kAXPositionAttribute/kAXSizeAttribute come back as opaque
            # AXValueRef wrappers, not usable CGPoint/CGSize structs directly
            # -- AXValueGetValue unpacks the underlying value into ``out``.
            ok, point = AXValueGetValue(pos_ref, kAXValueCGPointType, None)
            if not ok or point is None:
                dbg(f"frontmost_window_center: {name} (pid {pid}) AXValueGetValue(point) failed")
                return None
            ok, size = AXValueGetValue(size_ref, kAXValueCGSizeType, None)
            if not ok or size is None:
                dbg(f"frontmost_window_center: {name} (pid {pid}) AXValueGetValue(size) failed")
                return None
            cx = float(point.x) + float(size.width) / 2
            cy = float(point.y) + float(size.height) / 2
            dbg(
                f"frontmost_window_center: {name} (pid {pid}) "
                f"pos=({point.x},{point.y}) size=({size.width},{size.height}) -> center=({cx},{cy})"
            )
            return (cx, cy)
        except Exception as e:
            dbg(f"frontmost_window_center: exception {e!r}")
            return None

    def list_app_windows(self, bundle_id: str) -> list[WindowInfo]:
        """Enumerate windows of one app via AXUIElement (kAXChildrenAttribute),
        supplemented by CGWindowList for anything AX missed.

        AX gives us window references that respond to kAXRaiseAction, which
        CGWindowList alone cannot target. But AX drops a background app's
        windows -- and any app's windows on other Spaces -- while something is
        in native fullscreen, so the per-app (Alt+`) switcher would otherwise
        show an incomplete list. ``_cg_supplement`` fills those in (without AX
        refs; they fall back to the pid/title raise path). Falls back to
        filtering ``list_windows`` when both are unavailable.
        """
        pid = self._pid_for_bundle(bundle_id)
        if pid is None:
            return [w for w in self.list_windows() if w.bundle_id == bundle_id]
        NSRunningApplication, _ = _import_cocoa()
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        name = str(app.localizedName()) if app and app.localizedName() else (bundle_id or "App")
        wins = self._ax_windows(pid, app_name=name, bundle_id=bundle_id)
        wins = wins + self._cg_supplement(wins, {pid: (name, bundle_id)})
        wins = self._apply_exclusions(wins)
        if not wins:
            return [w for w in self.list_windows() if w.bundle_id == bundle_id]
        return wins

    def _pid_for_bundle(self, bundle_id: str) -> int | None:
        try:
            NSRunningApplication, _ = _import_cocoa()
            apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(
                bundle_id
            )
            if apps and apps.count():
                return int(apps.objectAtIndex_(0).processIdentifier())
        except Exception:
            pass
        return None

    def _ax_windows(
        self,
        pid: int,
        app_name: str | None = None,
        bundle_id: str | None = None,
    ) -> list[WindowInfo]:
        try:
            from ApplicationServices import (  # type: ignore
                AXUIElementCreateApplication,
                kAXChildrenAttribute,
                kAXTitleAttribute,
                kAXRoleAttribute,
                kAXMinimizedAttribute,
            )
        except ImportError:
            return []
        app_el = AXUIElementCreateApplication(pid)
        children = _ax_attr(app_el, kAXChildrenAttribute)
        if not children:
            return []
        if app_name is None or bundle_id is None:
            NSRunningApplication, _ = _import_cocoa()
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
            if app_name is None:
                app_name = str(app.localizedName()) if app and app.localizedName() else "App"
            if bundle_id is None:
                bundle_id = (
                    str(app.bundleIdentifier()) if app and app.bundleIdentifier() else None
                )
        out: list[WindowInfo] = []
        n = children.count() if hasattr(children, "count") else 0
        for i in range(n):
            win = children.objectAtIndex_(i)
            # AX exposes non-window children too (menu bar, function row on
            # Touch Bar Macs, etc.) -- only AXWindow entries are real windows.
            if _ax_attr(win, kAXRoleAttribute) != "AXWindow":
                continue
            t = _ax_attr(win, kAXTitleAttribute)
            title = str(t) if t else ""
            minimized = bool(_ax_attr(win, kAXMinimizedAttribute))
            # Prefer the real CGWindowID so ids stay stable/comparable with
            # list_windows(); minimized windows may not resolve one, so fall
            # back to a synthetic id (kept negative to avoid colliding with
            # real CGWindowIDs) while still caching the AX ref for activation.
            cg_id = _ax_cg_window_id(win)
            if cg_id is None:
                self._ax_counter += 1
                wid = -self._ax_counter
            else:
                wid = cg_id
            self._ax_refs[wid] = win
            out.append(
                WindowInfo(
                    app_name=app_name,
                    window_title=title,
                    window_id=wid,
                    bundle_id=bundle_id,
                    pid=pid,
                    is_minimized=minimized,
                )
            )
        return out

    def capture_preview(self, window_id: int) -> bytes | None:
        # Negative ids are synthetic (AX-only, no resolvable CGWindowID --
        # e.g. a minimized window); there's no compositor surface to grab.
        if window_id <= 0:
            return None
        try:
            from Quartz import (  # type: ignore
                CGWindowListCreateImage,
                CGRectNull,
                kCGWindowListOptionIncludingWindow,
                kCGWindowImageBoundsIgnoreFraming,
                kCGWindowImageBestResolution,
            )
            from AppKit import (  # type: ignore
                NSBitmapImageRep,
                NSBitmapImageFileTypePNG,
            )
        except ImportError:
            return None
        try:
            image = CGWindowListCreateImage(
                CGRectNull,
                kCGWindowListOptionIncludingWindow,
                window_id,
                kCGWindowImageBoundsIgnoreFraming | kCGWindowImageBestResolution,
            )
            if image is None:
                return None
            rep = NSBitmapImageRep.alloc().initWithCGImage_(image)
            data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
            if data is None:
                return None
            return bytes(data)
        except Exception:
            return None

    def activate_window(self, window_id: int) -> bool:
        # AX-cached window ref (from list_app_windows) takes priority.
        ref = self._ax_refs.get(window_id)
        if ref is not None:
            return self._ax_raise_ref(ref)
        # Find the window info to get pid + title, then raise via AX and app.
        for w in self.list_windows():
            if w.window_id == window_id:
                return self._raise(
                    pid=w.pid,
                    cg_window_id=w.window_id,
                    title=w.window_title,
                    bundle_id=w.bundle_id,
                )
        return False

    def _ax_raise_ref(self, ref) -> bool:
        try:
            from ApplicationServices import (  # type: ignore
                AXUIElementPerformAction,
                kAXRaiseAction,
            )

            # Activate the owning app *before* raising the specific window,
            # not after: NSApplicationActivateAllWindows asks the app to
            # bring its own windows forward using its internal notion of
            # "key window", which for multi-window apps (Electron apps like
            # VS Code in particular) can override a raise performed first --
            # silently re-focusing whatever window the app had last focused
            # instead of the one the user picked. Raising last makes the AX
            # action the final word on which window ends up frontmost.
            pid = None
            try:
                from ApplicationServices import (  # type: ignore
                    AXUIElementGetPid,
                )

                err, p = AXUIElementGetPid(ref, None)
                if err == 0 and p:
                    pid = int(p)
            except Exception:
                pass
            if pid is not None:
                NSRunningApplication, _ = _import_cocoa()
                app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
                if app is not None:
                    self._activate_app(app)
            AXUIElementPerformAction(ref, kAXRaiseAction)
            _ax_set_focused(ref)
            return True
        except Exception:
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

    def _raise(
        self, pid: int, cg_window_id: int, title: str, bundle_id: str | None
    ) -> bool:
        NSRunningApplication, _ = _import_cocoa()
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        # Activate the app first, then raise the specific window last -- see
        # the comment in _ax_raise_ref for why the ordering matters.
        if app is not None:
            self._activate_app(app)
        raised = self._ax_raise_window(pid, cg_window_id, title)
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

    def _ax_raise_window(self, pid: int, cg_window_id: int, title: str) -> bool:
        try:
            from ApplicationServices import (  # type: ignore
                AXUIElementCreateApplication,
                kAXChildrenAttribute,
                kAXTitleAttribute,
                kAXRaiseAction,
            )
        except ImportError:
            return False
        app_el = AXUIElementCreateApplication(pid)
        children = _ax_attr(app_el, kAXChildrenAttribute)
        if not children:
            return False
        # children is an NSArray of AXUIElements (windows).
        n = children.count() if hasattr(children, "count") else 0
        # Prefer matching the real CGWindowID -- title text is ambiguous
        # when two windows of the same app share a title (or both lack one),
        # which otherwise always raises whichever window AX lists first.
        by_id = None
        title_fallback = None
        for i in range(n):
            win = children.objectAtIndex_(i)
            if _ax_cg_window_id(win) == cg_window_id:
                by_id = win
                break
            t = _ax_attr(win, kAXTitleAttribute)
            tstr = str(t) if t else ""
            if tstr and (tstr == title or title in tstr or tstr in title):
                if title_fallback is None:
                    title_fallback = win
            elif title_fallback is None and tstr:
                title_fallback = win
        best = by_id if by_id is not None else title_fallback
        if best is None:
            return False
        try:
            from ApplicationServices import AXUIElementPerformAction  # type: ignore

            AXUIElementPerformAction(best, kAXRaiseAction)
            _ax_set_focused(best)
            return True
        except Exception:
            return False
