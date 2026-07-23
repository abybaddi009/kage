"""Overview hover-highlighting must arm only on a real mouse move.

Symptoms this guards against:
1. Opening the palette under a stationary cursor must NOT highlight the tile
   that happens to render beneath it -- ``enterEvent`` is delivered to that
   tile at show time but should be ignored until the user actually moves.
2. Once the user moves the mouse, hover-highlighting must work again.

The fix gates ``_OverviewGrid``'s hover handler behind ``_hover_armed``,
disarmed on palette show and armed by ``PaletteWindow``'s event filter on
the first real ``MouseMove`` over the window. Keyboard-driven
``highlight_window`` calls (arrow-key navigation) are unaffected.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from alttabber.core.palette import _OverviewGrid
from alttabber.core.switcher import _WindowEntry


def _entry(window_id: int, title: str = "win") -> _WindowEntry:
    return _WindowEntry(
        window_id=window_id,
        title=title,
        app_name="app",
        icon_path=None,
        bundle_id="com.app",
    )


def _grid_with_entries(qapp) -> _OverviewGrid:
    grid = _OverviewGrid(scale=1.0)
    grid.resize(800, 600)
    entries = [_entry(1, "one"), _entry(2, "two")]
    grid.set_entries(entries)
    qapp.processEvents()
    return grid


def _selected_id(grid: _OverviewGrid) -> int | None:
    for i in range(grid._container.count()):
        tile = grid._container.tile(i)
        if getattr(tile, "_selected", False):
            e = getattr(tile, "_window_entry", None)
            return e.window_id if e is not None else None
    return None


def test_hover_disarmed_by_default_ignores_enter(qapp):
    grid = _grid_with_entries(qapp)
    # A freshly built grid is disarmed (as it is after a palette show).
    assert grid._hover_armed is False

    tile = grid._container.tile(0)
    # Simulate the spurious enterEvent Qt delivers to a tile that renders
    # under an already-stationary cursor on show.
    tile.enterEvent(None)

    assert _selected_id(grid) is None, "tile highlighted on show without a mouse move"


def test_keyboard_highlight_still_works_when_disarmed(qapp):
    grid = _grid_with_entries(qapp)
    assert grid._hover_armed is False

    grid.highlight_window(2)

    assert _selected_id(grid) == 2


def test_armed_hover_highlights_target_tile(qapp):
    grid = _grid_with_entries(qapp)
    grid.set_hover_armed(True)

    grid._container.tile(1).enterEvent(None)

    assert _selected_id(grid) == 2


def test_arming_then_enter_highlights(qapp):
    grid = _grid_with_entries(qapp)
    assert grid._hover_armed is False

    # Disarmed enter is a no-op.
    grid._container.tile(1).enterEvent(None)
    assert _selected_id(grid) is None

    # Arm (as PaletteWindow.eventFilter would on the first real move).
    grid.set_hover_armed(True)
    grid._container.tile(1).enterEvent(None)

    assert _selected_id(grid) == 2


def test_disarm_clears_hover_gating(qapp):
    grid = _grid_with_entries(qapp)
    grid.set_hover_armed(True)
    grid._container.tile(0).enterEvent(None)
    assert _selected_id(grid) == 1

    # Re-disarm: subsequent enters are ignored again.
    grid.set_hover_armed(False)
    grid._container.tile(1).enterEvent(None)
    assert _selected_id(grid) == 1


def test_eventfilter_arms_on_real_mouse_move_over_palette(qapp):
    """PaletteWindow.eventFilter arms the overview on the first MouseMove
    that lands inside the palette window; moves outside don't."""
    from types import SimpleNamespace

    from alttabber.backends.base import AppInfo, AppProvider, WindowInfo, WindowProvider
    from alttabber.core.palette import PaletteWindow

    class _WP(WindowProvider):
        def list_windows(self):
            return []

        def activate_window(self, window_id):
            return True

        def activate_app(self, bundle_id):
            return True

        def capture_preview(self, window_id):
            return None

    class _AP(AppProvider):
        def list_apps(self):
            return []

        def launch(self, bundle_path):
            return True

        def icon_for_bundle_id(self, bundle_id):
            return None

    cfg = SimpleNamespace(
        ui_size="medium", screen_preference="active",
        palette=SimpleNamespace(
            max_results=50, overview_enabled=False, windows_first=True
        ),
    )
    pal = PaletteWindow(cfg)
    pal.set_providers(_WP(), _AP())
    # Position the palette somewhere known and make it visible so the
    # isVisible() gate in eventFilter passes.
    pal.move(100, 100)
    pal.setFixedSize(400, 300)
    pal.show()
    qapp.processEvents()
    assert pal._overview._hover_armed is False


    # Move inside the palette: arm.
    inside = QMouseEvent(
        QMouseEvent.MouseMove,
        QPointF(50, 50),
        QPointF(150, 150),
        Qt.NoButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    pal.eventFilter(pal._field, inside)
    assert pal._overview._hover_armed is True

    # Re-disarm and move outside the palette: stays disarmed.
    pal._overview.set_hover_armed(False)
    outside = QMouseEvent(
        QMouseEvent.MouseMove,
        QPointF(10, 10),
        QPointF(10, 10),  # global well outside (100,100,400x300)
        Qt.NoButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    pal.eventFilter(pal._field, outside)
    assert pal._overview._hover_armed is False

    pal.hide()
