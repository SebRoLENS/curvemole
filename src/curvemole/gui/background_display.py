"""Background-aware display helpers shared by the plot and its controllers.

These functions only read a PlotWorkspace and its project. They live apart from
background_navigation (which extends MainWindow and PlotWorkspace) so that the
plot, the render controller and the data-point editor can use them without
importing the main window, which formed an 11-module import cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pyqtgraph as pg

from curvemole.core.data import Curve
from curvemole.core.errors import DataValidationError
from curvemole.core.parameters import resolve_parameter_values
from curvemole.gui import mask_display as _mask_display
from curvemole.gui.plot_appearance import (
    colour_with_opacity,
    marker_for_curve,
    plot_mode_flags,
    qt_pen_style,
)

if TYPE_CHECKING:
    from curvemole.gui.plot import PlotWorkspace


def background_removed(workspace: PlotWorkspace, curve_id: str | None) -> bool:
    controller = getattr(workspace, "view_options_controller", None)
    if controller is not None:
        options = controller.for_curve(curve_id)
        if options.original:
            return False
        if options.background != "stored":
            return options.background == "subtract"
    return bool(getattr(workspace, "_background_subtracted_view", False))


def _displayed_curves(workspace: PlotWorkspace) -> tuple[list[Curve], float, float]:
    project = workspace._project
    if project is None or not project.curves:
        return [], 0.0, 0.0
    mode = workspace.display_mode.currentText()
    curves = [workspace.curve_for_display(curve) for curve in workspace.displayed_curves()]
    x_step = workspace.x_offset.value() if mode == workspace.tr("Waterfall") else 0.0
    y_step = workspace.y_offset.value() if mode == workspace.tr("Waterfall") else 0.0
    return curves, x_step, y_step


def _background_array(
    workspace: PlotWorkspace,
    curve: Curve,
    values: dict[str, float] | None = None,
) -> np.ndarray:
    project = workspace._project
    if project is None:
        return np.zeros_like(curve.y, dtype=float)
    model = project.models.get(curve.id)
    if model is None or not any(
        component.enabled and component.is_background for component in model.components
    ):
        return np.zeros_like(curve.y, dtype=float)
    try:
        resolved = values if values is not None else resolve_parameter_values(
            project.parameter_map(), paths=model.parameter_map(curve.id))
        background = np.asarray(
            model.background(
                curve.x,
                curve_id=curve.id,
                values=resolved,
                registry=workspace.registry,
            ),
            dtype=float,
        )
        usable = np.isfinite(curve.x) & np.isfinite(curve.y)
        if background.shape != curve.y.shape or np.any(usable & ~np.isfinite(background)):
            raise DataValidationError("The background returned invalid values.")
        return background
    except Exception as exc:
        controller = getattr(workspace, "render_controller", None)
        if controller is not None:
            controller.evaluation_failed(curve, exc)
        return np.zeros_like(curve.y, dtype=float)


def _background_cache(workspace: PlotWorkspace) -> dict[str, np.ndarray]:
    project = workspace._project
    curves, _, _ = _displayed_curves(workspace)
    if project is None:
        return {}
    values = getattr(workspace, "_live_parameter_values", None)
    if values is None:
        try:
            values = project.resolved_parameter_values()
        except Exception:
            values = None
    workspace._render_values = values
    workspace._render_models = {}
    backgrounds = {}
    for curve in curves:
        model = project.models.get(curve.id)
        try:
            if model is not None and model.components:
                scoped_values = values if values is not None else resolve_parameter_values(
                    project.parameter_map(), paths=model.parameter_map(curve.id))
                total, components = model.evaluate(curve.x, curve_id=curve.id, values=scoped_values,
                                                    registry=workspace.registry, components=True)
                workspace._render_models[curve.id] = (total, components)
                backgrounds[curve.id] = model.background(curve.x, curve_id=curve.id, values=scoped_values,
                    registry=workspace.registry, evaluated_components=components)
                usable = np.isfinite(curve.x) & np.isfinite(curve.y)
                if np.any(usable & (~np.isfinite(total) | ~np.isfinite(backgrounds[curve.id]))):
                    raise DataValidationError("The model or background returned non-finite values.")
            else:
                backgrounds[curve.id] = np.zeros_like(curve.y)
            controller = getattr(workspace, "render_controller", None)
            if controller is not None:
                controller.errors.pop(curve.id, None)
                controller.notified.pop(curve.id, None)
        except Exception as exc:
            controller = getattr(workspace, "render_controller", None)
            if controller is not None:
                controller.evaluation_failed(curve, exc)
            backgrounds[curve.id] = np.zeros_like(curve.y)
    return backgrounds


def _masked_sample_renderer(workspace: PlotWorkspace) -> None:
    # Render excluded samples using the current project appearance settings.
    curves, x_step, y_step = _displayed_curves(workspace)
    if not curves:
        return
    cache = getattr(workspace, "_curvemole_background_cache", {})
    appearance = workspace.plot_appearance()
    draw_lines, draw_points = plot_mode_flags(str(appearance["data_style"]))

    for index, curve in enumerate(curves):
        subtract = background_removed(workspace, curve.id)
        x = np.asarray(curve.x, dtype=float) + index * x_step
        y = np.asarray(curve.y, dtype=float)
        if subtract:
            y = y - np.asarray(cache.get(curve.id, np.zeros_like(y)), dtype=float)
        y = y + index * y_step
        masked = (
            np.asarray(curve.effective_mask, dtype=bool)
            & np.isfinite(x)
            & np.isfinite(y)
        )
        if not np.any(masked):
            continue
        # Masked samples keep their established neutral-grey visual identity.
        # Size and opacity remain customizable, but spectrum colours never leak into masks.
        colour = colour_with_opacity(
            "#777777",
            int(appearance["masked_opacity"]),
        )
        line_pen = pg.mkPen(
            colour,
            width=float(appearance["data_line_width"]),
            style=qt_pen_style(str(appearance["data_line_style"])),
        )
        symbol = marker_for_curve(appearance, index)
        isolated_x: list[float] = []
        isolated_y: list[float] = []
        runs = _mask_display._true_runs(masked)
        for run in runs:
            if run.size == 1:
                point = int(run[0])
                isolated_x.append(float(x[point]))
                isolated_y.append(float(y[point]))

        if draw_lines:
            for run in runs:
                if run.size == 1:
                    continue
                item = workspace.plot.plot(x[run], y[run], pen=line_pen)
                item._curvemole_masked_data = True
                item.curve_id = curve.id
                item.setZValue(4.0)

        # A single masked sample has no line segment, so it is always rendered
        # as a marker even when the experimental-data mode is Lines.
        if isolated_x and not draw_points:
            item = workspace.plot.plot(
                np.asarray(isolated_x, dtype=float),
                np.asarray(isolated_y, dtype=float),
                pen=None,
                symbol=symbol,
                symbolSize=float(appearance["masked_point_size"]),
                symbolBrush=pg.mkBrush(colour),
                symbolPen=None,
            )
            item._curvemole_masked_data = True
            item.curve_id = curve.id
            item.setZValue(4.0)

        if draw_points:
            item = workspace.plot.plot(
                x[masked],
                y[masked],
                pen=None,
                symbol=symbol,
                symbolSize=float(appearance["masked_point_size"]),
                symbolBrush=pg.mkBrush(colour),
                symbolPen=None,
            )
            item._curvemole_masked_data = True
            item.curve_id = curve.id
            item.setZValue(4.0)


def _label_position(x: np.ndarray, y: np.ndarray) -> tuple[float, float] | None:
    finite = np.isfinite(x) & np.isfinite(y)
    if not np.any(finite):
        return None
    finite_indices = np.flatnonzero(finite)
    values = y[finite]
    maximum = float(np.nanmax(values))
    tolerance = max(abs(maximum) * 1e-10, np.finfo(float).eps)
    maxima = finite_indices[np.isclose(values, maximum, rtol=1e-10, atol=tolerance)]
    index = (
        int(maxima[len(maxima) // 2])
        if len(maxima)
        else int(finite_indices[np.nanargmax(values)])
    )
    return float(x[index]), float(y[index])


def _shift_selected_peak_handle(
    workspace: PlotWorkspace,
    backgrounds: dict[str, np.ndarray],
    y_step: float,
) -> None:
    if background_removed(workspace, workspace._active_curve_id):
        return
    project = workspace._project
    curve_id = workspace._active_curve_id
    component_id = workspace._selected_component_id
    if project is None or not curve_id or not component_id:
        return
    if workspace.display_replays(project.dataset.curve(curve_id)):
        return
    model = project.models.get(curve_id)
    if model is None:
        return
    try:
        component = model.component(component_id)
        curve = project.dataset.curve(curve_id)
    except KeyError:
        return
    if component.is_background or component.operator != "add" or "center" not in component.parameters:
        return
    background = backgrounds.get(curve_id)
    if background is None or not np.any(background):
        return
    centre = float(component.parameters["center"].value)
    finite = np.isfinite(curve.x) & np.isfinite(background)
    if not np.any(finite):
        return
    indices = np.flatnonzero(finite)
    index = int(indices[np.argmin(np.abs(curve.x[finite] - centre))])
    baseline = float(background[index])
    if not np.isfinite(baseline) or baseline == 0.0:
        return
    for handle in workspace._handles:
        if isinstance(handle, pg.TargetItem):
            position = handle.pos()
            handle.setPos(float(position.x()), float(position.y()) + baseline)
            break


def _apply_background_aware_display(
    workspace: PlotWorkspace,
    backgrounds: dict[str, np.ndarray],
) -> None:
    project = workspace._project
    curves, x_step, y_step = _displayed_curves(workspace)
    if project is None or not curves:
        return

    # Data traces.
    # Re-anchor component labels after moving the dashed curves.
    if workspace._show_component_labels and workspace._component_labels:
        specs: list[tuple[Any, float, float]] = []
        for curve in curves:
            subtract = background_removed(workspace, curve.id)
            model = project.models.get(curve.id)
            if model is None:
                continue
            for component in model.components:
                key = (curve.id, component.id)
                if not component.enabled or key not in workspace._component_items:
                    continue
                label = workspace._component_labels_by_key.get(key)
                if label is None:
                    continue
                item = workspace._component_items[key]
                if subtract and component.is_background:
                    label.hide()
                    continue
                label.show()
                x_data, y_data = item.getOriginalDataset()
                if x_data is None or y_data is None:
                    continue
                position = _label_position(np.asarray(x_data), np.asarray(y_data))
                if position is None:
                    continue
                label.setPos(*position)
                specs.append((label, position[0], position[1]))
        workspace._component_label_specs = specs
        workspace._layout_component_labels()

    _shift_selected_peak_handle(workspace, backgrounds, y_step)
