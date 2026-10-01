"""Live previews and reusable control points for manual-point components."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from contextlib import suppress
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF
from scipy.optimize import least_squares

from curvemole.core.dynamic_bounds import DynamicParameterCoordinates
from curvemole.core.errors import ConstraintError
from curvemole.core.initialization import PeakSuggestion, initialise_peak_component
from curvemole.core.models import Component
from curvemole.core.parameters import Parameter, resolve_parameter_values
from curvemole.gui import manual_points
from curvemole.gui.main_window import MainWindow
from curvemole.gui.plot import PlotWorkspace

_MANUAL_POINTS_KEY = "_manual_points"


def _normalise_points(points: object) -> list[tuple[float, float]]:
    return sorted((float(x), float(y)) for x, y in list(points))


def _stored_points(component: Component) -> list[tuple[float, float]]:
    raw = component.metadata.get(_MANUAL_POINTS_KEY)
    if raw:
        try:
            points = _normalise_points(raw)
        except (TypeError, ValueError):
            points = []
        if points:
            return points
    if component.function_id == "cubic_spline":
        nodes = list(component.metadata.get("x_nodes", []))
        result: list[tuple[float, float]] = []
        for index, x_value in enumerate(nodes):
            parameter = component.parameters.get(f"y{index}")
            if parameter is not None:
                result.append((float(x_value), float(parameter.value)))
        return result
    return []


def _set_stored_points(component: Component, points: list[tuple[float, float]]) -> None:
    component.metadata[_MANUAL_POINTS_KEY] = [
        [float(x_value), float(y_value)] for x_value, y_value in points
    ]


def _fitting_parameter_context(
    component: Component, parameter_context: Mapping[str, Parameter], curve_id: str,
) -> dict[str, Parameter]:
    """Clone the graph and hold other components at their current values."""
    prefix = f"{curve_id}.{component.id}."
    parameters = {
        path: Parameter.from_dict(parameter.to_dict())
        for path, parameter in parameter_context.items() if not path.startswith(prefix)
    }
    for parameter in parameters.values():
        parameter.fixed = True
    parameters.update({f"{prefix}{name}": parameter for name, parameter in component.parameters.items()})
    return parameters


def _generic_fit_component(
    component: Component,
    points: list[tuple[float, float]],
    *,
    registry: Any,
    free_only: bool,
    parameter_context: Mapping[str, Parameter] | None = None,
    curve_id: str | None = None,
) -> Component:
    fitted = Component.from_dict(copy.deepcopy(component.to_dict()))
    if not points:
        return fitted
    if free_only and any(parameter.link for parameter in fitted.parameters.values()) and parameter_context is None:
        raise ConstraintError("Linked manual control points require the spectrum parameter context.")

    x_values = np.asarray([point[0] for point in points], dtype=float)
    y_values = np.asarray([point[1] for point in points], dtype=float)
    definition = registry.get(fitted.function_id)

    if fitted.function_id == "linear":
        slope = fitted.parameters["slope"]
        intercept = fitted.parameters["intercept"]
        if len(points) >= 2 and (not free_only or slope.is_free or intercept.is_free):
            best_slope, best_intercept = np.polyfit(x_values, y_values, 1)
            if not free_only or slope.is_free:
                slope.value = float(np.clip(best_slope, slope.minimum, slope.maximum))
            if not free_only or intercept.is_free:
                intercept.value = float(
                    np.clip(best_intercept, intercept.minimum, intercept.maximum)
                )
        elif not free_only or intercept.is_free:
            value = float(y_values[0] - slope.value * x_values[0])
            intercept.value = float(np.clip(value, intercept.minimum, intercept.maximum))
    elif fitted.function_id == "constant":
        offset = fitted.parameters["offset"]
        if not free_only or offset.is_free:
            offset.value = float(np.clip(np.mean(y_values), offset.minimum, offset.maximum))
    elif definition.kind == "peak" and not free_only:
        baseline = float(np.min(y_values))
        peak_index = int(np.argmax(np.abs(y_values - baseline)))
        span = max(float(np.ptp(x_values)), 1.0)
        suggestion = PeakSuggestion(
            x=float(x_values[peak_index]),
            height=float(y_values[peak_index] - baseline) or float(y_values[peak_index]),
            fwhm=max(span / 2.0, np.finfo(float).eps),
            prominence=float(abs(y_values[peak_index] - baseline)),
            sign=1,
        )
        with suppress(Exception):
            initialise_peak_component(fitted, suggestion, registry=registry)

    names = [
        name
        for name, parameter in fitted.parameters.items()
        if not free_only or parameter.is_free
    ]
    if not names:
        return fitted

    context = None
    coordinates = None
    if parameter_context is not None:
        if not curve_id:
            raise ConstraintError("A spectrum is required to resolve manual control point links.")
        context = _fitting_parameter_context(fitted, parameter_context, curve_id)
        paths = [f"{curve_id}.{fitted.id}.{name}" for name in names]
        coordinates = DynamicParameterCoordinates(context, paths)
        initial = coordinates.initial()
        lower, upper = coordinates.bounds
    else:
        initial = np.asarray([fitted.parameters[name].value for name in names], dtype=float)
        lower = np.asarray([fitted.parameters[name].minimum for name in names], dtype=float)
        upper = np.asarray([fitted.parameters[name].maximum for name in names], dtype=float)
        initial = np.minimum(np.maximum(initial, lower), upper)
    scale = max(float(np.ptp(y_values)), float(np.max(np.abs(y_values))), 1.0)

    def physical_values(values: np.ndarray) -> dict[str, float]:
        if coordinates is not None:
            for path, value in coordinates.decode(values).items():
                context[path].value = float(value)
            resolved = resolve_parameter_values(context)
            return {name: resolved[f"{curve_id}.{fitted.id}.{name}"] for name in fitted.parameters}
        mapping = {name: parameter.value for name, parameter in fitted.parameters.items()}
        mapping.update({name: float(value) for name, value in zip(names, values, strict=True)})
        return mapping

    def residual(values: np.ndarray) -> np.ndarray:
        try:
            mapping = physical_values(values)
            calculated = definition.evaluate(x_values, mapping, fitted.metadata)
        except Exception:
            return np.full(len(x_values), 1e12, dtype=float)
        result = (np.asarray(calculated, dtype=float) - y_values) / scale
        if not np.all(np.isfinite(result)):
            return np.full(len(x_values), 1e12, dtype=float)
        return result

    try:
        result = least_squares(
            residual,
            initial,
            bounds=(lower, upper),
            max_nfev=1500,
        )
    except Exception:
        return Component.from_dict(copy.deepcopy(component.to_dict())) if context is not None else fitted
    if result.success and np.all(np.isfinite(result.x)):
        final_values = physical_values(result.x)
        for name, value in final_values.items():
            parameter = fitted.parameters[name]
            parameter.value = float(np.clip(value, parameter.minimum, parameter.maximum))
            parameter.standard_error = None
            parameter.ci_low = None
            parameter.ci_high = None
    return fitted


def preview_component_from_points(
    component: Component,
    points: object,
    *,
    registry: Any,
) -> Component | None:
    """Return the current best component estimate for any non-empty point set."""
    selected = _normalise_points(points)
    if not selected:
        return None
    if component.function_id == "cubic_spline":
        if len(selected) < 2:
            return None
        fitted = Component.from_dict(copy.deepcopy(component.to_dict()))
        manual_points.initialise_component_from_points(
            fitted,
            selected,
            registry=registry,
        )
        _set_stored_points(fitted, selected)
        return fitted
    fitted = _generic_fit_component(
        component,
        selected,
        registry=registry,
        free_only=False,
    )
    _set_stored_points(fitted, selected)
    return fitted


def _preview_x(workspace: PlotWorkspace, point_x: np.ndarray) -> np.ndarray:
    curve = workspace._project.dataset.curve(workspace._active_curve_id)
    finite = np.asarray(curve.x[np.isfinite(curve.x)], dtype=float)
    if not len(finite):
        return point_x
    lower = float(min(np.min(finite), np.min(point_x)))
    upper = float(max(np.max(finite), np.max(point_x)))
    if math.isclose(lower, upper):
        span = max(abs(lower) * 0.1, 1.0)
        lower -= span
        upper += span
    count = max(400, min(4000, len(finite) * 2))
    return np.linspace(lower, upper, count)


def _render_live_manual_preview(workspace: PlotWorkspace) -> None:
    workspace._clear_placement_items()
    if (
        workspace._project is None
        or not workspace._active_curve_id
        or not workspace._spline_points
    ):
        return

    selected = _normalise_points(workspace._spline_points)
    x_offset, y_offset = workspace._active_display_offsets()
    node_x = np.asarray([point[0] for point in selected], dtype=float)
    node_y = np.asarray([point[1] for point in selected], dtype=float)

    markers = workspace.plot.plot(
        node_x + x_offset,
        node_y + y_offset,
        pen=None,
        symbol="o",
        symbolSize=9,
        symbolBrush=pg.mkBrush("#009E73"),
        symbolPen=pg.mkPen("#ffffff", width=1),
    )
    workspace._placement_items.append(markers)

    owner = workspace.window()
    component = getattr(owner, "_pending_component", None)
    if component is None:
        return

    preview_x = _preview_x(workspace, node_x)
    if component.function_id == "cubic_spline" and len(selected) == 1:
        preview_y = np.full_like(preview_x, node_y[0], dtype=float)
    else:
        fitted = preview_component_from_points(
            component,
            selected,
            registry=workspace.registry,
        )
        if fitted is None:
            return
        definition = workspace.registry.get(fitted.function_id)
        values = {
            name: parameter.value for name, parameter in fitted.parameters.items()
        }
        try:
            preview_y = np.asarray(
                definition.evaluate(preview_x, values, fitted.metadata),
                dtype=float,
            )
        except Exception:
            return
    finite = np.isfinite(preview_x) & np.isfinite(preview_y)
    if not np.any(finite):
        return
    line = workspace.plot.plot(
        preview_x[finite] + x_offset,
        preview_y[finite] + y_offset,
        pen=pg.mkPen("#009E73", width=2),
    )
    workspace._placement_items.append(line)


def _point_is_movable(component: Component, point_index: int) -> bool:
    if component.function_id == "cubic_spline":
        parameter = component.parameters.get(f"y{point_index}")
        return bool(parameter is not None and parameter.is_free)
    return any(parameter.is_free for parameter in component.parameters.values())


def _replace_component_state(target: Component, source: Component) -> None:
    target.metadata = copy.deepcopy(source.metadata)
    target.parameters = {
        name: Parameter.from_dict(parameter.to_dict())
        for name, parameter in source.parameters.items()
    }


def _fit_after_generic_point_drag(
    component: Component,
    points: list[tuple[float, float]],
    *,
    registry: Any,
    parameter_context: Mapping[str, Parameter] | None = None,
    curve_id: str | None = None,
) -> Component:
    fitted = _generic_fit_component(
        component,
        points,
        registry=registry,
        free_only=True,
        parameter_context=parameter_context,
        curve_id=curve_id,
    )
    _set_stored_points(fitted, points)
    return fitted


def _fit_after_spline_point_drag(
    component: Component,
    points: list[tuple[float, float]],
    point_index: int,
    new_point: tuple[float, float],
    *,
    registry: Any,
    parameter_context: Mapping[str, Parameter] | None = None,
    curve_id: str | None = None,
) -> tuple[Component, list[tuple[float, float]]]:
    old_points = _stored_points(component)
    records: list[tuple[float, float, Parameter | None]] = []
    for index, point in enumerate(old_points):
        parameter = component.parameters.get(f"y{index}")
        records.append((point[0], point[1], copy.deepcopy(parameter)))

    x_value, y_value = new_point
    _, _, moved_parameter = records[point_index]
    records[point_index] = (float(x_value), float(y_value), moved_parameter)
    records.sort(key=lambda item: item[0])
    if any(
        math.isclose(left[0], right[0], rel_tol=0.0, abs_tol=np.finfo(float).eps)
        for left, right in zip(records, records[1:], strict=False)
    ):
        return Component.from_dict(copy.deepcopy(component.to_dict())), old_points

    fitted = Component.from_dict(copy.deepcopy(component.to_dict()))
    ordered = [(x_point, y_point) for x_point, y_point, _ in records]
    fitted.metadata["x_nodes"] = [point[0] for point in ordered]
    new_parameters: dict[str, Parameter] = {}
    for index, (_, y_point, old_parameter) in enumerate(records):
        if old_parameter is None:
            continue
        old_parameter.name = f"y{index}"
        old_parameter.value = float(
            np.clip(y_point, old_parameter.minimum, old_parameter.maximum)
        )
        old_parameter.standard_error = None
        old_parameter.ci_low = None
        old_parameter.ci_high = None
        new_parameters[f"y{index}"] = old_parameter
    expected = registry.get("cubic_spline").make_parameters(
        {f"y{index}": point[1] for index, point in enumerate(ordered)},
        fitted.metadata,
    )
    for name, parameter in expected.items():
        new_parameters.setdefault(name, parameter)
    fitted.parameters = new_parameters
    if parameter_context is not None:
        if not curve_id:
            raise ConstraintError("A spectrum is required to resolve manual control point links.")
        moved_index = next(index for index, (_, _, parameter) in enumerate(records)
                           if parameter is moved_parameter)
        moved_name = f"y{moved_index}"
        context = _fitting_parameter_context(fitted, parameter_context, curve_id)
        prefix = f"{curve_id}.{fitted.id}."
        for name in fitted.parameters:
            context[f"{prefix}{name}"] = Parameter.from_dict(fitted.parameters[name].to_dict())
            if name != moved_name:
                context[f"{prefix}{name}"].fixed = True
        path = f"{prefix}{moved_name}"
        free_paths = [path] if context[path].is_free else []
        coordinates = DynamicParameterCoordinates(context, free_paths)
        for parameter_path, value in coordinates.decode(coordinates.initial()).items():
            context[parameter_path].value = value
        resolved = resolve_parameter_values(context)
        for name, parameter in fitted.parameters.items():
            parameter.value = resolved[f"{prefix}{name}"]
        ordered = [(x, fitted.parameters[f"y{index}"].value) for index, (x, _) in enumerate(ordered)]
    elif any(parameter.link and parameter.link_relation != "equal" for parameter in fitted.parameters.values()):
        raise ConstraintError("Linked manual control points require the spectrum parameter context.")
    _set_stored_points(fitted, ordered)
    return fitted, ordered


def _apply_manual_point_drag(
    window: MainWindow,
    component_id: str,
    point_index: int,
    x_value: float,
    y_value: float,
) -> None:
    if not window.active_curve_id:
        return
    component = window.project.model_for(window.active_curve_id).component(component_id)
    points = _stored_points(component)
    if not points or point_index >= len(points):
        return
    if not _point_is_movable(component, point_index):
        window._fixed_notice()
        window.refresh_all()
        return

    new_point = (float(x_value), float(y_value))
    parameter_context = window.project.parameter_map()
    try:
        if component.function_id == "cubic_spline":
            fitted, _ = _fit_after_spline_point_drag(
                component,
                points,
                point_index,
                new_point,
                registry=window.registry,
                parameter_context=parameter_context,
                curve_id=window.active_curve_id,
            )
        else:
            updated_points = list(points)
            updated_points[point_index] = new_point
            updated_points.sort()
            fitted = _fit_after_generic_point_drag(
                component,
                updated_points,
                registry=window.registry,
                parameter_context=parameter_context,
                curve_id=window.active_curve_id,
            )
        prefix = f"{window.active_curve_id}.{component.id}."
        staged = {path: parameter for path, parameter in parameter_context.items() if not path.startswith(prefix)}
        staged.update({f"{prefix}{name}": parameter for name, parameter in fitted.parameters.items()})
        resolve_parameter_values(staged)
    except Exception as exc:
        window._show_error(window.tr("Manual control point"), exc)
        window.refresh_all()
        return

    before = component.to_dict()
    after = fitted.to_dict()
    if before == after:
        window.refresh_all()
        return

    def restore(state: dict[str, Any]) -> None:
        restored = Component.from_dict(copy.deepcopy(state))
        _replace_component_state(component, restored)

    window._push_change(
        window.tr("Drag manual control point"),
        lambda: restore(after),
        lambda: restore(before),
    )


def _finish_control_point_drag(
    workspace: PlotWorkspace,
    component_id: str,
    point_index: int,
    item: pg.TargetItem,
    x_offset: float,
    y_offset: float,
) -> None:
    owner = workspace.window()
    if not isinstance(owner, MainWindow):
        return
    position: QPointF = item.pos()
    _apply_manual_point_drag(
        owner,
        component_id,
        point_index,
        float(position.x() - x_offset),
        float(position.y() - y_offset),
    )


def _install_live_manual_points() -> None:
    if getattr(PlotWorkspace, "_curvemole_live_manual_points", False):
        return

    original_render = PlotWorkspace._render_placement_preview
    original_add_handles = PlotWorkspace._add_component_handles
    original_finished = MainWindow._graphical_spline_placed

    def render(workspace: PlotWorkspace) -> None:
        if getattr(workspace, "_manual_points_active", False):
            _render_live_manual_preview(workspace)
        else:
            original_render(workspace)
        if workspace._placement_mode is not None:
            workspace._sync_placement_mouse_targets()

    def add_handles(
        workspace: PlotWorkspace,
        curve: Any,
        model: Any,
        x_offset: float,
        y_offset: float,
    ) -> None:
        try:
            component = model.component(workspace._selected_component_id)
        except KeyError:
            return
        points = _stored_points(component)
        if not points:
            original_add_handles(workspace, curve, model, x_offset, y_offset)
            return

        for index, (x_value, y_value) in enumerate(points):
            movable = _point_is_movable(component, index)
            target = pg.TargetItem(
                pos=(x_value + x_offset, y_value + y_offset),
                size=11,
                movable=movable,
                pen=pg.mkPen("#009E73", width=2),
                brush=pg.mkBrush(255, 255, 255, 200),
            )
            target.setToolTip(
                workspace.tr(
                    "Manual control point. Unlock the relevant parameter(s) to drag it in x and y."
                )
            )
            workspace.plot.addItem(target)
            if movable:
                target.sigPositionChangeFinished.connect(
                    lambda item,
                    component_id=component.id,
                    point=index,
                    xo=x_offset,
                    yo=y_offset: _finish_control_point_drag(
                        workspace,
                        component_id,
                        point,
                        item,
                        xo,
                        yo,
                    )
                )
            workspace._handles.append(target)

    def finished(window: MainWindow, points: object) -> None:
        if bool(getattr(window, "_pending_manual_points", False)):
            component = getattr(window, "_pending_component", None)
            if component is not None:
                _set_stored_points(component, _normalise_points(points))
        original_finished(window, points)

    PlotWorkspace._render_placement_preview = render
    PlotWorkspace._add_component_handles = add_handles
    PlotWorkspace._curvemole_live_manual_points = True
    MainWindow._graphical_spline_placed = finished
    MainWindow._curvemole_live_manual_points = True


_ORIGINAL_INSTALL = manual_points.install_manual_point_support


def install_manual_point_support_with_live_controls() -> None:
    """Install normal manual-point support, then add live previews and reusable handles."""
    _ORIGINAL_INSTALL()
    _install_live_manual_points()


manual_points.install_manual_point_support = install_manual_point_support_with_live_controls
