"""Ordered rendering lifecycle and rate-limited per-curve evaluation diagnostics."""
from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt

from curvemole.gui.rendering import _optimise_plot_data_item, _split_dense_symbols

if TYPE_CHECKING:
    from curvemole.gui.plot import PlotWorkspace

PlotViewState = tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
]

_MASK_REGION_Z = -20.0
_MASK_BOUNDARY_Z = -10.0


def _capture_plot_view(workspace: PlotWorkspace) -> PlotViewState | None:
    """Capture the current main X/Y and residual Y ranges when a plot is visible."""
    if not workspace._data_items:
        return None
    main_range = workspace.view_box.viewRange()
    residual_range = workspace.residual_plot.getViewBox().viewRange()
    return (
        (float(main_range[0][0]), float(main_range[0][1])),
        (float(main_range[1][0]), float(main_range[1][1])),
        (float(residual_range[1][0]), float(residual_range[1][1])),
    )


def _restore_plot_view(workspace: PlotWorkspace, state: PlotViewState | None) -> None:
    """Restore a previously captured viewport without re-enabling auto range."""
    if state is None:
        return
    x_range, y_range, residual_y_range = state
    workspace.view_box.setRange(
        xRange=list(x_range),
        yRange=list(y_range),
        padding=0,
    )
    workspace.residual_plot.getViewBox().setRange(
        yRange=list(residual_y_range),
        padding=0,
    )


def _optimise_plot_rendering(workspace: PlotWorkspace) -> None:
    """Apply adaptive rendering to dense Overlay/Waterfall views after each refresh."""
    adaptive = workspace.display_mode.currentIndex() != 0
    for plot in (workspace.plot, workspace.residual_plot):
        for item in tuple(plot.listDataItems()):
            _split_dense_symbols(plot, item)
            _optimise_plot_data_item(item, adaptive=adaptive)
    # Dense rendering can add marker items after refresh configured placement.
    # Apply the same mouse rules to those new items before the next click.
    workspace._sync_placement_mouse_targets()


def _render_lightweight_mask_boundaries(workspace: PlotWorkspace) -> None:
    """Replace filled mask overlays with cheap, non-ranging dashed boundary lines."""
    for item in tuple(workspace.plot.items):
        if isinstance(item, pg.LinearRegionItem) and np.isclose(item.zValue(), _MASK_REGION_Z):
            workspace.plot.removeItem(item)

    project = workspace._project
    if project is None or not project.curves:
        return

    mode = workspace.display_mode.currentText()
    curves = workspace.displayed_curves()
    x_step = workspace.x_offset.value() if mode == workspace.tr("Waterfall") else 0.0
    pen = pg.mkPen(105, 105, 105, 155, width=1.0, style=Qt.PenStyle.DashLine)
    positions_seen: set[float] = set()

    for index, curve in enumerate(curves):
        x_offset = index * x_step
        for mask in curve.masks.values():
            for lower, upper in mask.ranges:
                lo, hi = sorted((float(lower), float(upper)))
                positions = (lo + x_offset,) if math.isclose(lo, hi) else (lo + x_offset, hi + x_offset)
                for position in positions:
                    if not np.isfinite(position):
                        continue
                    key = round(position, 12)
                    if key in positions_seen:
                        continue
                    positions_seen.add(key)
                    line = pg.InfiniteLine(
                        pos=position,
                        angle=90,
                        movable=False,
                        pen=pen,
                    )
                    line.setZValue(_MASK_BOUNDARY_Z)
                    line.setToolTip(workspace.tr("Masked / excluded region boundary"))
                    line._curvemole_mask_boundary = True
                    workspace.plot.addItem(line, ignoreBounds=True)



class RenderController:
    def __init__(self, workspace):
        self.workspace = workspace
        self.project = None
        self.errors = {}
        self.notified = {}

    def evaluation_failed(self, curve, error):
        message = str(error) or type(error).__name__
        self.errors[curve.id] = message
        previous, when = self.notified.get(curve.id, (None, -math.inf))
        now = time.monotonic()
        if message == previous or now - when < 10:
            return
        self.notified[curve.id] = (message, now)
        window = self.workspace.window()
        if hasattr(window, "_notify"):
            window._notify(f"{curve.name}: model/background evaluation failed: {message}", warning=True)

    def refresh(self, *args):
        from curvemole.gui.background_navigation import (
            _apply_background_aware_display,
            _background_cache,
            _masked_sample_renderer,
        )
        workspace = self.workspace
        if workspace._project is not self.project:
            self.project = workspace._project
            self.errors.clear()
            self.notified.clear()
        current_ids = {c.id for c in self.project.curves} if self.project else set()
        self.errors = {key: value for key, value in self.errors.items() if key in current_ids}
        self.notified = {key: value for key, value in self.notified.items() if key in current_ids}
        preserve = bool(getattr(workspace, "_preserve_view_on_refresh", True))
        workspace.__dict__.pop("_preserve_view_on_refresh", None)
        state = _capture_plot_view(workspace) if preserve else None
        workspace._lightweight_masks = True
        options = getattr(workspace, "view_options_controller", None)
        if options is not None:
            options.prepare()
        backgrounds = _background_cache(workspace)
        workspace._curvemole_background_cache = backgrounds
        try:
            workspace._refresh_scene(*args)
            _masked_sample_renderer(workspace)
            _apply_background_aware_display(workspace, backgrounds)
            _render_lightweight_mask_boundaries(workspace)
            _optimise_plot_rendering(workspace)
            _restore_plot_view(workspace, state)
            if state is None:
                workspace.auto_range()
        finally:
            workspace._render_models = None
            workspace._render_values = None
            workspace.__dict__.pop("_curvemole_background_cache", None)
