# Alt-Tabber — Application Launcher & Window Switcher

Extensible, cross-platform launcher / window switcher / activator. macOS first, then Linux (Wayland-first), then Windows.

## Product goals (MVP)

1. **Alt+Tab** — switch between applications (hold Alt, Tab to cycle, release Alt to commit).
2. **Tilde+Tab** — switch between windows of the current application (same hold/cycle/commit semantics).
3. **Customizable shortcuts** — all bindings user-configurable via config file (UI later).
4. **Super+A launcher** (customizable) — a type-to-filter palette showing open windows **and** installed-but-unopened applications; selecting activates the window or launches the app.
5. **Tray icon** — keeps the app resident; menu for settings, reload config, quit.

## Tech stack

| Concern | Choice |
|---|---|
| Language / runtime | Python 3.12+, managed with `uv` |
| UI (palette, switcher overlay, tray) | PySide6 (Qt 6) — resident hidden window for instant show |
| macOS window list / activation | `pyobjc` (Quartz CGWindowList, ApplicationServices AXUIElement, Cocoa NSWorkspace) |
| macOS hotkeys + modifier-release detection | CGEventTap via `pyobjc` (requires Accessibility permission); escalate to a small Swift helper only if tap latency proves inadequate |
| Fuzzy matching | `rapidfuzz` |
| Config | TOML (`~/.config/alttabber/config.toml`) |

## Architecture

Three backend interfaces, implemented per platform. All platform code lives behind them; the core never imports platform modules directly.

- **WindowProvider** — list open windows (with app grouping), activate a window, activate an app.
- **AppProvider** — enumerate installed applications, launch one.
- **HotkeyProvider** — register bindings; report modifier press/release events (needed for hold-to-cycle).

```
alttabber/
  core/        # Qt app, palette UI, switcher overlay, fuzzy matcher, config, tray
  backends/    # the three abstract interfaces
  platform/
    macos/     # pyobjc implementations
    wayland/   # later: Hyprland/Sway IPC adapters
    x11/       # later
    win32/     # later
```

## Key macOS constraints

- **Accessibility permission** is required for the CGEventTap (hotkeys/modifier release) and AXUIElement (window activation). First-run must detect the missing grant and direct the user to System Settings → Privacy & Security → Accessibility.
- Alt+Tab is free to claim on macOS (Cmd+Tab is the system switcher and is left alone).
- "Tilde+Tab" needs a decision: literal `` ` ``+Tab chord, or the conventional Alt+`` ` `` for same-app window cycling. Tracked in Open Questions.
- App enumeration: scan `/Applications`, `~/Applications`, `/System/Applications` for `.app` bundles; launch via NSWorkspace.

## Action tracker

Status: ☐ todo · ◐ in progress · ☑ done

### Phase 0 — Scaffold
- ☑ `uv init`, project layout as above, `pyproject.toml` with PySide6, pyobjc frameworks, rapidfuzz
- ☑ Resident Qt app with tray icon (menu: Settings placeholder, Reload config, Quit)
- ☑ Config loader with defaults + `config.toml` override (shortcut bindings live here from day one)
- ☑ Accessibility-permission check + first-run prompt

### Phase 1 — Super+A launcher (no event tap needed beyond a plain hotkey)
- ☑ AppProvider (macOS): enumerate `.app` bundles with names + icons; launch via NSWorkspace
- ☑ WindowProvider (macOS): list open windows via CGWindowList (title, app, window id); activate via AX/NSRunningApplication
- ☑ Palette UI: frameless, centered, pre-built hidden window; text field + result list with icons
- ☑ Fuzzy matching over merged results (open windows ranked above unopened apps)
- ☑ Global hotkey Super+A shows palette; Enter activates/launches; Esc hides
- ☑ Verify end-to-end: cold launch of an app, activation of an open window, latency feels instant

### Phase 2 — Alt+Tab app switcher
- ☑ CGEventTap: capture Alt+Tab, suppress delivery to focused app, detect Alt release
- ☑ Switcher overlay UI: horizontal app icons, most-recently-used order, pre-built hidden
- ☑ MRU tracking of app activations
- ☑ Hold/cycle/commit state machine (Tab forward, Shift+Tab backward, Esc cancels)
- ☐ Verify against fullscreen apps and multiple displays

### Phase 3 — Tilde+Tab window switcher
- ☑ Resolve Open Question on the exact chord
- ☑ Per-app window enumeration via AXUIElement (CGWindowList alone can't raise a specific window)
- ☑ Reuse switcher overlay filtered to the active app's windows

### Phase 4 — Polish & extensibility
- ☑ Settings UI from tray (edit bindings, launcher scope)
- ☑ Plugin interface for launcher result sources (entry points)
- ☑ Login item / launch-at-startup
- ☐ Packaging (`briefcase` or `pyinstaller`) — only if it outgrows `uv run`

### Later — other platforms
- ☐ Linux Wayland: Hyprland + Sway IPC adapters first; KDE via KWin DBus; GNOME (shell extension) deferred
- ☐ Linux X11: `python-xlib` + `ewmh`
- ☐ Windows: `pywin32` (EnumWindows, SetForegroundWindow, low-level keyboard hook)

## Open questions

1. ~~**Tilde+Tab semantics** — literal backtick+Tab as a chord is unusual and conflicts with typing; propose Alt+`` ` `` (cycle windows of current app, matching macOS convention) unless a true `` ` ``+Tab chord is intended.~~ **Resolved:** Alt+`` ` `` adopted (matches macOS convention); window_switcher hotkey enumerates the frontmost app's windows via AXUIElement and raises the selected window with kAXRaiseAction.
2. Should the launcher also index files/folders or stay apps+windows only for MVP? (Assume apps+windows only.)
3. Switcher scope: current desktop/Space only, or all Spaces? (Assume all, minus minimized indicated differently.)
