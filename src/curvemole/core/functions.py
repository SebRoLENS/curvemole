"""Function definitions shipped with CurveMole and safe custom formulas."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.special import voigt_profile

from curvemole.core.errors import DataValidationError
from curvemole.core.expressions import SafeExpression, expression_parameters
from curvemole.core.parameters import Parameter

Evaluator = Callable[[np.ndarray, Mapping[str, float], Mapping[str, Any]], np.ndarray]
DerivedEvaluator = Callable[[Mapping[str, float], Mapping[str, Any]], float]


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    default: float
    minimum: float = -math.inf
    maximum: float = math.inf
    unit: str = ""

    def make(self, value: float | None = None) -> Parameter:
        selected = self.default if value is None else float(value)
        selected = min(max(selected, self.minimum), self.maximum)
        return Parameter(
            self.name,
            selected,
            minimum=self.minimum,
            maximum=self.maximum,
            unit=self.unit,
        )


@dataclass(slots=True)
class FunctionDefinition:
    identifier: str
    display_name: str
    kind: str
    evaluator: Evaluator
    parameter_specs: tuple[ParameterSpec, ...] = ()
    parameter_factory: Callable[[Mapping[str, Any]], tuple[ParameterSpec, ...]] | None = None
    derived: dict[str, DerivedEvaluator] = field(default_factory=dict)
    description: str = ""
    custom_metadata: dict[str, Any] = field(default_factory=dict)

    def specs(self, metadata: Mapping[str, Any] | None = None) -> tuple[ParameterSpec, ...]:
        if self.parameter_factory:
            return self.parameter_factory(metadata or {})
        return self.parameter_specs

    def make_parameters(
        self,
        initial: Mapping[str, float] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Parameter]:
        values = initial or {}
        return {spec.name: spec.make(values.get(spec.name)) for spec in self.specs(metadata)}

    def evaluate(
        self,
        x: np.ndarray,
        parameters: Mapping[str, float],
        metadata: Mapping[str, Any] | None = None,
    ) -> np.ndarray:
        result = np.asarray(self.evaluator(x, parameters, metadata or {}), dtype=np.float64)
        if result.ndim == 0:
            result = np.full_like(x, float(result))
        if result.shape != x.shape:
            try:
                result = np.broadcast_to(result, x.shape).astype(np.float64, copy=True)
            except ValueError as exc:
                raise DataValidationError(
                    f"Function '{self.display_name}' returned shape {result.shape}; expected {x.shape}."
                ) from exc
        return result

    def derived_values(
        self, parameters: Mapping[str, float], metadata: Mapping[str, Any] | None = None
    ) -> dict[str, float | None]:
        result: dict[str, float | None] = {}
        for name, evaluator in self.derived.items():
            try:
                value = float(evaluator(parameters, metadata or {}))
                result[name] = value if np.isfinite(value) else None
            except (ArithmeticError, ValueError, TypeError):
                result[name] = None
        return result


_POSITIVE = np.finfo(np.float64).eps
_SQRT_2PI = math.sqrt(2 * math.pi)


def _gaussian(x: np.ndarray, p: Mapping[str, float], _: Mapping[str, Any]) -> np.ndarray:
    sigma = p["sigma"]
    z = (x - p["center"]) / sigma
    return p["area"] * np.exp(-0.5 * z * z) / (sigma * _SQRT_2PI)


def _lorentzian(x: np.ndarray, p: Mapping[str, float], _: Mapping[str, Any]) -> np.ndarray:
    gamma = p["gamma"]
    return p["area"] * gamma / (math.pi * ((x - p["center"]) ** 2 + gamma**2))


def _voigt(x: np.ndarray, p: Mapping[str, float], _: Mapping[str, Any]) -> np.ndarray:
    return p["area"] * voigt_profile(x - p["center"], p["sigma"], p["gamma"])


def _pseudo_voigt(x: np.ndarray, p: Mapping[str, float], _: Mapping[str, Any]) -> np.ndarray:
    fwhm = p["fwhm"]
    eta = p["eta"]
    sigma = fwhm / (2 * math.sqrt(2 * math.log(2)))
    gamma = fwhm / 2
    gaussian = np.exp(-0.5 * ((x - p["center"]) / sigma) ** 2) / (sigma * _SQRT_2PI)
    lorentzian = gamma / (math.pi * ((x - p["center"]) ** 2 + gamma**2))
    return p["area"] * ((1 - eta) * gaussian + eta * lorentzian)


def _constant(x: np.ndarray, p: Mapping[str, float], _: Mapping[str, Any]) -> np.ndarray:
    return np.full_like(x, p["offset"])


def _linear(x: np.ndarray, p: Mapping[str, float], _: Mapping[str, Any]) -> np.ndarray:
    return p["intercept"] + p["slope"] * x


def _polynomial_specs(metadata: Mapping[str, Any]) -> tuple[ParameterSpec, ...]:
    order = int(metadata.get("order", 2))
    if not 0 <= order <= 50:
        raise DataValidationError("Polynomial order must be between 0 and 50.")
    return tuple(ParameterSpec(f"c{degree}", 0.0) for degree in range(order + 1))


def _polynomial(x: np.ndarray, p: Mapping[str, float], metadata: Mapping[str, Any]) -> np.ndarray:
    order = int(metadata.get("order", len(p) - 1))
    result = np.zeros_like(x)
    for degree in range(order + 1):
        result += p[f"c{degree}"] * np.power(x, degree)
    return result


def _spline_specs(metadata: Mapping[str, Any]) -> tuple[ParameterSpec, ...]:
    nodes = metadata.get("x_nodes", [])
    if len(nodes) < 2:
        raise DataValidationError("A cubic spline requires at least two x nodes.")
    return tuple(ParameterSpec(f"y{index}", 0.0) for index in range(len(nodes)))


def _spline(x: np.ndarray, p: Mapping[str, float], metadata: Mapping[str, Any]) -> np.ndarray:
    x_nodes = np.asarray(metadata.get("x_nodes", []), dtype=float)
    if len(x_nodes) < 2 or np.any(~np.isfinite(x_nodes)) or np.any(np.diff(x_nodes) <= 0):
        raise DataValidationError("Spline x nodes must be finite and strictly increasing.")
    y_nodes = np.asarray([p[f"y{index}"] for index in range(len(x_nodes))], dtype=float)
    if len(x_nodes) == 2:
        return np.interp(x, x_nodes, y_nodes)
    return CubicSpline(x_nodes, y_nodes, bc_type="natural", extrapolate=True)(x)


def builtin_definitions() -> tuple[FunctionDefinition, ...]:
    area = ParameterSpec("area", 1.0)
    center = ParameterSpec("center", 0.0)
    sigma = ParameterSpec("sigma", 1.0, _POSITIVE)
    gamma = ParameterSpec("gamma", 1.0, _POSITIVE)
    fwhm = ParameterSpec("fwhm", 1.0, _POSITIVE)
    return (
        FunctionDefinition(
            "gaussian",
            "Gaussian",
            "peak",
            _gaussian,
            (area, center, sigma),
            derived={"area": lambda p, m: p["area"], "FWHM": lambda p, m: 2.354820045 * p["sigma"]},
            description="Area-normalised Gaussian peak; sigma is the standard deviation.",
        ),
        FunctionDefinition(
            "lorentzian",
            "Lorentzian",
            "peak",
            _lorentzian,
            (area, center, gamma),
            derived={"area": lambda p, m: p["area"], "FWHM": lambda p, m: 2 * p["gamma"]},
            description="Area-normalised Lorentzian peak; gamma is HWHM.",
        ),
        FunctionDefinition(
            "voigt",
            "Voigt",
            "peak",
            _voigt,
            (area, center, sigma, gamma),
            derived={
                "area": lambda p, m: p["area"],
                "FWHM": lambda p, m: 0.5346 * 2 * p["gamma"]
                + math.sqrt(0.2166 * (2 * p["gamma"]) ** 2 + (2.354820045 * p["sigma"]) ** 2),
            },
            description="Area-normalised convolution of Gaussian and Lorentzian profiles.",
        ),
        FunctionDefinition(
            "pseudo_voigt",
            "Pseudo-Voigt",
            "peak",
            _pseudo_voigt,
            (area, center, fwhm, ParameterSpec("eta", 0.5, 0.0, 1.0)),
            derived={"area": lambda p, m: p["area"], "FWHM": lambda p, m: p["fwhm"]},
            description="Area-normalised linear mixture with common FWHM and eta in [0, 1].",
        ),
        FunctionDefinition(
            "constant",
            "Constant",
            "generic",
            _constant,
            (ParameterSpec("offset", 0.0),),
        ),
        FunctionDefinition(
            "linear",
            "Linear",
            "generic",
            _linear,
            (ParameterSpec("intercept", 0.0), ParameterSpec("slope", 0.0)),
        ),
        FunctionDefinition(
            "polynomial",
            "Polynomial",
            "generic",
            _polynomial,
            parameter_factory=_polynomial_specs,
        ),
        FunctionDefinition(
            "cubic_spline",
            "Cubic spline",
            "generic",
            _spline,
            parameter_factory=_spline_specs,
        ),
    )


def formula_definition(
    identifier: str,
    display_name: str,
    formula: str,
    *,
    kind: str = "generic",
    defaults: Mapping[str, float] | None = None,
    bounds: Mapping[str, tuple[float, float]] | None = None,
    derived_formulas: Mapping[str, str] | None = None,
) -> FunctionDefinition:
    expression = SafeExpression.compile(formula)
    parameter_names = expression_parameters(formula)
    default_values = defaults or {}
    parameter_bounds = bounds or {}
    specs = tuple(
        ParameterSpec(
            name,
            float(default_values.get(name, 1.0)),
            float(parameter_bounds.get(name, (-math.inf, math.inf))[0]),
            float(parameter_bounds.get(name, (-math.inf, math.inf))[1]),
        )
        for name in parameter_names
    )

    def evaluator(x: np.ndarray, values: Mapping[str, float], metadata: Mapping[str, Any]) -> np.ndarray:
        return np.asarray(expression.evaluate({"x": x, **values}), dtype=float)

    derived: dict[str, DerivedEvaluator] = {}
    for quantity, derived_source in (derived_formulas or {}).items():
        compiled = SafeExpression.compile(derived_source)
        derived[quantity] = lambda values, metadata, expr=compiled: float(expr.evaluate(values))

    return FunctionDefinition(
        identifier=identifier,
        display_name=display_name,
        kind=kind,
        evaluator=evaluator,
        parameter_specs=specs,
        derived=derived,
        description=f"User formula: {formula}",
        custom_metadata={
            "formula": formula,
            "defaults": dict(default_values),
            "bounds": {key: list(value) for key, value in parameter_bounds.items()},
            "derived_formulas": dict(derived_formulas or {}),
        },
    )


def numerical_peak_quantities(
    definition: FunctionDefinition,
    parameters: Mapping[str, float],
    metadata: Mapping[str, Any],
    x: np.ndarray,
) -> dict[str, float | None]:
    """Numerically estimate signed area and FWHM where they are meaningful."""

    if len(x) < 3 or definition.kind != "peak":
        return {"area": None, "FWHM": None}
    order = np.argsort(x)
    xs = np.asarray(x)[order]
    ys = definition.evaluate(xs, parameters, metadata)
    area = float(np.trapezoid(ys, xs))
    absolute = np.abs(ys)
    if not np.any(np.isfinite(absolute)):
        return {"area": area, "FWHM": None}
    peak_index = int(np.nanargmax(absolute))
    half = absolute[peak_index] / 2
    above = np.flatnonzero(absolute >= half)
    fwhm_value = float(xs[above[-1]] - xs[above[0]]) if len(above) >= 2 else None
    return {"area": area, "FWHM": fwhm_value}
