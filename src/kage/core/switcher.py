"""Alt+Tab style app switcher and per-app window switcher.

*SwitcherOverlay* is a frameless, horizontal icon strip shown instantly on
the switcher hotkey. *SwitcherController* implements ``SwitcherHandler`` and
drives the overlay + activation, reusing MRU ordering for apps and AX
window enumeration for per-app windows.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ..backends.base import AppProvider, WindowInfo, WindowProvider
from .activation import activate_window_reliably
from .config import Config
from .mru import MRUTracker, WindowMRUTracker
from .screens import target_screen
from .theme import ui_scale


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class _AppEntry:
    key: str  # bundle_id or app_name
    name: str
    icon_path: str | None
    bundle_id: str | None
    # A representative window (e.g. the first one seen) used for the
    # preview thumbnail -- app entries aren't tied to one specific window.
    window_id: int | None = None
    # How many windows the app has open; shown as a badge on the tile.
    window_count: int = 0


@dataclass
class _WindowEntry:
    window_id: int
    title: str
    app_name: str
    icon_path: str | None
    bundle_id: str | None


# ---------------------------------------------------------------------------
# Overlay widget
# ---------------------------------------------------------------------------


def _with_count_badge(pix: QPixmap, count: int, scale: float = 1.0) -> QPixmap:
    """Return a copy of ``pix`` with a window-count badge in the top-right."""
    if pix.isNull():
        return pix
    out = QPixmap(pix)
    text = str(count) if count < 100 else "99+"
    font = QFont()
    font.setPixelSize(max(8, round(11 * scale)))
    font.setBold(True)
    fm = QFontMetrics(font)
    h = max(14, round(18 * scale))
    w = max(h, fm.horizontalAdvance(text) + round(10 * scale))
    rect = QRect(out.width() - w - 3, 3, w, h)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(59, 130, 246, 235))
    p.drawRoundedRect(rect, h / 2, h / 2)
    p.setPen(QColor("#ffffff"))
    p.setFont(font)
    p.drawText(rect, Qt.AlignCenter, text)
    p.end()
    return out


class _ItemWidget(QFrame):
    """A single tile; highlights when selected.

    Renders either a small app icon (default theme) or, when a window
    screenshot is supplied, a larger preview thumbnail. Preview tiles show
    a small app icon before a middle-elided title; ``badge_count`` (used
    for non-expanded app entries) overlays a window-count badge on the
    image's top-right corner.

    Emits :pyattr:`clicked` on a left-button press so the launcher palette
    can use the same tiles as the switcher overlay for its overview grid.
    """

    clicked = Signal()

    def __init__(
        self,
        icon_path: str | None,
        label: str,
        preview: QPixmap | None = None,
        badge_count: int | None = None,
        preview_size: tuple[int, int] = (176, 110),
        scale: float = 1.0,
    ) -> None:
        super().__init__()
        self._selected = False
        self.setObjectName("switcherItem")
        has_preview = preview is not None and not preview.isNull()

        app_icon_px = max(24, round(64 * scale))
        inline_icon_px = max(12, round(16 * scale))
        text_width = max(72, round(96 * scale))
        font_pt = max(8, round(11 * scale))
        w_overhead = round(20 * scale)
        h_overhead = round(42 * scale)

        image_lbl = QLabel()
        image_lbl.setAlignment(Qt.AlignCenter)
        if has_preview:
            image_lbl.setFixedSize(*preview_size)
            pix = preview.scaled(
                *preview_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            if badge_count:
                pix = _with_count_badge(pix, badge_count, scale)
            image_lbl.setPixmap(pix)
        else:
            pix = QPixmap(icon_path) if icon_path else QPixmap()
            if not pix.isNull():
                pix = pix.scaled(
                    app_icon_px, app_icon_px,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
                if badge_count:
                    pix = _with_count_badge(pix, badge_count, scale)
                image_lbl.setPixmap(pix)
            else:
                image_lbl.setFixedSize(app_icon_px, app_icon_px)
                image_lbl.setText("▢")

        f = QFont()
        f.setPointSize(font_pt)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        lay.addWidget(image_lbl)

        if has_preview:
            # [16px app icon] [middle-elided title], centered as one unit.
            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(4)
            title_row.addStretch(1)

            text_avail = preview_size[0]
            icon_pix = QPixmap(icon_path) if icon_path else QPixmap()
            if not icon_pix.isNull():
                icon_lbl = QLabel()
                icon_lbl.setPixmap(
                    icon_pix.scaled(
                        inline_icon_px, inline_icon_px,
                        Qt.KeepAspectRatio, Qt.SmoothTransformation,
                    )
                )
                title_row.addWidget(icon_lbl)
                text_avail -= inline_icon_px + 4

            text_lbl = QLabel(QFontMetrics(f).elidedText(label, Qt.ElideMiddle, text_avail))
            text_lbl.setFont(f)
            title_row.addWidget(text_lbl)
            title_row.addStretch(1)
            lay.addLayout(title_row)
            self.setToolTip(label)
        else:
            text_lbl = QLabel(label)
            text_lbl.setWordWrap(True)
            text_lbl.setAlignment(Qt.AlignCenter)
            text_lbl.setFont(f)
            text_lbl.setMaximumWidth(text_width)
            lay.addWidget(text_lbl)

        if has_preview:
            self.setFixedSize(preview_size[0] + w_overhead, preview_size[1] + h_overhead)
        else:
            self.setFixedSize(max(72, round(108 * scale)), max(72, round(110 * scale)))
        self._update_style()

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self._update_style()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def _update_style(self) -> None:
        if self._selected:
            self.setStyleSheet(
                "_ItemWidget{background:#3b82f6;border-radius:8px;}"
                "QLabel{color:#ffffff;}"
            )
        else:
            self.setStyleSheet(
                "_ItemWidget{background:rgba(255,255,255,16);border-radius:8px;}"
                "QLabel{color:#e5e7eb;}"
            )


class _FlowContainer(QFrame):
    """A frame that lays its child tiles out in wrapped, center-aligned rows.

    Unlike ``QHBoxLayout``, tiles flow left-to-right and wrap onto a new
    row once they would exceed ``max_content_width`` (typically the host
    screen's available width). Each row is centered horizontally within
    the container so the strip stays visually balanced regardless of how
    many windows are open.
    """

    def __init__(self) -> None:
        super().__init__()
        self._tiles: list[_ItemWidget] = []
        self._max_content_width: int = 10_000
        self._h_spacing: int = 8
        self._v_spacing: int = 8
        self._margins = (12, 12, 12, 12)

    def set_tiles(self, tiles: list[_ItemWidget]) -> None:
        for t in self._tiles:
            t.setParent(None)
            t.deleteLater()
        self._tiles = list(tiles)
        for t in self._tiles:
            t.setParent(self)
            t.show()
        self._relayout()

    def clear(self) -> None:
        self.set_tiles([])

    def tile(self, index: int) -> _ItemWidget | None:
        if 0 <= index < len(self._tiles):
            return self._tiles[index]
        return None

    def count(self) -> int:
        return len(self._tiles)

    def set_max_content_width(self, width: int) -> None:
        self._max_content_width = max(1, width)
        self._relayout()

    def set_margins(self, left: int, top: int, right: int, bottom: int) -> None:
        self._margins = (left, top, right, bottom)
        self._relayout()

    def set_spacing(self, horizontal: int, vertical: int) -> None:
        self._h_spacing = horizontal
        self._v_spacing = vertical
        self._relayout()

    def _relayout(self) -> None:
        ml, mt, mr, mb = self._margins
        if not self._tiles:
            self.setFixedSize(ml + mr, mt + mb)
            return
        avail = max(1, self._max_content_width - ml - mr)
        # Group tiles into rows that fit within ``avail``.
        rows: list[list[_ItemWidget]] = []
        cur: list[_ItemWidget] = []
        cur_w = 0
        for t in self._tiles:
            tw = t.width()
            if cur and cur_w + self._h_spacing + tw > avail:
                rows.append(cur)
                cur = []
                cur_w = 0
            if cur:
                cur_w += self._h_spacing
            cur.append(t)
            cur_w += tw
        if cur:
            rows.append(cur)
        # Width of each row (sum of tile widths + spacing between them).
        row_widths = [
            sum(t.width() for t in row) + self._h_spacing * (len(row) - 1)
            for row in rows
        ]
        content_w = max(row_widths)
        # Position each row, centered horizontally within ``content_w``.
        y = mt
        for row, rw in zip(rows, row_widths):
            x = ml + (content_w - rw) // 2
            for t in row:
                t.setGeometry(x, y, t.width(), t.height())
                x += t.width() + self._h_spacing
            y += max(t.height() for t in row) + self._v_spacing
        y -= self._v_spacing  # undo the trailing gap added after last row
        self.setFixedSize(content_w + ml + mr, y + mb)


class SwitcherOverlay(QWidget):
    activate_app = Signal(str)  # bundle_id (or app key when no bundle id)
    activate_window = Signal(int)  # window_id

    def __init__(self) -> None:
        super().__init__()
        self._entries: list = []  # _AppEntry | _WindowEntry
        self._mode = "apps"  # "apps" | "windows"
        self._index = 0
        self._previews_enabled = False
        self._theme = "default"
        self._screen_preference = "active"
        self._window_provider: WindowProvider | None = None
        self._tile_previews: dict[int, QPixmap] = {}
        self._max_content_width: int = 10_000
        self._scale: float = 1.0

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._preview_label = QLabel()
        self._preview_label.setFixedSize(480, 270)
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setStyleSheet(
            "background:rgba(24,24,27,235);border-radius:10px;color:#9ca3af;"
        )
        self._preview_label.hide()

        self._container = _FlowContainer()
        self._container.setObjectName("switcherBox")
        self._container.setStyleSheet(
            "#switcherBox{background:rgba(24,24,27,235);border-radius:14px;}"
        )
        self._container.set_margins(12, 12, 12, 12)
        self._container.set_spacing(8, 8)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        outer.addWidget(self._preview_label, alignment=Qt.AlignHCenter)
        outer.addWidget(self._container, alignment=Qt.AlignHCenter)

        self.hide()

    # ---- population ----

    def set_theme(self, theme: str) -> None:
        self._theme = theme

    def set_screen_preference(
        self, preference: str, window_provider: WindowProvider | None = None
    ) -> None:
        self._screen_preference = preference
        self._window_provider = window_provider

    def set_size_scale(self, scale: float) -> None:
        """Apply a UI size scale (tile icons/text, preview label, spacing).

        Stores the scale so subsequent ``_rebuild()`` passes thread it into
        every :class:`_ItemWidget`, and resizes the live preview label plus
        container margins/spacing. Rebuilds tiles immediately if entries
        already exist so the change is visible without a re-trigger.
        """
        if scale == self._scale:
            return
        self._scale = scale
        self._preview_label.setFixedSize(
            max(200, round(480 * scale)), max(112, round(270 * scale))
        )
        m = max(6, round(12 * scale))
        s = max(4, round(8 * scale))
        self._container.set_margins(m, m, m, m)
        self._container.set_spacing(s, s)
        if self._entries:
            self._rebuild()

    def set_apps(
        self,
        entries: list[_AppEntry],
        select_index: int = 0,
        tile_previews: dict[int, QPixmap] | None = None,
    ) -> None:
        self._mode = "apps"
        self._entries = entries
        self._tile_previews = tile_previews or {}
        self._rebuild()
        self._select(min(select_index, max(0, len(entries) - 1)))

    def set_windows(
        self,
        entries: list[_WindowEntry],
        select_index: int = 0,
        tile_previews: dict[int, QPixmap] | None = None,
    ) -> None:
        self._mode = "windows"
        self._entries = entries
        self._tile_previews = tile_previews or {}
        self._rebuild()
        self._select(min(select_index, max(0, len(entries) - 1)))

    def _rebuild(self) -> None:
        tiles: list[_ItemWidget] = []
        scaled_preview_size = (
            max(72, round(176 * self._scale)),
            max(45, round(110 * self._scale)),
        )
        for e in self._entries:
            preview = None
            if self._theme == "window_previews":
                wid = getattr(e, "window_id", None)
                if wid is not None:
                    preview = self._tile_previews.get(wid)
            if isinstance(e, _AppEntry):
                tile = _ItemWidget(
                    e.icon_path,
                    e.name,
                    preview=preview,
                    badge_count=e.window_count or None,
                    preview_size=scaled_preview_size,
                    scale=self._scale,
                )
            else:
                tile = _ItemWidget(
                    e.icon_path,
                    e.title or e.app_name,
                    preview=preview,
                    preview_size=scaled_preview_size,
                    scale=self._scale,
                )
            tiles.append(tile)
        self._container.set_tiles(tiles)
        # Re-apply the screen-derived width constraint now that the tiles
        # changed; without it the flow container would fall back to its
        # default (very wide) bound and lay out a single row.
        self._container.set_max_content_width(self._max_content_width)

    def _select(self, index: int) -> None:
        self._index = index
        for i in range(self._container.count()):
            w = self._container.tile(i)
            if isinstance(w, _ItemWidget):
                w.set_selected(i == index)

    def current_entry(self):
        if not self._entries:
            return None
        return self._entries[self._index]

    # ---- preview ----

    def set_previews_enabled(self, enabled: bool) -> None:
        self._previews_enabled = enabled
        if not enabled:
            self._preview_label.hide()
            self._preview_label.clear()

    def set_preview(self, pixmap: QPixmap | None) -> None:
        if not self._previews_enabled:
            return
        if pixmap is None or pixmap.isNull():
            self._preview_label.setPixmap(QPixmap())
            self._preview_label.setText("No preview")
        else:
            scaled = pixmap.scaled(
                self._preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self._preview_label.setText("")
            self._preview_label.setPixmap(scaled)
        self._preview_label.show()

    # ---- navigation ----

    def cycle(self, reverse: bool = False) -> None:
        n = len(self._entries)
        if n == 0:
            return
        if reverse:
            self._index = (self._index - 1) % n
        else:
            self._index = (self._index + 1) % n
        self._select(self._index)

    def commit(self) -> None:
        if not self._entries:
            self.hide()
            return
        e = self._entries[self._index]
        if self._mode == "apps" and isinstance(e, _AppEntry):
            # Raise the app's representative window via AX when we have
            # one -- activate_app() only calls NSRunningApplication's
            # activateWithOptions_, which brings the process forward but
            # does not un-minimize/raise a specific (possibly hidden)
            # window the way activate_window()'s AX raise action does.
            if e.window_id is not None:
                self.activate_window.emit(e.window_id)
            else:
                self.activate_app.emit(e.bundle_id or e.key)
        elif isinstance(e, _WindowEntry):
            self.activate_window.emit(e.window_id)
        self.hide()

    # ---- show / hide ----

    def show_overlay(self) -> None:
        current = self.screen() if hasattr(self, "screen") else None
        screen = target_screen(self._screen_preference, current, self._window_provider)
        if screen is not None:
            sg = screen.availableGeometry()
            # Leave a comfortable gutter on either side of the strip so the
            # rounded container never kisses the screen edges, and constrain
            # the flow layout so tiles wrap into rows before overflowing.
            gutter = 64
            self._max_content_width = max(200, sg.width() - gutter * 2)
            self._container.set_max_content_width(self._max_content_width)
            self.adjustSize()
            x = sg.center().x() - self.width() // 2
            y = int(sg.center().y() * 0.4) - self.height() // 2
            self.move(x, y)
        else:
            self.adjustSize()
        self.show()
        self.raise_()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Controller (implements SwitcherHandler)
# ---------------------------------------------------------------------------


class SwitcherController(QObject):
    """Drives the overlay for both the app switcher and window switcher.

    ``mode`` selects whether the overlay shows running apps (Alt+Tab) or the
    windows of the active app (Alt+`).
    """

    triggered = Signal()

    def __init__(
        self,
        window_provider: WindowProvider,
        app_provider: AppProvider,
        mru: MRUTracker,
        mode: str = "apps",
        config: Config | None = None,
        window_mru: WindowMRUTracker | None = None,
    ) -> None:
        super().__init__()
        self._wp = window_provider
        self._ap = app_provider
        self._mru = mru
        self._wmru = window_mru
        self._mode = mode
        self.config = config
        self.overlay = SwitcherOverlay()
        self.overlay.set_size_scale(
            ui_scale(config.ui_size) if config is not None else 1.0
        )
        self.overlay.activate_app.connect(self._on_activate_app)
        self.overlay.activate_window.connect(self._on_activate_window)

    # ---- build entries ----

    def _running_apps(self) -> list[_AppEntry]:
        windows = self._wp.list_windows()
        # Group by bundle_id (fallback app_name) to get distinct running apps.
        keys: dict[str, _AppEntry] = {}
        representative_minimized: dict[str, bool] = {}
        for w in windows:
            key = w.bundle_id or w.app_name
            if key not in keys:
                icon = None
                if w.bundle_id:
                    icon = self._ap.icon_for_bundle_id(w.bundle_id)
                keys[key] = _AppEntry(
                    key=key,
                    name=w.app_name,
                    icon_path=icon,
                    bundle_id=w.bundle_id,
                    window_id=w.window_id,
                    window_count=1,
                )
                representative_minimized[key] = w.is_minimized
            else:
                keys[key].window_count += 1
                if representative_minimized.get(key) and not w.is_minimized:
                    # Prefer a visible window as the representative over a
                    # minimized one, so committing this entry raises something
                    # already on-screen rather than an arbitrary hidden window.
                    keys[key].window_id = w.window_id
                    representative_minimized[key] = False
        all_keys = list(keys.values())
        ordered_keys = self._mru.order([e.key for e in all_keys])
        key_to_entry = {e.key: e for e in all_keys}
        return [key_to_entry[k] for k in ordered_keys if k in key_to_entry]

    def _flat_window_entries(self) -> list[_WindowEntry]:
        """Every window of every app as its own entry, ordered by per-window
        MRU so a single Alt+Tab targets the previously focused window
        regardless of which app owns it (KDE-style). Windows kage has never
        seen activated are appended after known ones in list_windows order."""
        windows = self._wp.list_windows()
        # Deduplicate by window_id (AX may report a window twice across
        # Spaces); keep the first occurrence.
        seen_ids: set[int] = set()
        uniq: list[WindowInfo] = []
        for w in windows:
            if w.window_id in seen_ids:
                continue
            seen_ids.add(w.window_id)
            uniq.append(w)

        if self._wmru is not None:
            ordered_ids = self._wmru.order([w.window_id for w in uniq])
            by_id = {w.window_id: w for w in uniq}
            ordered_windows = [by_id[wid] for wid in ordered_ids if wid in by_id]
        else:
            ordered_windows = uniq

        out: list[_WindowEntry] = []
        for w in ordered_windows:
            icon = self._ap.icon_for_bundle_id(w.bundle_id) if w.bundle_id else None
            out.append(
                _WindowEntry(
                    window_id=w.window_id,
                    title=w.window_title or w.app_name,
                    app_name=w.app_name,
                    icon_path=icon,
                    bundle_id=w.bundle_id,
                )
            )
        return out

    def _app_windows(self) -> list[_WindowEntry]:
        bid = self._wp.frontmost_bundle_id()
        if not bid:
            return []
        wins = self._wp.list_app_windows(bid)
        icon = self._ap.icon_for_bundle_id(bid)
        out: list[_WindowEntry] = []
        seen: set[int] = set()
        for w in wins:
            if w.window_id in seen:
                continue
            seen.add(w.window_id)
            title = w.window_title or w.app_name
            out.append(
                _WindowEntry(
                    window_id=w.window_id,
                    title=title,
                    app_name=w.app_name,
                    icon_path=icon,
                    bundle_id=bid,
                )
            )
        return out

    # ---- SwitcherHandler interface ----

    def on_trigger(self, reverse: bool = False) -> None:
        self.triggered.emit()
        show_previews = bool(self.config.switcher.show_previews) if self.config else False
        theme = self.config.switcher.theme if self.config else "default"
        expand = bool(self.config.switcher.expand_windows) if self.config else False
        # Re-apply the UI size scale on every trigger so a live Settings
        # save (no app restart) takes effect on the next Alt+Tab.
        if self.config is not None:
            self.overlay.set_size_scale(ui_scale(self.config.ui_size))
        self.overlay.set_theme(theme)
        self.overlay.set_screen_preference(
            self.config.screen_preference if self.config else "active", self._wp
        )
        # The window_previews theme shows a screenshot per tile already, so
        # the single large "current selection" preview would be redundant.
        self.overlay.set_previews_enabled(show_previews and theme == "default")

        if self._mode == "apps":
            # Non-expanded window_previews shows one tile per app: the
            # representative window's screenshot with a window-count badge.
            if expand:
                entries = self._flat_window_entries()
                setter = self.overlay.set_windows
            else:
                entries = self._running_apps()
                setter = self.overlay.set_apps
        else:
            entries = self._app_windows()
            setter = self.overlay.set_windows

        # A single tap of the chord should switch one window/app, not just
        # re-show the current one. Start one step in the chosen direction:
        # forward lands on the previous app / next window, reverse (Shift
        # held, e.g. Alt+Shift+Tab) lands on the last entry. Without this,
        # the window switcher (mode="windows") started on index 0, the
        # current window, so a quick tap-and-release did nothing.
        #
        # In expanded mode, entries are ordered by per-window MRU (not
        # grouped by app), so index 1 is genuinely the previously-focused
        # window -- a single tap thus mirrors KDE's per-window Alt+Tab.
        if len(entries) > 1:
            select_index = (len(entries) - 1) if reverse else 1
        else:
            select_index = 0

        tile_previews = (
            self._capture_tile_previews(entries)
            if show_previews and theme == "window_previews"
            else {}
        )
        setter(entries, select_index=select_index, tile_previews=tile_previews)

        self._update_preview()
        self.overlay.show_overlay()

    def on_cycle(self, reverse: bool) -> None:
        self.overlay.cycle(reverse)
        self._update_preview()

    def on_commit(self) -> None:
        entry = self.overlay.current_entry()
        if isinstance(entry, _AppEntry):
            self._mru.touch(entry.bundle_id or entry.key)
            if self._wmru is not None and entry.window_id is not None:
                self._wmru.touch(entry.window_id)
        elif isinstance(entry, _WindowEntry):
            if entry.bundle_id:
                self._mru.touch(entry.bundle_id)
            if self._wmru is not None:
                self._wmru.touch(entry.window_id)
        self.overlay.commit()

    def on_cancel(self) -> None:
        self.overlay.hide()

    def _capture_tile_previews(self, entries: list) -> dict[int, QPixmap]:
        out: dict[int, QPixmap] = {}
        for e in entries:
            wid = getattr(e, "window_id", None)
            if wid is None or wid in out:
                continue
            data = self._wp.capture_preview(wid)
            if not data:
                continue
            pix = QPixmap()
            pix.loadFromData(data, "PNG")
            out[wid] = pix
        return out

    def _update_preview(self) -> None:
        if not (self.config and self.config.switcher.show_previews):
            return
        if self.config.switcher.theme != "default":
            return
        entry = self.overlay.current_entry()
        window_id = getattr(entry, "window_id", None)
        if window_id is None:
            self.overlay.set_preview(None)
            return
        data = self._wp.capture_preview(window_id)
        if not data:
            self.overlay.set_preview(None)
            return
        pix = QPixmap()
        pix.loadFromData(data, "PNG")
        self.overlay.set_preview(pix)

    # ---- activation ----

    def _on_activate_app(self, key_or_bid: str) -> None:
        # ``key`` may be a bundle id (preferred) or an app name fallback.
        # Heuristic: if it looks like a bundle id (contains '.'), activate
        # by bundle id; otherwise scan running windows for a matching app.
        # (MRU touch happens once in on_commit(), keyed off the entry.)
        if "." in key_or_bid:
            self._wp.activate_app(key_or_bid)
            return
        # Fallback: find a window whose app_name matches and raise its app.
        for w in self._wp.list_windows():
            if w.app_name == key_or_bid:
                if w.bundle_id:
                    self._wp.activate_app(w.bundle_id)
                else:
                    activate_window_reliably(self._wp, w.window_id)
                return

    def _on_activate_window(self, window_id: int) -> None:
        activate_window_reliably(self._wp, window_id)
