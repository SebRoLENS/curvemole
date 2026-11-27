"""View state of the plot: ranges, axis scales and directions, autoscale.

ViewState frames data (View all / View unmasked), applies autoscale, log and
reversed axes, the view lock, and display offsets used for coordinates.
PlotWorkspace keeps delegating methods with the historical names.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject


class ViewState(QObject):
    def __init__(self, workspace: Any) -> None:
        super().__init__(workspace)
        self.workspace = workspace

    def _active_display_offsets(self) -> tuple[float, float]:
        workspace = self.workspace
        if workspace.display_mode.currentText() != workspace.tr("Waterfall") or workspace._project is None:
            return 0.0, 0.0
        curves = workspace.displayed_curves()
        index = next(
            (position for position, curve in enumerate(curves) if curve.id == workspace._active_curve_id),
            0,
        )
        return index * workspace.x_offset.value(), index * workspace.y_offset.value()

    def _from_display_coordinates(self, x: float, y: float) -> tuple[float, float]:
        workspace = self.workspace
        x_offset, y_offset = workspace._active_display_offsets()
        return x - x_offset, y - y_offset

    def _active_x_span(self) -> float:
        workspace = self.workspace
        if workspace._project is None or not workspace._active_curve_id:
            return 0.0
        curve = workspace._project.dataset.curve(workspace._active_curve_id)
        finite = curve.x[np.isfinite(curve.x)]
        return float(np.ptp(finite)) if len(finite) else 0.0

    def _active_y_span(self) -> float:
        workspace = self.workspace
        if workspace._project is None or not workspace._active_curve_id:
            return 0.0
        curve = workspace._project.dataset.curve(workspace._active_curve_id)
        finite = curve.y[np.isfinite(curve.y)]
        return float(np.ptp(finite)) if len(finite) else 0.0

    def set_log_x(self, enabled: bool) -> None:
        workspace = self.workspace
        workspace.plot.setLogMode(x=enabled, y=None)
        workspace.residual_plot.setLogMode(x=enabled, y=False)

    def set_log_y(self, enabled: bool) -> None:
        workspace = self.workspace
        workspace.plot.setLogMode(x=None, y=enabled)

    def set_reverse_x(self, enabled: bool) -> None:
        workspace = self.workspace
        workspace.view_box.invertX(enabled)

    def set_reverse_y(self, enabled: bool) -> None:
        workspace = self.workspace
        workspace.view_box.invertY(enabled)

    def set_view_locked(self, enabled: bool) -> None:
        workspace = self.workspace
        workspace._view_locked = enabled
        workspace._update_interaction_state()

    def auto_range(self) -> None:
        workspace = self.workspace
        workspace._fit_experimental_data(active_only=False)

    def view_active(self) -> None:
        workspace = self.workspace
        workspace._fit_experimental_data(active_only=True)

    def _fit_experimental_data(self, *, active_only: bool, series_id: str | None = None) -> None:
        # Never use scene/item bounds: adaptive rendering clips those to the
        # current viewport, while model extrapolation can dwarf the actual data.
        workspace = self.workspace
        from curvemole.gui.background_display import (
            _background_array,
            _displayed_curves,
            background_removed,
        )

        curves, x_step, y_step = _displayed_curves(workspace)
        series_curves = None
        if series_id is not None and workspace._project is not None:
            series = next((group for group in workspace._project.dataset.series if group.id == series_id), None)
            series_curves = {curve.id for curve in series.curves} if series is not None else set()
        log_x, log_y = workspace.plot.ctrl.logXCheck.isChecked(), workspace.plot.ctrl.logYCheck.isChecked()
        bounds = []
        for index, curve in enumerate(curves):
            if series_curves is not None and curve.id not in series_curves:
                continue
            x = np.asarray(curve.x, dtype=float) + index * x_step
            y = np.asarray(curve.y, dtype=float)
            if background_removed(workspace, curve.id):
                y = y - _background_array(workspace, curve)
            y = y + index * y_step
            valid = np.isfinite(x) & np.isfinite(y)
            if active_only:
                valid &= ~curve.effective_mask
            if log_x:
                valid &= x > 0
            if log_y:
                valid &= y > 0
            if not np.any(valid):
                continue
            # Include displayed CI endpoints in the experimental-data range.
            range_x, range_y = [x[valid]], [y[valid]]
            if workspace.error_bars_toggle.isChecked():
                from curvemole.gui.data_errors import y_error_widths
                widths = y_error_widths(curve)
                if widths is not None:
                    minus, plus = widths
                    keep = valid & np.isfinite(minus) & np.isfinite(plus) & (minus > 0) & (plus > 0)
                    range_y.extend((y[keep]-minus[keep], y[keep]+plus[keep]))
                if curve.current_sigma_x is not None:
                    sx = curve.current_sigma_x
                    keep = valid & np.isfinite(sx) & (sx > 0)
                    range_x.extend((x[keep]-sx[keep], x[keep]+sx[keep]))
            x, y = np.concatenate(range_x), np.concatenate(range_y)
            if log_x:
                x = np.log10(x[x > 0])
            if log_y:
                y = np.log10(y[y > 0])
            bounds.append((float(x.min()), float(x.max()), float(y.min()), float(y.max())))
        # Empty/all-masked data must not fall back to model bounds.
        if not bounds:
            return
        limits = np.asarray(bounds)
        def usable_range(lower: float, upper: float) -> tuple[float, float]:
            # pyqtgraph otherwise retains the previous (possibly huge) span
            # for a constant signal or a single remaining unmasked sample.
            if lower == upper:
                half_span = max(abs(lower) * 0.05, 0.5)
                return lower - half_span, upper + half_span
            return lower, upper

        workspace.view_box.disableAutoRange()
        residual_view = workspace.residual_plot.getViewBox()
        residual_view.disableAutoRange()
        workspace.view_box.setRange(
            xRange=usable_range(float(limits[:, 0].min()), float(limits[:, 1].max())),
            yRange=usable_range(float(limits[:, 2].min()), float(limits[:, 3].max())),
            padding=0.04,
        )
        # Residuals may determine only their own Y axis, never the linked X axis.
        workspace._residual_view_manual = False
        residual_view.enableAutoRange(axis=pg.ViewBox.YAxis)

    def _residual_range_changed_manually(self, *_: Any) -> None:
        workspace = self.workspace
        workspace._residual_view_manual = True

    def _apply_autoscale(self, *, series_id: str | None = None) -> None:
        workspace = self.workspace
        if series_id is not None:
            workspace._fit_experimental_data(
                active_only=workspace.autoscale_mode.currentIndex() == 1,
                series_id=series_id,
            )
        elif workspace.autoscale_mode.currentIndex() == 1:
            workspace.view_active()
        else:
            workspace.auto_range()

    def _autoscale_settings_changed(self, *_: Any) -> None:
        workspace = self.workspace
        enabled = workspace.autoscale_toggle.isChecked()
        workspace.autoscale_mode.setEnabled(enabled)
        if workspace._project is not None:
            workspace._project.ui_state["autoscale_enabled"] = enabled
            workspace._project.ui_state["autoscale_mode"] = (
                "active" if workspace.autoscale_mode.currentIndex() == 1 else "all"
            )
        if enabled:
            workspace._apply_autoscale()
