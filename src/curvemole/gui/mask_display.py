"""Lightweight, visible rendering for samples excluded from fitting."""

from __future__ import annotations

from typing import Any

import numpy as np
import pyqtgraph as pg

from curvemole.gui.plot import PlotWorkspace

_MASKED_DATA_Z = 4.0
_MASKED_GREY = (125, 125, 125, 190)


def _true_runs(mask: np.ndarray) -> list[np.ndarray]:
    """Return contiguous runs of true indices without copying source data."""
    indices = np.flatnonzero(mask)
    if indices.size == 0:
        return []
    split_at = np.flatnonzero(np.diff(indices) > 1) + 1
    return [run for run in np.split(indices, split_at) if run.size]


def _render_masked_samples(workspace: PlotWorkspace) -> None:
    """Draw excluded samples as cheap grey lines, with tiny markers only for isolated points."""
    project = workspace._project
    if project is None or not project.curves:
        return

    mode = workspace.display_mode.currentText()
    if mode == workspace.tr("Single"):
        curves = [project.dataset.curve(workspace._active_curve_id)] if workspace._active_curve_id else []
    else:
        curves = [curve for curve in project.curves if curve.visible]

    x_step = workspace.x_offset.value() if mode == workspace.tr("Waterfall") else 0.0
    y_step = workspace.y_offset.value() if mode == workspace.tr("Waterfall") else 0.0
    line_pen = pg.mkPen(*_MASKED_GREY, width=1.0)
    marker_brush = pg.mkBrush(*_MASKED_GREY)

    for index, curve in enumerate(curves):
        x = np.asarray(curve.x, dtype=float) + index * x_step
        y = np.asarray(curve.y, dtype=float) + index * y_step
        masked = np.asarray(curve.effective_mask, dtype=bool) & np.isfinite(x) & np.isfinite(y)
        isolated_x: list[float] = []
        isolated_y: list[float] = []

        for run in _true_runs(masked):
            if run.size == 1:
                point = int(run[0])
                isolated_x.append(float(x[point]))
                isolated_y.append(float(y[point]))
                continue

            item = workspace.plot.plot(x[run], y[run], pen=line_pen)
            item._curvemole_masked_data = True
            item.setZValue(_MASKED_DATA_Z)

        if isolated_x:
            item = workspace.plot.plot(
                np.asarray(isolated_x, dtype=float),
                np.asarray(isolated_y, dtype=float),
                pen=None,
                symbol="o",
                symbolSize=3.5,
                symbolBrush=marker_brush,
                symbolPen=None,
            )
            item._curvemole_masked_data = True
            item.setZValue(_MASKED_DATA_Z)


def _install_masked_sample_rendering() -> None:
    """Add lightweight masked-data rendering around the standard plot refresh."""
    if getattr(PlotWorkspace, "_curvemole_shows_masked_samples", False):
        return

    original_refresh = PlotWorkspace.refresh

    def refresh(workspace: PlotWorkspace, *args: Any) -> None:
        original_refresh(workspace, *args)
        _render_masked_samples(workspace)

    PlotWorkspace.refresh = refresh
    PlotWorkspace._curvemole_shows_masked_samples = True


_install_masked_sample_rendering()
