"""macOS HotkeyProvider via a CGEventTap (keyDown).

Runs the tap on a dedicated background thread with its own CFRunLoop so it
doesn't depend on the Qt event loop dispatching CFRunLoop sources. Matched
chords are marshalled back to the main thread via Qt signals (so GUI actions
like showing the palette happen on the right thread).

Accessibility permission is required for the event tap.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from ...backends.base import HotkeyProvider
from .chord import Hotkey, parse_chord, COMMAND, ALTERNATE, CONTROL, SHIFT


class _HotkeyBridge(QObject):
    """Lives on the main thread; emits triggered signals the app can connect to."""

    triggered = Signal(str)


class MacHotkeyProvider(HotkeyProvider):
    def __init__(self) -> None:
        self._bindings: dict[str, Hotkey] = {}
        self._callbacks: dict[str, callable] = {}  # type: ignore[type-arg]
        self._bridge = _HotkeyBridge()
        self._bridge.triggered.connect(self._dispatch)
        self._thread: threading.Thread | None = None
        self._rl = None
        self._port = None
        self._started = False

    def register(self, chord: str, callback) -> None:
        hk = parse_chord(chord)
        self._bindings[hk.chord] = hk
        self._callbacks[hk.chord] = callback

    def unregister(self, chord: str) -> None:
        self._bindings.pop(chord, None)
        self._callbacks.pop(chord, None)

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        try:
            from CoreFoundation import CFRunLoopStop  # type: ignore

            if self._rl is not None:
                CFRunLoopStop(self._rl)
        except Exception:
            pass

    # ---- internal ----

    def _dispatch(self, chord: str) -> None:
        cb = self._callbacks.get(chord)
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def _run(self) -> None:
        try:
            from CoreFoundation import (  # type: ignore
                CFMachPortCreateRunLoopSource,
                CFRunLoopGetCurrent,
                CFRunLoopAddSource,
                kCFRunLoopCommonModes,
                CFRunLoopRun,
            )
            from Quartz import (  # type: ignore
                CGEventTapCreate,
                kCGSessionEventTap,
                kCGHeadInsertEventTap,
                kCGEventTapOptionDefault,
                CGEventMaskBit,
                kCGEventKeyDown,
            )
        except ImportError:
            return

        def callback(proxy, event_type, event, refcon):
            try:
                from Quartz import (  # type: ignore
                    CGEventGetFlags,
                    CGEventGetIntegerValueField,
                    kCGKeyboardEventKeycode,
                )

                flags = CGEventGetFlags(event)
                keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            except Exception:
                return event

            for chord, hk in self._bindings.items():
                if keycode != hk.keycode:
                    continue
                # Require all of the chord's modifiers to be present.
                if flags & hk.flags != hk.flags:
                    continue
                # Disallow extra modifiers not in the chord.
                known = COMMAND | ALTERNATE | CONTROL | SHIFT
                extra = (flags & known) & ~hk.flags
                if extra:
                    continue
                self._bridge.triggered.emit(chord)
                return None  # suppress delivery
            return event

        self._port = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            CGEventMaskBit(kCGEventKeyDown),
            callback,
            None,
        )
        if self._port is None:
            # Most likely missing Accessibility permission.
            return
        self._rl = CFRunLoopGetCurrent()
        source = CFMachPortCreateRunLoopSource(None, self._port, 0)
        CFRunLoopAddSource(self._rl, source, kCFRunLoopCommonModes)
        CFRunLoopRun()
