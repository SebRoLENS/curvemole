"""Capture the displayed scientific traces before an export dialog changes focus.

The snapshot owns plain NumPy arrays, so rendering does not touch Qt widgets.
Read source arrays instead of getData(): pyqtgraph getData() can already be
log-transformed, clipped or downsampled for display.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt

from curvemole.core.figure_export import PlotSnapshot, PlotTrace


def capture_plot_snapshot(workspace) -> PlotSnapshot:
    curves = {curve.id: workspace.curve_for_display(curve)
              for curve in workspace.displayed_curves()}
    traces = []

    def trace(item, label, kind, curve=None):
        if not item.isVisible() or item.xData is None or item.yData is None:
            return None
        pen = item.opts.get("pen")
        has_line = hasattr(pen, "style") and pen.style() != Qt.PenStyle.NoPen
        brush = pen if has_line else item.opts.get("symbolBrush")
        color = brush.color().name() if hasattr(brush, "color") else None
        symbol = item.opts.get("symbol")
        styles = {Qt.PenStyle.NoPen: "none", Qt.PenStyle.SolidLine: "-",
                  Qt.PenStyle.DashLine: "--", Qt.PenStyle.DotLine: ":",
                  Qt.PenStyle.DashDotLine: "-."}
        line_style = styles.get(pen.style(), "-") if hasattr(pen, "style") else "none"
        options = {}
        if kind == "data" and curve is not None and workspace.error_bars_toggle.isChecked():
            keep = ~curve.effective_mask
            minus, plus = curve.current_error_y_minus, curve.current_error_y_plus
            if minus is None:
                minus = plus = curve.current_sigma_y
            for key, values in (("y_error_minus", minus), ("y_error_plus", plus),
                                ("x_error", curve.current_sigma_x)):
                if values is not None:
                    options[key] = np.asarray(values)[keep].copy()
        return PlotTrace(label=label, x=np.asarray(item.xData).copy(),
                         y=np.asarray(item.yData).copy(), kind=kind, color=color,
                         line_style=line_style, marker=bool(symbol), **options)

    for curve_id, item in workspace._data_items.items():
        curve = curves.get(curve_id)
        captured = trace(item, curve.name if curve else str(curve_id), "data", curve)
        if captured is not None:
            traces.append(captured)
    for curve_id, item in workspace._sum_items.items():
        curve = curves.get(curve_id)
        captured = trace(item, f"{curve.name if curve else curve_id} · model", "fit")
        if captured is not None:
            traces.append(captured)
    for (curve_id, component_id), item in workspace._component_items.items():
        model = workspace._project.models.get(curve_id)
        component = next((part for part in model.components if part.id == component_id), None) if model else None
        curve = curves.get(curve_id)
        label = f"{curve.name if curve else curve_id} · {component.name if component else component_id}"
        captured = trace(item, label, "background" if component and component.is_background else "component")
        if captured is not None:
            traces.append(captured)

    for item in workspace.plot.listDataItems():
        if getattr(item, "_curvemole_masked_data", False):
            captured = trace(item, "Excluded observations", "masked")
            if captured is not None:
                traces.append(captured)

    residuals = []
    if workspace.residual_toggle.isChecked():
        for item in workspace.residual_plot.listDataItems():
            captured = trace(item, "", "residual")
            if captured is not None:
                residuals.append(captured)

    log_x = bool(workspace.plot.getAxis("bottom").logMode)
    log_y = bool(workspace.plot.getAxis("left").logMode)

    def data_range(values, logarithmic, inverted=False):
        if logarithmic:
            with np.errstate(over="ignore", under="ignore"):
                values = np.power(10.0, values)
        result = tuple(float(value) for value in values)
        return result[::-1] if inverted else result

    def axis_label(side):
        axis = workspace.plot.getAxis(side)
        return f"{axis.labelText} ({axis.labelUnits})" if axis.labelUnits else str(axis.labelText)

    masked_ranges = []
    # Regions already contain the waterfall x offset, just like the traces.
    for item in workspace.plot.items:
        if type(item).__name__ == "LinearRegionItem" and item.isVisible():
            masked_ranges.append(tuple(item.getRegion()))
    view = workspace.plot.viewRange()
    residual_view = workspace.residual_plot.viewRange()
    return PlotSnapshot(
        traces=traces, residuals=residuals,
        x_label=axis_label("bottom"), y_label=axis_label("left"),
        x_range=data_range(view[0], log_x, workspace.view_box.xInverted()),
        y_range=data_range(view[1], log_y, workspace.view_box.yInverted()),
        residual_range=data_range(residual_view[1], False, workspace.residual_plot.getViewBox().yInverted()) if residuals else None,
        log_x=log_x, log_y=log_y,
        title=f"{workspace._project.name} · {workspace.display_mode.currentText()}",
        masked_ranges=masked_ranges,
        theme="dark" if workspace.graphics.backgroundBrush().color().lightness() < 128 else "light",
    )
