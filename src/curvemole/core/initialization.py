"""Editable peak and background initial estimates."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks, peak_widths

from curvemole.core.data import Curve
from curvemole.core.errors import DataValidationError
from curvemole.core.models import Component
from curvemole.core.registry import FunctionRegistry, default_registry


@dataclass(frozen=True, slots=True)
class PeakSuggestion:
    x: float
    height: float
    fwhm: float
    prominence: float
    sign: int


def find_peak_suggestions(
    curve: Curve,
    *,
    sign: str = "positive",
    prominence: float | None = None,
    distance: int | None = None,
    max_peaks: int = 50,
) -> list[PeakSuggestion]:
    if sign not in {"positive", "negative", "both"}:
        raise DataValidationError("Peak sign must be positive, negative, or both.")
    keep = ~curve.effective_mask
    x, y = curve.x[keep], curve.y[keep]
    if len(x) < 3:
        return []
    baseline = float(np.nanmedian(y))
    centred = y - baseline
    noise = float(np.nanmedian(np.abs(centred - np.nanmedian(centred))) * 1.4826)
    selected_prominence = prominence if prominence is not None else max(noise * 3, np.ptp(y) * 0.01)
    suggestions: list[PeakSuggestion] = []
    signs = (1,) if sign == "positive" else (-1,) if sign == "negative" else (1, -1)
    for selected_sign in signs:
        transformed = centred * selected_sign
        indices, properties = find_peaks(
            transformed,
            prominence=selected_prominence,
            distance=distance,
        )
        if len(indices):
            widths = peak_widths(transformed, indices, rel_height=0.5)[0]
            median_dx = float(np.nanmedian(np.abs(np.diff(np.sort(x)))))
            for local, index in enumerate(indices):
                suggestions.append(
                    PeakSuggestion(
                        x=float(x[index]),
                        height=float(centred[index]),
                        fwhm=max(float(widths[local] * median_dx), np.finfo(float).eps),
                        prominence=float(properties["prominences"][local]),
                        sign=selected_sign,
                    )
                )
    return sorted(suggestions, key=lambda item: item.prominence, reverse=True)[:max_peaks]


def component_from_suggestion(
    suggestion: PeakSuggestion,
    function_id: str = "gaussian",
    *,
    registry: FunctionRegistry | None = None,
) -> Component:
    registry = registry or default_registry()
    if function_id == "gaussian":
        sigma = suggestion.fwhm / 2.354820045
        area = suggestion.height * sigma * math.sqrt(2 * math.pi)
        initial = {"area": area, "center": suggestion.x, "sigma": sigma}
    elif function_id == "lorentzian":
        gamma = suggestion.fwhm / 2
        initial = {"area": suggestion.height * math.pi * gamma, "center": suggestion.x, "gamma": gamma}
    elif function_id == "voigt":
        sigma = suggestion.fwhm / 3.6
        gamma = suggestion.fwhm / 3.6
        unit = registry.get("voigt").evaluate(
            np.array([suggestion.x]), {"area": 1.0, "center": suggestion.x, "sigma": sigma, "gamma": gamma}, {}
        )[0]
        initial = {"area": suggestion.height / unit, "center": suggestion.x, "sigma": sigma, "gamma": gamma}
    elif function_id == "pseudo_voigt":
        unit = registry.get("pseudo_voigt").evaluate(
            np.array([suggestion.x]),
            {"area": 1.0, "center": suggestion.x, "fwhm": suggestion.fwhm, "eta": 0.5},
            {},
        )[0]
        initial = {
            "area": suggestion.height / unit,
            "center": suggestion.x,
            "fwhm": suggestion.fwhm,
            "eta": 0.5,
        }
    else:
        raise DataValidationError(f"Automatic peak estimates are unavailable for '{function_id}'.")
    return Component.create(function_id, registry=registry, initial=initial)


def initialise_peak_component(
    component: Component,
    suggestion: PeakSuggestion,
    *,
    registry: FunctionRegistry | None = None,
) -> Component:
    """Apply a graphical centre/width estimate to built-in or custom peak functions."""
    registry = registry or default_registry()
    definition = registry.get(component.function_id)
    if definition.kind != "peak":
        raise DataValidationError(f"'{definition.display_name}' is not a peak function.")
    if component.function_id in {"gaussian", "lorentzian", "voigt", "pseudo_voigt"}:
        estimated = component_from_suggestion(
            suggestion,
            component.function_id,
            registry=registry,
        )
        component.parameters = estimated.parameters
        return component

    aliases = {name.casefold(): name for name in component.parameters}

    def set_first(names: tuple[str, ...], value: float) -> str | None:
        for alias in names:
            name = aliases.get(alias)
            if name is None:
                continue
            parameter = component.parameters[name]
            parameter.value = min(max(float(value), parameter.minimum), parameter.maximum)
            return name
        return None

    set_first(("center", "centre", "x0", "position", "mu"), suggestion.x)
    set_first(("fwhm", "width", "w"), suggestion.fwhm)
    set_first(("sigma",), suggestion.fwhm / 2.354820045)
    set_first(("gamma", "hwhm"), suggestion.fwhm / 2)
    scale_name = next(
        (
            aliases[name]
            for name in ("area", "amplitude", "height", "intensity")
            if name in aliases
        ),
        None,
    )
    if scale_name is not None:
        scale = component.parameters[scale_name]
        scale.value = min(max(1.0, scale.minimum), scale.maximum)
        values = {name: parameter.value for name, parameter in component.parameters.items()}
        unit_height = float(
            definition.evaluate(np.array([suggestion.x]), values, component.metadata)[0]
        )
        if math.isfinite(unit_height) and unit_height != 0:
            value = suggestion.height / unit_height * scale.value
            scale.value = min(max(value, scale.minimum), scale.maximum)
    for parameter in component.parameters.values():
        parameter.validate()
    return component


def initialise_spline_component(
    component: Component,
    points: Iterable[tuple[float, float]],
    *,
    registry: FunctionRegistry | None = None,
) -> Component:
    """Set cubic-spline nodes from graph points while preserving component identity."""
    registry = registry or default_registry()
    if component.function_id != "cubic_spline":
        raise DataValidationError("Graphical spline points require a cubic-spline component.")
    ordered = sorted((float(x), float(y)) for x, y in points)
    if len(ordered) < 2:
        raise DataValidationError("A cubic spline requires at least two graph points.")
    if any(not math.isfinite(value) for point in ordered for value in point):
        raise DataValidationError("Spline points must be finite.")
    if any(left[0] >= right[0] for left, right in zip(ordered, ordered[1:], strict=False)):
        raise DataValidationError("Spline x positions must be unique.")
    metadata = {**component.metadata, "x_nodes": [x for x, _ in ordered]}
    initial = {f"y{index}": y for index, (_, y) in enumerate(ordered)}
    component.metadata = metadata
    component.parameters = registry.get("cubic_spline").make_parameters(initial, metadata)
    return component


def estimate_background(curve: Curve, function_id: str = "constant") -> Component:
    keep = ~curve.effective_mask
    x, y = curve.x[keep], curve.y[keep]
    if function_id == "constant":
        return Component.create("constant", initial={"offset": float(np.nanmedian(y))})
    if function_id == "linear":
        coefficients = np.polyfit(x, y, 1)
        return Component.create(
            "linear", initial={"slope": float(coefficients[0]), "intercept": float(coefficients[1])}
        )
    raise DataValidationError(f"Automatic background estimate is unavailable for '{function_id}'.")
