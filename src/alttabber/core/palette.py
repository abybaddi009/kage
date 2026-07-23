"""Launcher palette: frameless, full-screen overview window.

Three-section layout inspired by KDE's Present Windows overview:

::

    ┌──────────────────────────────────────────────────────┐
    │  🔍  Search windows and applications…                 │  ← search field
    ├──────────────────────────────────────────────────────┤
    │  ▸ Safari — GitHub                                    │
    │  ▸ Notes — Meeting                                    │  ← results list
    │  ▸ Xcode                                              │   (compact, fuzzy)
    ├──────────────────────────────────────────────────────┤
    │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────┐  │
    │  │ thumb  │ │ thumb  │ │ thumb  │ │ thumb  │ │ ..  │  │  ← overview
    │  │ title  │ │ title  │ │ title  │ │ title  │ │     │  │   grid fills
    │  └────────┘ └────────┘ └────────┘ └────────┘ └────┘  │   all remaining
    │  ┌────────┐ ┌────────┐                               │   space; tiles
    │  │ thumb  │ │ thumb  │                               │   shrink to fit
    │  │ title  │ │ title  │                               │   (no scrolling)
    │  └────────┘ └────────┘                               │
    └──────────────────────────────────────────────────────┘

The window fills most of the screen. Typing filters both the result list
and the thumbnail grid. Thumbnails shrink so all open windows are visible
at once — no scrolling needed. Enter activates the selected list result;
clicking a thumbnail activates that window directly.
"""

from __future__ import annotations

import math
import sys

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..backends.base import AppProvider, WindowProvider
from .config import Config
from .matcher import Result, match
from .mru import MRUTracker, WindowMRUTracker
from .screens import target_screen
from .sources import load_sources
from .switcher import _FlowContainer, _ItemWidget, _WindowEntry
from .theme import (
    OVERLAY_BG,
    OVERLAY_FIELD_BORDER,
    OVERLAY_HOVER,
    OVERLAY_PANEL_BG,
    OVERLAY_SEPARATOR,
    OVERLAY_TEXT,
    Tokens,
    ui_scale,
)


# ---------------------------------------------------------------------------
# Overview grid
# ---------------------------------------------------------------------------


# Default (maximum) tile dimensions. Tiles shrink below these to fit.
_MAX_PREVIEW_W = 220
_MAX_PREVIEW_H = 138
# Tile chrome: margins + title row height.
_TILE_MARGIN = 20  # left+right margins (6+6) + padding
_TILE_TITLE_H = 32  # title row + spacing
_TILE_W_OVERHEAD = 20
_TILE_H_OVERHEAD = 42
_TILE_GAP = 16
# Margins the overview's own container adds around the tile grid; kept in
# sync with the ``set_margins()`` call in ``_OverviewGrid.__init__`` so the
# available-space math below matches what actually gets laid out.
_CONTAINER_MARGIN = 14


