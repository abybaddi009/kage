"""macOS HotkeyProvider via a CGEventTap.

Runs the tap on a dedicated background thread with its own CFRunLoop so it
doesn't depend on the Qt event loop dispatching CFRunLoop sources. Matched
chords are marshalled back to the main thread via Qt signals (so GUI actions
like showing the palette happen on the right thread).

Two registration modes:

* ``register(chord, callback)`` — a *discrete* hotkey: the callback fires
  once per keypress of the chord (e.g. Super+A launcher).
* ``register_switcher(chord, handler)`` — a *hold-to-cycle* hotkey
  (Alt+Tab style): ``on_trigger`` fires on the initial chord press, then
  ``on_cycle`` fires for each subsequent Tab while the modifier is held,
  ``on_commit`` fires when the modifier is released, and ``on_cancel`` on
  Esc. The provider tracks this state machine on the tap thread.

Accessibility permission is required for the event tap.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from ...backends.base import HotkeyProvider, SwitcherHandler
from .chord import Hotkey, parse_chord, COMMAND, ALTERNATE, CONTROL, SHIFT

# Virtual keycodes we react to inside switcher mode.
_TAB_KEYCODE = 48
_ESC_KEYCODE = 53

# CGEventFlags we treat as "known modifiers" when checking for extras.
_KNOWN_MODS = COMMAND | ALTERNATE | CONTROL | SHIFT


class _HotkeyBridge(QObject):
    """Lives on the main thread; emits signals the app can connect to."""

    triggered = Signal(str)  # discrete chord fired


class _SwitcherBridge(QObject):
    """Marshals switcher-mode events from the tap thread to the main thread."""

    trigger = Signal()
    cycle = Signal(bool)  # reverse?
    commit = Signal()
    cancel = Signal()


class MacHotkeyProvider(HotkeyProvider):
    def __init__(self) -> None:
        self._bindings: dict[str, Hotkey] = {}
        self._callbacks: dict[str, callable] = {}  # type: ignore[type-arg]
        self._bridge = _HotkeyBridge()
        self._bridge.triggered.connect(self._dispatch)

        # Switcher mode registration.
        self._switcher_hk: Hotkey | None = None
        self._switcher_handler: SwitcherHandler | None = None
        self._switcher_bridge = _SwitcherBridge()
        self._switcher_bridge.trigger.connect(self._on_switcher_trigger)
        self._switcher_bridge.cycle.connect(self._on_switcher_cycle)
        self._switcher_bridge.commit.connect(self._on_switcher_commit)
        self._switcher_bridge.cancel.connect(self._on_switcher_cancel)

        # State machine, only touched from the tap thread.
        self._in_switcher = False

        self._thread: threading.Thread | None = None
        self._rl = None
        self._port = None
        self._started = False

    def register(self, chord: str, callback) -> None:
        hk = parse_chord(chord)
        self._bindings[hk.chord] = hk
        self._callbacks[hk.chord] = callback

    def register_switcher(self, chord: str, handler: SwitcherHandler) -> None:
        self._switcher_hk = parse_chord(chord)
        self._switcher_handler = handler

    def unregister(self, chord: str) -> None:
        self._bindings.pop(chord, None)
        self._callbacks.pop(chord, None)
        if self._switcher_hk is not None and self._switcher_hk.chord == chord:
            self._switcher_hk = None
            self._switcher_handler = None
            self._in_switcher = False

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

    # ---- main-thread dispatch ----

    def _dispatch(self, chord: str) -> None:
        cb = self._callbacks.get(chord)
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def _on_switcher_trigger(self) -> None:
        if self._switcher_handler is not None:
            try:
                self._switcher_handler.on_trigger()
            except Exception:
                pass

    def _on_switcher_cycle(self, reverse: bool) -> None:
        if self._switcher_handler is not None:
            try:
                self._switcher_handler.on_cycle(reverse)
            except Exception:
                pass

    def _on_switcher_commit(self) -> None:
        if self._switcher_handler is not None:
            try:
                self._switcher_handler.on_commit()
            except Exception:
                pass

    def _on_switcher_cancel(self) -> None:
        if self._switcher_handler is not None:
            try:
                self._switcher_handler.on_cancel()
            except Exception:
                pass

    # ---- event tap ----

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
                kCGEventFlagsChanged,
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

            # --- Switcher mode: we're already cycling. ---
            if self._in_switcher:
                if event_type == kCGEventFlagsChanged:
                    # Modifier released? Commit if any required modifier dropped.
                    if self._switcher_hk is not None and (
                        flags & self._switcher_hk.flags != self._switcher_hk.flags
                    ):
                        self._in_switcher = False
                        self._switcher_bridge.commit.emit()
                    return event
                if event_type == kCGEventKeyDown:
                    if keycode == _TAB_KEYCODE:
                        reverse = bool(flags & SHIFT)
                        self._switcher_bridge.cycle.emit(reverse)
                        return None  # suppress Tab
                    if keycode == _ESC_KEYCODE:
                        self._in_switcher = False
                        self._switcher_bridge.cancel.emit()
                        return None  # suppress Esc
                # Let all other keys through while cycling.
                return event

            # --- Not in switcher mode: match discrete + switcher chords. ---
            if event_type != kCGEventKeyDown:
                return event

            # Discrete chords.
            for chord, hk in self._bindings.items():
                if keycode != hk.keycode:
                    continue
                if flags & hk.flags != hk.flags:
                    continue
                extra = (flags & _KNOWN_MODS) & ~hk.flags
                if extra:
                    continue
                self._bridge.triggered.emit(chord)
                return None  # suppress

            # Switcher chord -> enter switcher mode.
            if self._switcher_hk is not None and keycode == self._switcher_hk.keycode:
                hk = self._switcher_hk
                if flags & hk.flags == hk.flags:
                    # Allow Shift as an extra modifier (Shift+Tab cycles back).
                    extra = (flags & _KNOWN_MODS) & ~hk.flags & ~SHIFT
                    if not extra:
                        self._in_switcher = True
                        self._switcher_bridge.trigger.emit()
                        return None  # suppress the initial Tab
            return event

        self._port = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventFlagsChanged),
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
