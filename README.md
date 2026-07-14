# Kage

The window switcher macOS should have shipped with.

macOS's built-in `Cmd+Tab` is a 20-year-old row of blurry icons. It can't show
minimized windows, can't preview what you're switching to, can't let you pick a
*specific* window of an app, and forgets what you used last the moment you log
out. **Kage fixes all of it** — and hands you a fuzzy-search launcher in the same
app, with every shortcut rebindable.

* **Alt+Tab app switcher** — hold Alt, Tab to cycle, release to commit. Same
  gesture you already know, but with **MRU ordering that persists across
  restarts**, live window previews, and Shift+Tab to cycle backward.
* **Alt+` per-app window switcher** — cycle just the windows of the app you're
  in and raise the exact one you want. Minimized windows are *not* silently
  hidden the way they are in the stock switcher.
* **Super+A launcher** — a keystroke opens a fuzzy palette of every open window
  *and* every installed app. Type a few letters with `rapidfuzz`, hit Enter, and
  the window is raised or the app launched. Open windows rank above apps you
  haven't started yet.
* **Live previews** — watch a thumbnail of the window you're about to land on,
  or switch to the `window_previews` theme where every window is its own
  screenshot tile.
* **Rebind everything** — the Settings dialog *captures* chords from your actual
  key press, so the binding always matches what the hotkey engine expects. No
  typos, no guesswork. Reload is live; no restart needed.
* **Extensible** — third-party packages can plug extra result sources into the
  launcher via the `kage.sources` entry point. One bad plugin can't take down
  the palette.
* **Stays out of your way** — resident in the menu bar via a tray icon, a hidden
  reference window keeps popups instant, and **Launch at login** is a checkbox
  away (`SMAppService`, macOS 13+).

Cross-platform by design: macOS today, Linux (Wayland-first) and Windows next.
See `PLAN.md` for the roadmap.

## Run

```sh
uv run kage
```

On first launch, grant **Accessibility** and **Screen Recording** permission to
your terminal (or to the packaged app later) and restart Kage. Accessibility
powers the event tap and window activation; Screen Recording lets Kage read
window titles and capture previews.

## Configuration

Defaults are merged with `~/.config/kage/config.toml`. Edit it by hand or via
the Settings dialog, then use the tray's **Reload config** (the Settings dialog
reloads automatically on save).

```toml
[hotkeys]
launcher = "Super+A"
app_switcher = "Alt+Tab"
window_switcher = "Alt+`"

[palette]
max_results = 12
windows_first = true

[switcher]
expand_windows = false   # list every window as its own Alt+Tab entry
show_previews = true
theme = "default"        # or "window_previews" (a screenshot tile per window)
```

## Build a DMG (macOS)

Package Kage as a proper `.app` so launch-at-login (`SMAppService.mainAppService`)
works reliably and hotkeys survive your terminal closing. The easiest path is
PyInstaller + `hdiutil`:

1. Install the build tool:

   ```sh
   uv pip install pyinstaller
   ```

2. Build the `.app` (windowed, no terminal window, with a bundle id so
   `SMAppService` can target it):

   ```sh
   uv run pyinstaller --windowed \
     --name Kage \
     --osx-bundle-identifier ai.kage.Kage \
     --icon path/to/icon.icns \
     src/kage/__main__.py
   ```

   This produces `dist/Kage.app`. Drop the `--icon` flag if you don't have one
   yet.

3. Create the DMG from the `.app`:

   ```sh
   hdiutil create -volname "Kage" \
     -srcfolder dist/Kage.app \
     -ov -format UDZO \
     dist/Kage.dmg
   ```

4. (Optional, for distribution) **Ad-hoc sign** and **notarize** so Gatekeeper
   doesn't scare users off:

   ```sh
   codesign --deep --force --sign - dist/Kage.app
   xcrun notarytool submit dist/Kage.dmg \
     --apple-id "you@example.com" --team-id "TEAMID" --wait
   xcrun stapler staple dist/Kage.dmg
   ```

   Users mount the DMG, drag `Kage.app` to `/Applications`, and grant
   Accessibility + Screen Recording on first launch.

> Prefer `briefcase` (BeeWare)? It's called out in `PLAN.md` as an alternative
> packager — either produces a bundle that `SMAppService` can register for
> launch-at-login.

## Project layout

```
kage/
  core/        # Qt app, palette, switcher overlay, fuzzy matcher, MRU, settings, sources
  backends/    # abstract WindowProvider / AppProvider / HotkeyProvider / SwitcherHandler
  platform/
    macos/     # pyobjc implementations: accessibility, apps, windows, hotkeys, chord, launch_at_login
```
