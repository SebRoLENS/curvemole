"""Live previews and reusable control points for manual-point components."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF

from curvemole.core.dynamic_bounds import DynamicParameterCoordinates
from curvemole.core.errors import ConstraintError, DataValidationError
from curvemole.core.models import Component
from curvemole.core.parameters import Parameter, resolve_parameter_values
from curvemole.gui.main_window import MainWindow
from curvemole.gui.plot import PlotWorkspace
from curvemole.gui.point_initialisation import (  # noqa: E402,F401 - compatibility re-exports
    _MANUAL_POINTS_KEY,
    _fitting_parameter_context,
    _generic_fit_component,
    _normalise_points,
    _set_stored_points,
    _stored_points,
    preview_component_from_points,
)


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
    workspace._manual_points_error = ""
    workspace._manual_points_configuration = ""
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
        try:
            editor = getattr(owner, "_function_point_editor", None)
            if editor is not None and editor.active:
                fitted = editor.preview(selected)
            else:
                fitted = preview_component_from_points(
                    component, selected, registry=workspace.registry,
                )
        except Exception as exc:
            workspace._manual_points_error = str(exc)
            return
        if fitted is None:
            return
        definition = workspace.registry.get(fitted.function_id)
        workspace._manual_points_configuration = "; ".join(
            f"{option.label}: {fitted.metadata[option.name]}"
            for option in definition.configuration_specs if option.from_points is not None
        )
        if definition.has_point_configuration and len(selected) > 1:
            # A growing interpolant must not expand the viewport through extrapolation.
            preview_x = np.linspace(float(node_x.min()), float(node_x.max()), len(preview_x))
        if definition.kind == "peak" and len(selected) > 1:
            # Keep narrow peaks visible even on a spectrum spanning a wide range.
            preview_x = np.unique(np.concatenate((
                preview_x, node_x,
                np.linspace(float(node_x.min()), float(node_x.max()), 400),
            )))
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
    curve_id = window.active_curve_id
    component = window.project.model_for(curve_id).component(component_id)
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
        current = window.project.model_for(curve_id).component(component_id)
        _replace_component_state(current, restored)

    window._push_change(
        window.tr("Drag manual control point"),
        lambda: restore(after),
        lambda: restore(before),
        modified_curve_ids={curve_id},
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
        editor = getattr(workspace.window(), "_function_point_editor", None)
        if editor is not None and editor.active and editor.draft.id == component.id:
            return
        points = _stored_points(component)
        try:
            definition = workspace.registry.get(component.function_id)
        except DataValidationError:
            return
        if not points or (definition.kind == "peak" and "center" in component.parameters):
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