def _compute_tile_size(
    n_entries: int, avail_w: int, avail_h: int, scale: float = 1.0
) -> tuple[int, int]:
    """Return ``(preview_w, preview_h)`` so all tiles fit without scrolling.

    Tries every column count from 1..N and picks the one that yields the
    largest tile size that still fits within the available area. ``scale``
    multiplies the base tile constants (max preview size, tile chrome
    overhead, gap) so a UI size tier can grow tiles without changing the
    shrink-to-fit math.
    """
    if n_entries <= 0 or avail_w <= 0 or avail_h <= 0:
        return int(_MAX_PREVIEW_W * scale), int(_MAX_PREVIEW_H * scale)

    max_pw = _MAX_PREVIEW_W * scale
    max_ph = _MAX_PREVIEW_H * scale
    w_overhead = _TILE_W_OVERHEAD * scale
    h_overhead = _TILE_H_OVERHEAD * scale
    gap = _TILE_GAP * scale

    best = (max(48, int(64 * scale)), max(30, int(40 * scale)))  # minimum floor
    for cols in range(1, n_entries + 1):
        rows = math.ceil(n_entries / cols)
        # Width budget per tile (accounting for gaps + margins).
        w_per_tile = (avail_w - gap * (cols - 1)) / cols
        h_per_tile = (avail_h - gap * (rows - 1)) / rows
        # Convert to preview image area (subtract chrome).
        pw = w_per_tile - w_overhead
        ph = h_per_tile - h_overhead
        if pw <= 0 or ph <= 0:
            continue
        # Maintain the preview aspect ratio (176:110 ≈ 1.6).
        aspect = _MAX_PREVIEW_W / _MAX_PREVIEW_H
        if pw / ph > aspect:
            ph_adj = pw / aspect
            pw_adj = pw
        else:
            pw_adj = ph * aspect
            ph_adj = ph
        # Cap at the maximum tile size.
        pw_adj = min(pw_adj, max_pw)
        ph_adj = min(ph_adj, max_ph)
        pw_adj = max(pw_adj, 48)
        ph_adj = max(ph_adj, 30)
        if pw_adj > best[0]:
            best = (int(pw_adj), int(ph_adj))
    return best


