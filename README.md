# Kage

Extensible, cross-platform **application launcher & window switcher**. macOS first,
then Linux (Wayland-first), then Windows.

See `PLAN.md` for the full roadmap.

## Status

Phase 0 (scaffold) and Phase 1 (Super+A launcher) are complete:

- `uv` project with PySide6, pyobjc frameworks, rapidfuzz dependencies.
- Resident Qt app with a system-tray icon (menu: Settings placeholder, Reload config,
  Quit). `app.setQuitOnLastWindowClosed(False)` keeps it resident.
- Config loader with defaults merged from `~/.config/kage/config.toml`; shortcut
  bindings live here from day one (see `examples/config.toml`).
- macOS Accessibility-permission check + first-run prompt that opens System Settings
  → Privacy & Security → Accessibility.
- **AppProvider (macOS)**: enumerates `.app` bundles from the standard application
  directories with names + cached PNG icons; launches via `NSWorkspace`.
- **WindowProvider (macOS)**: lists on-screen windows via `CGWindowList` (title,
  app, window id, bundle id); activates a specific window via `AXUIElement` raise
  and `NSRunningApplication` activation; falls back to app activation.
- **HotkeyProvider (macOS)**: a `CGEventTap` on a background thread registers the
  launcher chord and suppresses it; matches are marshalled to the main thread via
  a Qt signal.
- **Palette UI**: frameless, centered, pre-built hidden window with a text field
  and a result list with icons; Enter activates/launches, Esc hides, Up/Down moves.
- **Fuzzy matcher** (`rapidfuzz`): merges open windows and installed-but-unopened
  apps; open windows rank above unopened apps.

## Run

```sh
uv run kage
```

On first launch, grant Accessibility permission to your terminal (or to the packaged
app later) and restart Kage.

## Project layout

```
kage/
  core/        # Qt app, config, tray (palette/switcher/fuzzy come later)
  backends/   # abstract WindowProvider / AppProvider / HotkeyProvider
  platform/
    macos/     # pyobjc implementations (accessibility first)
```
