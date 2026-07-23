"""Generate the four theme-preview assets for the settings theme picker.

Renders the real SwitcherOverlay in each theme x expansion state (with a
transparent background so the rounded corners survive), then composites it
centered over ``assets/generic-wallpaper.png``. Writes each preview to both
``assets/`` and ``src/alttabber/assets/`` (the packaged copy is what
``theme_preview_path`` resolves first).

Usage::

    QT_QPA_PLATFORM=offscreen python scripts/gen_theme_previews.py [content_dir]

``content_dir`` may hold window-content screenshots named
``settings-{general,switcher,shortcuts,about}.png`` used as fake window
contents for the thumbnail tiles; missing files fall back to the wallpaper.
Defaults to ``scripts/theme_preview_content/``.
"""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication(sys.argv)

from alttabber.core.switcher import SwitcherOverlay, _AppEntry, _WindowEntry

ASSETS = REPO / "assets"
PKG_ASSETS = REPO / "src" / "alttabber" / "assets"
WALL = str(ASSETS / "generic-wallpaper.jpg")
LOGO = str(ASSETS / "logo.png")


def icon(path: str) -> str:
    return path if os.path.exists(path) and not QPixmap(path).isNull() else LOGO


SAFARI = icon("/Applications/Safari.app/Contents/Resources/AppIcon.icns")
FINDER = icon("/System/Library/CoreServices/Finder.app/Contents/Resources/Finder.icns")
NOTES = icon("/System/Applications/Notes.app/Contents/Resources/AppIcon.icns")
MUSIC = icon("/System/Applications/Music.app/Contents/Resources/AppIcon.icns")

# Fake window contents for the thumbnail tiles: screenshots of the settings
# dialog read as plausible app windows at thumbnail size.
content_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "scripts" / "theme_preview_content"
content: list[QPixmap] = []
for name in ("general", "switcher", "shortcuts", "about"):
    pix = QPixmap(str(content_dir / f"settings-{name}.png")) if content_dir else QPixmap()
    content.append(pix if not pix.isNull() else QPixmap(WALL))

apps = [
    _AppEntry(key="s", name="Safari", icon_path=SAFARI, bundle_id="s", window_id=1, window_count=3),
    _AppEntry(key="f", name="Finder", icon_path=FINDER, bundle_id="f", window_id=2, window_count=1),
    _AppEntry(key="n", name="Notes", icon_path=NOTES, bundle_id="n", window_id=3, window_count=2),
    _AppEntry(key="m", name="Music", icon_path=MUSIC, bundle_id="m", window_id=4, window_count=1),
]
wins = [
    _WindowEntry(window_id=1, title="Safari — alttabber/pull/42", app_name="Safari", icon_path=SAFARI, bundle_id="s"),
    _WindowEntry(window_id=2, title="Safari — Documentation", app_name="Safari", icon_path=SAFARI, bundle_id="s"),
    _WindowEntry(window_id=3, title="Downloads", app_name="Finder", icon_path=FINDER, bundle_id="f"),
    _WindowEntry(window_id=4, title="Meeting notes — July", app_name="Notes", icon_path=NOTES, bundle_id="n"),
    _WindowEntry(window_id=5, title="Music", app_name="Music", icon_path=MUSIC, bundle_id="m"),
]
previews = {i: content[(i - 1) % len(content)] for i in range(1, 6)}


def render(ov: SwitcherOverlay) -> QPixmap:
    ov.adjustSize()
    app.processEvents()
    pm = QPixmap(ov.size())
    pm.fill(Qt.transparent)
    ov.render(pm, renderFlags=QWidget.RenderFlag.DrawChildren)
    return pm


def composite(pm: QPixmap, file_name: str) -> None:
    # 1000x600 keeps the 5:3 ratio of the settings dialog's 200x120 cards.
    W, H = 1000, 600
    canvas = QPixmap(W, H)
    p = QPainter(canvas)
    wall = QPixmap(WALL).scaled(W, H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    p.drawPixmap((W - wall.width()) // 2, (H - wall.height()) // 2, wall)
    max_w, max_h = int(W * 0.88), int(H * 0.88)
    if pm.width() > max_w or pm.height() > max_h:
        pm = pm.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    p.drawPixmap((W - pm.width()) // 2, (H - pm.height()) // 2, pm)
    p.end()
    for dest in (ASSETS / file_name, PKG_ASSETS / file_name):
        canvas.save(str(dest))
        print("wrote", dest)


ov = SwitcherOverlay()
ov.show()
app.processEvents()

# 1. Default theme, non-expanded: app icons + count badges + big preview.
ov.set_theme("default")
ov.set_previews_enabled(True)
ov.set_apps(apps, select_index=1)
ov.set_preview(content[0])
composite(render(ov), "default.png")

# 2. Default theme, expanded: one icon tile per window + big preview.
ov.set_windows(wins, select_index=1)
ov.set_preview(content[1])
composite(render(ov), "default-expanded.png")

# 2b. Default theme, previews off: plain icon tiles, no big preview panel.
ov.set_previews_enabled(False)
ov.set_apps(apps, select_index=1)
composite(render(ov), "default-no-preview.png")

# 2c. Default theme, expanded + previews off: plain per-window icon tiles.
ov.set_windows(wins, select_index=1)
composite(render(ov), "default-expanded-no-preview.png")

# 3. Previews theme, non-expanded: one thumbnail per app + count badges.
ov.set_theme("window_previews")
ov.set_previews_enabled(False)
ov.set_apps(apps, select_index=1, tile_previews=previews)
composite(render(ov), "thumbnails.png")

# 4. Previews theme, expanded: one thumbnail per window, elided titles.
ov.set_windows(wins, select_index=1, tile_previews=previews)
composite(render(ov), "thumbnails-expanded.png")