class _OverviewGrid(QWidget):
    """A wrapping grid of window thumbnail tiles that shrink to fit.

    Reuses :class:`_FlowContainer` and :class:`_ItemWidget` from the
    switcher so the tiles look identical to the ``window_previews``
    theme. Tiles are sized so all entries fit within the available area
    without scrolling.
    """

    activate_window = Signal(int)  # window_id

    def __init__(self, scale: float = 1.0) -> None:
        super().__init__()
        self._entries: list[_WindowEntry] = []
        self._previews: dict[int, QPixmap] = {}
        self._scale = scale
        # window_id -> tile, kept across rebuilds so filtering as the user
        # types reuses existing tiles instead of destroying and
        # reconstructing every one (each construction re-scales pixmaps and
        # builds a widget tree, which was the actual per-keystroke cost).
        self._tile_cache: dict[int, _ItemWidget] = {}
        self._tile_size: tuple[int, int] | None = None
        # Hover-driven highlighting is gated behind an explicit arm so a
        # tile that merely renders under an already-stationary cursor
        # doesn't light up on its own; only an actual mouse move after the
        # palette opens arms it (see PaletteWindow.eventFilter). Fixes the
        # spurious highlight on show plus the follow-on where moving the
        # mouse wouldn't re-highlight.
        self._hover_armed = False
        self._container = _FlowContainer()
        self._container.setObjectName("overviewBox")
        self._container.setStyleSheet(
            f"#overviewBox{{background:{OVERLAY_PANEL_BG};border-radius:12px;}}"
        )
        margin = int(_CONTAINER_MARGIN * scale)
        gap = int(_TILE_GAP * scale)
        self._container.set_margins(margin, margin, margin, margin)
        self._container.set_spacing(gap, gap)

        # The grid is centered as a whole in the available area, the way
        # KDE's Present Windows centers thumbnails in open space rather
        # than pinning them to a corner.
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._container, stretch=1, alignment=Qt.AlignCenter)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_scale(self, scale: float) -> None:
        """Update the UI size scale and re-layout tiles.

        Used by :class:`PaletteWindow` to apply a live ``ui_size`` config
        change (Settings dialog save, no app restart) on the next show.
        """
        if scale == self._scale:
            return
        self._scale = scale
        margin = int(_CONTAINER_MARGIN * scale)
        gap = int(_TILE_GAP * scale)
        self._container.set_margins(margin, margin, margin, margin)
        self._container.set_spacing(gap, gap)
        self._relayout()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._relayout()

    def relayout(self) -> None:
        """Force a re-layout using the widget's current allocated size.

        Public so callers can request a fresh layout pass right after the
        host window is resized, since the very first ``resizeEvent`` can
        race with populating the grid on initial show.
        """
        self._relayout()

    def _relayout(self) -> None:
        if not self._entries:
            return
        # Compute the space actually available to the tile grid from this
        # widget's own allocated geometry -- *not* from ``self._container``,
        # whose size is a function of its own tiles (it self-sizes to its
        # content, then this call centers it). Reading the container's size
        # here would create a feedback loop where tiles are sized off of a
        # previous, usually much smaller, layout pass -- the root cause of
        # thumbnails rendering tiny and clustered instead of filling the
        # overview area.
        margin = int(_CONTAINER_MARGIN * self._scale)
        avail_w = self.width() - margin * 2
        avail_h = self.height() - margin * 2
        if avail_w <= 0 or avail_h <= 0:
            return
        pw, ph = _compute_tile_size(
            len(self._entries), avail_w, avail_h, self._scale
        )
        self._rebuild_tiles(pw, ph, avail_w)

    def set_entries(
        self,
        entries: list[_WindowEntry],
        previews: dict[int, QPixmap] | None = None,
    ) -> None:
        previews = previews or {}
        self._entries = list(entries)
        self._previews = previews
        self._relayout()

    def clear(self) -> None:
        self._entries = []
        self._previews = {}
        self._tile_cache = {}
        self._tile_size = None
        self._container.clear()

    def is_empty(self) -> bool:
        return len(self._entries) == 0

    def highlight_window(self, window_id: int | None) -> None:
        """Highlight the thumbnail tile matching ``window_id``.

        Clears any previous highlight. Used by the palette window to
        mirror the results-list selection onto the overview grid as the
        user navigates with the arrow keys.
        """
        for i in range(self._container.count()):
            tile = self._container.tile(i)
            if not isinstance(tile, _ItemWidget):
                continue
            e = getattr(tile, "_window_entry", None)
            wid = e.window_id if e is not None else None
            tile.set_selected(wid == window_id)

    def set_hover_armed(self, armed: bool) -> None:
        """Enable/disable hover-driven highlighting.

        Disarmed on palette show so a tile rendering under a stationary
        cursor doesn't light up; armed on the first real mouse move so
        subsequent hovers highlight as expected. Keyboard-driven
        ``highlight_window`` calls are unaffected.
        """
        self._hover_armed = armed

    def _on_tile_hovered(self, window_id: int) -> None:
        if self._hover_armed:
            self.highlight_window(window_id)

    def _rebuild_tiles(self, pw: int, ph: int, avail_w: int) -> None:
        # A tile's dimensions are baked into its layout at construction time
        # (see ``_ItemWidget.__init__``), so a size change invalidates every
        # cached tile; otherwise entries unchanged since the last rebuild
        # (the common case: filtering as-you-type on a stable window list)
        # reuse their existing widget instead of being reconstructed.
        if (pw, ph) != self._tile_size:
            self._tile_cache = {}
            self._tile_size = (pw, ph)
        old_cache = self._tile_cache
        new_cache: dict[int, _ItemWidget] = {}
        tiles: list[_ItemWidget] = []
        for e in self._entries:
            pix = self._previews.get(e.window_id)
            signature = (e.title, e.icon_path, id(pix))
            cached = old_cache.get(e.window_id)
            if cached is not None and getattr(cached, "_signature", None) == signature:
                tile = cached
            else:
                tile = _ItemWidget(
                    e.icon_path,
                    e.title or e.app_name,
                    preview=pix,
                    preview_size=(pw, ph),
                    scale=self._scale,
                )
                tile._signature = signature  # type: ignore[attr-defined]
                tile.clicked.connect(lambda t=tile: self._on_tile_clicked(t))
                tile.hovered.connect(lambda wid=e.window_id: self._on_tile_hovered(wid))
            tile._window_entry = e  # type: ignore[attr-defined]
            new_cache[e.window_id] = tile
            tiles.append(tile)
        self._tile_cache = new_cache
        # Wrap rows against the real available width, not the container's
        # own (self-sizing) current width -- see the note in ``_relayout``.
        self._container.set_max_content_width(avail_w)
        self._container.set_tiles(tiles)

    def _on_tile_clicked(self, tile: _ItemWidget) -> None:
        e = getattr(tile, "_window_entry", None)
        if e is not None:
            self.activate_window.emit(e.window_id)


