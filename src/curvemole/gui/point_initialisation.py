"""Initialise and preview model functions from points placed on the plot.

Pure functions shared by graphical placement, the point editor and live
previews. They have no Qt dependency and do not import the main window, so the
modules that extend MainWindow and PlotWorkspace can all use them without
forming an import cycle.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Iterable, Mapping
from contextlib import suppress
from typing import Any

import numpy as np

from curvemole.core.dynamic_bounds import DynamicParameterCoordinates
from curvemole.core.errors import ConstraintError, DataValidationError
from curvemole.core.initialization import (
    PeakSuggestion,
    initialise_peak_component,
    initialise_spline_component,
)
from curvemole.core.models import Component
from curvemole.core.parameters import Parameter, resolve_parameter_values
from curvemole.core.registry import default_registry


def manual_points_default(definition: Any) -> bool:
    """Return the function's preferred creation mode.

    Linear and cubic-spline functions are manual-point-first by default. Custom
    functions can override this through ``custom_metadata`` in Function Builder.
    """
    marker = definition.custom_metadata.get("manual_points_default")
    if marker is not None:
        return bool(marker)
    return definition.identifier in {"linear", "cubic_spline"}


def minimum_manual_points(component: Component, *, registry: Any = None) -> int:
    """Require enough explicit points to determine the component sensibly."""
    definition = (registry or default_registry()).get(component.function_id)
    if definition.minimum_points is not None:
        return definition.minimum_points
    if definition.has_point_configuration or component.function_id == "cubic_spline":
        return 2
    return max(2, len(component.parameters))


def initialise_component_from_points(
    component: Component,
    points: Iterable[tuple[float, float]],
    *,
    registry: Any,
    preview: bool = False,
) -> Component:
    """Initialize any function from explicit graph points and lock its parameters."""
    selected = sorted((float(x), float(y)) for x, y in points)
    if not selected:
        raise ValueError("At least one manual point is required.")
    if any(not math.isfinite(value) for point in selected for value in point):
        raise ValueError("Manual points must be finite.")

    definition = registry.get(component.function_id)
    required = 1 if preview and definition.has_point_configuration else minimum_manual_points(component, registry=registry)
    if len(selected) < required:
        raise ValueError(f"This function needs at least {required} manual points.")

    if component.function_id == "cubic_spline":
        initialise_spline_component(component, selected, registry=registry)
        return component

    x = np.asarray([point[0] for point in selected], dtype=float)
    y = np.asarray([point[1] for point in selected], dtype=float)
    definition = registry.get(component.function_id)
    if definition.has_point_configuration:
        metadata = definition.configuration_from_points(x, y, component.metadata)
        parameters = definition.make_parameters(metadata=metadata)
    else:
        metadata, parameters = dict(component.metadata), copy.deepcopy(component.parameters) if definition.point_initializer else component.parameters
    if definition.point_initializer is not None:
        initial = definition.point_initializer(x, y, metadata)
        if set(initial) != set(parameters):
            raise ValueError("Point initialization must supply all declared parameters.")
        for name, parameter in parameters.items():
            value = float(initial[name])
            if not math.isfinite(value):
                raise ValueError("Point initialization produced a non-finite parameter.")
            parameter.value = value
            parameter.fixed = True
            parameter.validate()
        component.metadata, component.parameters = metadata, parameters
        return component
    component.metadata, component.parameters = metadata, parameters

    # Give common functions a physically meaningful starting estimate before
    # the generic least-squares refinement.
    if component.function_id == "linear":
        slope, intercept = np.polyfit(x, y, 1)
        component.parameters["slope"].value = float(slope)
        component.parameters["intercept"].value = float(intercept)
    elif component.function_id == "constant":
        component.parameters["offset"].value = float(np.mean(y))
    elif definition.kind == "peak":
        # Use exactly the same fit as the placement preview, including signed peaks.

        fitted = _generic_fit_component(component, selected, registry=registry,
                                        free_only=False, strict=True)
        for parameter in fitted.parameters.values():
            parameter.fixed = True
            parameter.validate()
        component.parameters = fitted.parameters
        return component

    names = list(component.parameters)
    initial = np.asarray([component.parameters[name].value for name in names], dtype=float)
    lower = np.asarray([component.parameters[name].minimum for name in names], dtype=float)
    upper = np.asarray([component.parameters[name].maximum for name in names], dtype=float)
    initial = np.minimum(np.maximum(initial, lower), upper)

    scale = max(float(np.ptp(y)), float(np.max(np.abs(y))), 1.0)

    def residual(values: np.ndarray) -> np.ndarray:
        mapping = {name: float(value) for name, value in zip(names, values, strict=True)}
        try:
            calculated = definition.evaluate(x, mapping, component.metadata)
        except Exception:
            return np.full(len(x), 1e12, dtype=float)
        result = (np.asarray(calculated, dtype=float) - y) / scale
        if not np.all(np.isfinite(result)):
            return np.full(len(x), 1e12, dtype=float)
        return result

    if names:
        from scipy.optimize import least_squares
        fitted = least_squares(residual, initial, bounds=(lower, upper), max_nfev=5000)
        if fitted.success and np.all(np.isfinite(fitted.x)):
            for name, value in zip(names, fitted.x, strict=True):
                component.parameters[name].value = float(value)

    for parameter in component.parameters.values():
        parameter.fixed = True
        parameter.validate()
    return component


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
    reseed: bool = True,
    strict: bool = False,
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
    elif definition.kind == "peak" and not free_only and reseed:
        peak_index = int(np.argmax(np.abs(y_values)))
        height = float(y_values[peak_index])
        span = float(np.ptp(x_values)) or max(abs(float(x_values[peak_index]))*1e-3, 1.)
        suggestion = PeakSuggestion(
            x=float(x_values[peak_index]),
            height=height,
            fwhm=max(span / 2.0, np.finfo(float).eps),
            prominence=abs(height),
            sign=-1 if height < 0 else 1,
        )
        with suppress(Exception):
            initialise_peak_component(fitted, suggestion, registry=registry)

    names = [
        name
        for name, parameter in fitted.parameters.items()
        if not free_only or parameter.is_free
    ]
    if not names or (reseed and not free_only and definition.kind == "peak" and len(points) < len(names)):
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

    from scipy.optimize import least_squares
    try:
        result = least_squares(
            residual,
            initial,
            bounds=(lower, upper),
            max_nfev=1500,
            x_scale="jac",
        )
    except Exception:
        if strict:
            raise
        return Component.from_dict(copy.deepcopy(component.to_dict())) if context is not None else fitted
    if strict and (not result.success or not np.all(np.isfinite(result.x))):
        raise DataValidationError("Could not fit this peak to its control points. Move or add points and retry.")
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
    definition = registry.get(component.function_id)
    if definition.has_point_configuration or definition.point_initializer is not None or component.function_id == "cubic_spline":
        if component.function_id == "cubic_spline" and len(selected) < 2:
            return None
        fitted = Component.from_dict(copy.deepcopy(component.to_dict()))
        initialise_component_from_points(
            fitted,
            selected,
            registry=registry,
            preview=True,
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
