# Kage

Extensible, cross-platform **application launcher & window switcher**. macOS first,
then Linux (Wayland-first), then Windows.

See `PLAN.md` for the full roadmap.

## Status

Phase 0 (scaffold) is complete:

- `uv` project with PySide6, pyobjc frameworks, rapidfuzz dependencies.
- Resident Qt app with a system-tray icon (menu: Settings placeholder, Reload config,
  Quit). `app.setQuitOnLastWindowClosed(False)` keeps it resident.
- Config loader with defaults merged from `~/.config/kage/config.toml`; shortcut
  bindings live here from day one (see `examples/config.toml`).
- macOS Accessibility-permission check + first-run prompt that opens System Settings
  → Privacy & Security → Accessibility.

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
