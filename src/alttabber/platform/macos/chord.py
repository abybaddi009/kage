"""Parse Alt-Tabber chord strings ('Super+A', 'Alt+`', 'Alt+Tab') into a
(modifier-flags, keycode) pair for the macOS event tap.

Modifier tokens recognised: Super/Cmd -> Command; Alt/Option -> Alternate;
Ctrl/Control -> Control; Shift -> Shift.
"""

from __future__ import annotations

from dataclasses import dataclass


# CGEventFlags bit masks.
COMMAND = 1 << 20  # kCGEventFlagMaskCommand
ALTERNATE = 1 << 19  # kCGEventFlagMaskAlternate
CONTROL = 1 << 18  # kCGEventFlagMaskControl
SHIFT = 1 << 17  # kCGEventFlagMaskShift


# macOS virtual keycodes (US layout) for the characters we support.
_KEYCODES: dict[str, int] = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7,
    "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16,
    "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26,
    "8": 28, "9": 25, "0": 29, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37,
    "j": 38, "k": 40, "n": 45, "m": 46,
    ";": 41, "'": 39, ",": 43, ".": 47, "/": 44, "-": 27, "=": 24,
    "`": 50, "[": 33, "]": 30, "\\": 42,
    "tab": 48, "return": 36, "enter": 36, "space": 49,
    "esc": 53, "escape": 53,
}


@dataclass(frozen=True)
class Hotkey:
    chord: str
    flags: int
    keycode: int


def _modifier_flag(tok: str) -> int:
    t = tok.lower()
    if t in ("super", "cmd", "command", "meta"):
        return COMMAND
    if t in ("alt", "option", "opt"):
        return ALTERNATE
    if t in ("ctrl", "control"):
        return CONTROL
    if t == "shift":
        return SHIFT
    raise ValueError(f"unknown modifier: {tok!r}")


def parse_chord(chord: str) -> Hotkey:
    parts = [p.strip() for p in chord.split("+")]
    if not parts:
        raise ValueError("empty chord")
    flags = 0
    for mod in parts[:-1]:
        flags |= _modifier_flag(mod)
    key = parts[-1].lower()
    if key not in _KEYCODES:
        raise ValueError(f"unsupported key: {key!r}")
    return Hotkey(chord=chord, flags=flags, keycode=_KEYCODES[key])