# ---------------------------------------------------------------------------
# Palette window
# ---------------------------------------------------------------------------


class PaletteWindow(QWidget):
    activate_window = Signal(int)  # window_id
    launch_app = Signal(str)        # bundle_path
    activate_app = Signal(str)     # bundle_id

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self._results: list[Result] = []
        self._window_provider: WindowProvider | None = None
        self._app_provider: AppProvider | None = None
        self._mru: MRUTracker | None = None
        self._wmru: WindowMRUTracker | None = None
        self._sources: list = load_sources()
        self._tile_previews_cache: dict[int, QPixmap] = {}
        self._all_windows: list = []  # WindowInfo list for overview filtering
        self._scale: float = ui_scale(config.ui_size)
        self._icon_cache: dict[str, QIcon] = {}
        self._pending_query: str = ""
        # Filtering rebuilds the results list and overview grid, so a fast
        # typist firing textChanged on every keystroke was doing that work
        # once per character. Coalesce bursts into one refresh a beat later.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(30)
        self._refresh_timer.timeout.connect(lambda: self._refresh(self._pending_query))

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        tokens = Tokens()
        self._tokens = tokens

        # --- Search field ---
        self._field = QLineEdit()
        self._field.setPlaceholderText("Search windows and applications…")
        self._field.setClearButtonEnabled(True)
        self._field.textChanged.connect(self._schedule_refresh)
        self._field.returnPressed.connect(self._activate_selected)
        self._field.textChanged.connect(self._reset_selection)

        # --- Results list ---
        # QListWidget is a QFrame subclass, so (unlike a plain QWidget) it
        # can paint its own stylesheet background directly -- give it the
        # same card treatment as #overviewBox instead of leaving it
        # "transparent" and dependent on the window behind it.
        self._list = QListWidget()
        self._list.setObjectName("resultsBox")
        self._list.setFocusPolicy(Qt.NoFocus)
        self._list.setUniformItemSizes(True)
        # Pin the list to the top of the body so it stays right below the
        # search field regardless of whether the overview grid is visible.
        # QListWidget's default vertical policy is Expanding; when the
        # overview is hidden that makes the layout allocate the full body
        # height to the list, and Qt then centers the (capped-at-160) widget
        # within that cell -- causing the results to float mid-screen.
        # Maximum tells the layout not to grow the list, so leftover space
        # falls to the bottom instead.
        self._list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        # --- Overview grid ---
        self._overview = _OverviewGrid(scale=self._scale)
        self._overview.activate_window.connect(self.activate_window)

        # --- Layout ---
        self._body = QWidget()
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(10)
        body_lay.addWidget(self._list, alignment=Qt.AlignTop)
        body_lay.addWidget(self._overview, stretch=1)
        body_lay.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(self._field)
        layout.addWidget(self._body, stretch=1)

        self._field.installEventFilter(self)
        # Catch mouse moves anywhere over the palette (even over child
        # tiles) so the first real move arms overview hover-highlighting;
        # enterEvents delivered to tiles that simply render under an
        # already-stationary cursor are otherwise treated as hover.
        QApplication.instance().installEventFilter(self)

        self.setStyleSheet(
            f"PaletteWindow{{background:{OVERLAY_BG};border-radius:16px;}}"
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # Plain QWidgets don't paint a stylesheet ``background`` on their own
        # -- only QFrame-derived widgets (or anything with this attribute)
        # do. Without it, the rounded dark backdrop above never rendered,
        # leaving the transparent list/search rows with nothing opaque
        # behind them so whatever was on screen showed straight through.
        self.setAttribute(Qt.WA_StyledBackground, True)

        # Apply the initial UI size scale (fonts, icon size, list height,
        # overview grid scale). Re-applied at the top of show_palette() so
        # a Settings-dialog save (live reload, no restart) takes effect the
        # next time the palette opens.
        self._apply_size_scale()

        self.hide()

    def _apply_size_scale(self) -> None:
        """Re-read ``self.config.ui_size`` and apply the scale to fonts,
        list icon size, list height, and the overview grid.

        Called once from ``__init__`` and again from ``show_palette()`` so
        a live config reload picks up the new size tier without rebuilding
        the widget tree.
        """
        scale = ui_scale(self.config.ui_size)
        self._scale = scale
        tokens = self._tokens

        field_font_px = max(11, round(15 * scale))
        field_pad_v = max(6, round(10 * scale))
        field_pad_h = max(10, round(14 * scale))
        self._field.setStyleSheet(
            f"QLineEdit{{background:{OVERLAY_PANEL_BG};border:1px solid {OVERLAY_FIELD_BORDER};"
            f"border-radius:12px;padding:{field_pad_v}px {field_pad_h}px;"
            f"font-size:{field_font_px}px;color:{OVERLAY_TEXT};"
            f"selection-background-color:{tokens.accent};}}"
            f"QLineEdit:focus{{border-color:{tokens.accent};}}"
        )

        list_font_px = max(10, round(13 * scale))
        item_pad_v = max(4, round(6 * scale))
        item_pad_h = max(6, round(8 * scale))
        self._list.setStyleSheet(
            f"#resultsBox{{background:{OVERLAY_PANEL_BG};border:none;border-radius:12px;"
            f"outline:0;color:{OVERLAY_TEXT};font-size:{list_font_px}px;padding:6px;}}"
            f"QListWidget::item{{padding:{item_pad_v}px {item_pad_h}px;border-radius:6px;}}"
            f"QListWidget::item:selected{{background:{tokens.accent};color:{tokens.accent_text};}}"
            f"QListWidget::item:hover:!selected{{background:{OVERLAY_HOVER};}}"
        )
        icon_px = max(16, round(20 * scale))
        self._list.setIconSize(QSize(icon_px, icon_px))
        self._list.setMaximumHeight(max(80, round(160 * scale)))

        self._overview.set_scale(scale)

    def set_providers(
        self,
        window_provider: WindowProvider,
        app_provider: AppProvider,
    ) -> None:
        self._window_provider = window_provider
        self._app_provider = app_provider

    def set_mru(
        self, mru: MRUTracker, window_mru: WindowMRUTracker
    ) -> None:
        """Share the app + per-window MRU trackers with the switcher.

        Ordering palette windows/apps by the same recency the switcher uses
        keeps the two views consistent: a window raised via the switcher
        surfaces at the top of the palette's results and overview, and vice
        versa.
        """
        self._mru = mru
        self._wmru = window_mru

    # ---- show / hide ----

    def show_palette(self) -> None:
        # Collection behavior must be set before positioning/showing:
        # flipping CanJoinAllSpaces on an already-positioned NSWindow makes
        # AppKit snap it onto the current main screen, discarding the frame.
        # The window *level* is applied after show() instead (Qt resets the
        # level during show) -- see raise_to_overlay_level().
        fullscreen = False
        if sys.platform == "darwin":
            from ..platform.macos.overlay import prepare_for_fullscreen

            fullscreen = prepare_for_fullscreen(self)
        # Pick up a live ui_size change from Settings (no app restart) so
        # the new scale applies the next time the palette opens.
        self._apply_size_scale()
        self._field.clear()
        self._capture_overview_previews()
        self._refresh_timer.stop()
        self._refresh("")
        current = self.screen() if hasattr(self, "screen") else None
        screen = target_screen(
            self.config.screen_preference, current, self._window_provider
        )
        if screen is not None:
            sg = screen.availableGeometry()
            # Fill most of the screen, leaving a gutter around the edges.
            gutter = 48
            w = sg.width() - gutter * 2
            h = sg.height() - gutter * 2
            self.setFixedSize(w, h)
            x = sg.center().x() - w // 2
            y = sg.center().y() - h // 2
            self.move(x, y)
        else:
            self.setFixedSize(900, 600)
        # setFixedSize() above changes the overview grid's allocated size,
        # but _refresh() already ran (and laid out tiles) against whatever
        # size the window had before this resize -- force one more pass now
        # that the real geometry is known.
        self._overview.relayout()
        # Disarm hover so a tile rendering under the cursor on open isn't
        # spuriously highlighted; armed again on the first real mouse move.
        self._overview.set_hover_armed(False)
        self.show()
        self.raise_()
        self.activateWindow()
        self._field.setFocus()
        # After show(): Qt has (re)set the window level from the window
        # flags, so re-assert the above-fullscreen level now, or the palette
        # stays below the fullscreen app's Space and never appears over it.
        if fullscreen:
            from ..platform.macos.overlay import raise_to_overlay_level

            raise_to_overlay_level(self)

    def hide_palette(self) -> None:
        self._refresh_timer.stop()
        self.hide()

    # ---- events ----

    def eventFilter(self, obj, event):
        if obj is self._field and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Escape:
                self.hide_palette()
                return True
            if key in (Qt.Key_Up, Qt.Key_Down):
                row = self._list.currentRow()
                n = self._list.count()
                if key == Qt.Key_Up:
                    row = row - 1 if row > 0 else n - 1
                else:
                    row = row + 1 if row < n - 1 else 0
                self._list.setCurrentRow(row)
                self._sync_overview_highlight()
                return True
        # Arm overview hover-highlighting on the first real mouse move over
        # the palette window. ``enterEvent`` fires for a tile that merely
        # renders under an already-stationary cursor on show; gating on an
        # actual move means no spurious highlight on open and correct
        # re-highlight once the user starts moving the mouse.
        if (
            event.type() == QEvent.MouseMove
            and self.isVisible()
            and not self._overview._hover_armed
        ):
            gpos = event.globalPosition().toPoint()
            if self.rect().contains(self.mapFromGlobal(gpos)):
                self._overview.set_hover_armed(True)
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide_palette()
            return
        super().keyPressEvent(event)

    def _reset_selection(self, _text: str) -> None:
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _sync_overview_highlight(self) -> None:
        """Mirror the results-list selection onto the overview grid.

        Highlights the thumbnail tile for the selected window result (if
        any) and clears the highlight otherwise.
        """
        row = self._list.currentRow()
        wid: int | None = None
        if 0 <= row < len(self._results):
            r = self._results[row]
            if r.is_window:
                wid = r.window_id
        self._overview.highlight_window(wid)

    # ---- preview capture ----

    def _capture_overview_previews(self) -> None:
        """Grab a screenshot for every open window once per palette show.

        Previews are cached for the lifetime of a single palette session
        (show -> hide); they are recaptured on the next show.
        """
        self._tile_previews_cache = {}
        if self._window_provider is None:
            return
        if not self.config.palette.overview_enabled:
            return
        for w in self._window_provider.list_windows():
            data = self._window_provider.capture_preview(w.window_id)
            if not data:
                continue
            pix = QPixmap()
            pix.loadFromData(data, "PNG")
            if not pix.isNull():
                self._tile_previews_cache[w.window_id] = pix

    def _order_windows_mru(self, windows: list) -> list:
        """Return ``windows`` ordered by per-window MRU (most recent first).

        Mirrors :meth:`SwitcherController._flat_window_entries` so the
        palette's overview and results share the switcher's recency order.
        Windows the tracker has never seen keep their original (provider)
        order, appended after known ones.
        """
        if self._wmru is None or not windows:
            return windows
        ordered_ids = self._wmru.order([w.window_id for w in windows])
        by_id = {w.window_id: w for w in windows}
        return [by_id[wid] for wid in ordered_ids if wid in by_id]

    def _order_apps_mru(self, apps: list) -> list:
        """Return ``apps`` ordered by app MRU (most recent first).

        Keys on ``bundle_id`` (falling back to ``name``), the same key the
        switcher and the palette's own activation slot use, so an app
        raised via either surface ranks first in both.
        """
        if self._mru is None or not apps:
            return apps
        keys = [a.bundle_id or a.name for a in apps]
        ordered_keys = self._mru.order(keys)
        by_key = {a.bundle_id or a.name: a for a in apps}
        return [by_key[k] for k in ordered_keys if k in by_key]

    # ---- refresh ----

    def _schedule_refresh(self, text: str) -> None:
        self._pending_query = text
        self._refresh_timer.start()

    def _icon_for_path(self, path: str) -> QIcon | None:
        icon = self._icon_cache.get(path)
        if icon is None:
            pix = QPixmap(path)
            if pix.isNull():
                return None
            icon = QIcon(pix)
            self._icon_cache[path] = icon
        return icon

    def _refresh(self, text: str) -> None:
        if self._window_provider is None or self._app_provider is None:
            return
        try:
            windows = self._window_provider.list_windows()
            apps = self._app_provider.list_apps()
        except Exception:
            return
        # Order windows and apps by the same recency the switcher uses so
        # the palette's results and overview mirror Alt+Tab ordering: the
        # most recently focused window/app ranks first. match()'s stable
        # sort preserves this MRU order among equal-scoring (or scoreless,
        # no-query) results, and _all_windows feeds the overview grid
        # which has no further ordering of its own.
        windows = self._order_windows_mru(windows)
        apps = self._order_apps_mru(apps)
        self._all_windows = windows
        self._results = match(text, windows, apps, self.config.palette)
        for src in self._sources:
            try:
                self._results.extend(src.search(text))
            except Exception:
                continue
        self._results = self._results[: self.config.palette.max_results]

        # --- Results list ---
        self._list.clear()
        for r in self._results:
            item = QListWidgetItem(r.name)
            item.setToolTip(r.subtitle)
            if r.icon_path:
                icon = self._icon_for_path(r.icon_path)
                if icon is not None:
                    item.setIcon(icon)
            item.setData(Qt.UserRole, r.name)
            self._list.addItem(item)
        if self._results:
            self._list.setCurrentRow(0)

        # --- Overview grid ---
        self._update_overview(text)
        self._sync_overview_highlight()

    def _update_overview(self, text: str) -> None:
        if not self.config.palette.overview_enabled:
            self._overview.hide()
            return
        q = text.strip().lower()
        entries: list[_WindowEntry] = []
        for w in self._all_windows:
            if w.is_minimized:
                continue
            label = w.window_title or w.app_name
            hay = f"{w.app_name} {w.window_title}".strip().lower()
            if q and q not in hay:
                continue
            icon = None
            if w.bundle_id and self._app_provider is not None:
                icon = self._app_provider.icon_for_bundle_id(w.bundle_id)
            entries.append(
                _WindowEntry(
                    window_id=w.window_id,
                    title=label,
                    app_name=w.app_name,
                    icon_path=icon,
                    bundle_id=w.bundle_id,
                )
            )
        if not entries:
            self._overview.hide()
            return
        self._overview.show()
        self._overview.set_entries(entries, self._tile_previews_cache)

    def _activate_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._results):
            return
        r = self._results[row]
        if r.is_window and r.window_id is not None:
            self.activate_window.emit(r.window_id)
        elif r.bundle_id and not r.bundle_path:
            self.activate_app.emit(r.bundle_id)
        elif r.bundle_path:
            self.launch_app.emit(r.bundle_path)
        self.hide_palette()
