"""Least-squares fitting workflows and transparent fit statistics."""

from __future__ import annotations

import copy
import math
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import numpy as np
from scipy import optimize, stats

from curvemole.core.data import Curve, CurveState
from curvemole.core.errors import ConstraintError, FitCancelled, FitError
from curvemole.core.models import Model
from curvemole.core.parameters import Parameter, resolve_parameter_values
from curvemole.core.registry import FunctionRegistry, default_registry

ProgressCallback = Callable[[float | None, str], None]


class FitMode(StrEnum):
    INDEPENDENT = "independent"
    COPY = "copy"
    SEQUENTIAL = "sequential"
    GLOBAL = "global"


@dataclass(slots=True)
class FitSettings:
    solver: str = "local"
    local_method: str = "auto"
    loss: str = "linear"
    f_scale: float = 1.0
    max_nfev: int = 10_000
    ftol: float = 1e-10
    xtol: float = 1e-10
    gtol: float = 1e-10
    x_scale: str | float = "jac"
    seed: int = 1729
    workers: int = 1
    de_maxiter: int = 400
    de_popsize: int = 15
    confidence_level: float = 0.95
    absolute_sigma: bool | None = None

    def validate(self) -> None:
        if self.solver not in {"local", "differential_evolution"}:
            raise FitError(f"Unknown solver: {self.solver}")
        if self.local_method not in {"auto", "trf", "dogbox", "lm"}:
            raise FitError(f"Unknown local method: {self.local_method}")
        if self.loss not in {"linear", "soft_l1", "huber", "cauchy"}:
            raise FitError(f"Unknown least-squares loss: {self.loss}")
        if not 0 < self.confidence_level < 1:
            raise FitError("Confidence level must be between zero and one.")
        if self.max_nfev <= 0:
            raise FitError("Maximum function evaluations must be positive.")


@dataclass(slots=True)
class FitPlan:
    curve_ids: list[str]
    mode: FitMode = FitMode.INDEPENDENT
    settings: FitSettings = field(default_factory=FitSettings)
    spectrum_weights: dict[str, float] = field(default_factory=dict)
    equal_contribution: bool = False

    def validate(self) -> None:
        if not self.curve_ids:
            raise FitError("A fit plan requires at least one curve.")
        if len(self.curve_ids) != len(set(self.curve_ids)):
            raise FitError("A fit plan contains the same curve more than once.")
        for curve_id, weight in self.spectrum_weights.items():
            if weight <= 0 or not math.isfinite(weight):
                raise FitError(f"Spectrum weight for '{curve_id}' must be finite and positive.")
        self.settings.validate()


@dataclass(slots=True)
class ParameterEstimate:
    path: str
    value: float
    standard_error: float | None
    ci_low: float | None
    ci_high: float | None
    minimum: float
    maximum: float
    status: str
    link: str | None
    at_bound: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CurveFitOutput:
    curve_id: str
    indices: np.ndarray
    x: np.ndarray
    observed: np.ndarray
    fitted: np.ndarray
    residual: np.ndarray
    weighted_residual: np.ndarray
    statistics: dict[str, float | int | None]

    def to_dict(self, *, arrays: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {"curve_id": self.curve_id, "statistics": self.statistics}
        if arrays:
            result.update(
                {
                    "indices": self.indices.tolist(),
                    "x": self.x.tolist(),
                    "observed": self.observed.tolist(),
                    "fitted": self.fitted.tolist(),
                    "residual": self.residual.tolist(),
                    "weighted_residual": self.weighted_residual.tolist(),
                }
            )
        return result


@dataclass(slots=True)
class FitResult:
    success: bool
    mode: FitMode
    message: str
    status: int
    evaluations: int
    parameters: dict[str, ParameterEstimate]
    curve_outputs: dict[str, CurveFitOutput]
    statistics: dict[str, float | int | None]
    warnings: list[str]
    settings: FitSettings
    free_parameter_paths: list[str]
    covariance: np.ndarray | None = None
    correlation: np.ndarray | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    elapsed_seconds: float = 0.0
    cancelled: bool = False
    paused_curve_id: str | None = None

    def to_dict(self, *, arrays: bool = False) -> dict[str, Any]:
        return {
            "success": self.success,
            "mode": self.mode.value,
            "message": self.message,
            "status": self.status,
            "evaluations": self.evaluations,
            "parameters": {key: value.to_dict() for key, value in self.parameters.items()},
            "curve_outputs": {
                key: value.to_dict(arrays=arrays) for key, value in self.curve_outputs.items()
            },
            "statistics": self.statistics,
            "warnings": self.warnings,
            "settings": asdict(self.settings),
            "free_parameter_paths": self.free_parameter_paths,
            "covariance": self.covariance.tolist() if arrays and self.covariance is not None else None,
            "correlation": self.correlation.tolist() if arrays and self.correlation is not None else None,
            "timestamp": self.timestamp,
            "elapsed_seconds": self.elapsed_seconds,
            "cancelled": self.cancelled,
            "paused_curve_id": self.paused_curve_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FitResult:
        settings = FitSettings(**dict(value.get("settings", {})))
        parameters = {
            path: ParameterEstimate(**estimate)
            for path, estimate in value.get("parameters", {}).items()
        }
        outputs: dict[str, CurveFitOutput] = {}
        for curve_id, output in value.get("curve_outputs", {}).items():
            if not all(
                key in output
                for key in ("indices", "x", "observed", "fitted", "residual", "weighted_residual")
            ):
                continue
            outputs[curve_id] = CurveFitOutput(
                curve_id=curve_id,
                indices=np.asarray(output["indices"], dtype=int),
                x=np.asarray(output["x"], dtype=float),
                observed=np.asarray(output["observed"], dtype=float),
                fitted=np.asarray(output["fitted"], dtype=float),
                residual=np.asarray(output["residual"], dtype=float),
                weighted_residual=np.asarray(output["weighted_residual"], dtype=float),
                statistics=dict(output.get("statistics", {})),
            )
        return cls(
            success=bool(value.get("success", False)),
            mode=FitMode(value.get("mode", FitMode.INDEPENDENT.value)),
            message=str(value.get("message", "")),
            status=int(value.get("status", 0)),
            evaluations=int(value.get("evaluations", 0)),
            parameters=parameters,
            curve_outputs=outputs,
            statistics=dict(value.get("statistics", {})),
            warnings=list(value.get("warnings", [])),
            settings=settings,
            free_parameter_paths=list(value.get("free_parameter_paths", [])),
            covariance=(
                np.asarray(value["covariance"], dtype=float)
                if value.get("covariance") is not None
                else None
            ),
            correlation=(
                np.asarray(value["correlation"], dtype=float)
                if value.get("correlation") is not None
                else None
            ),
            timestamp=str(value.get("timestamp", datetime.now(UTC).isoformat())),
            elapsed_seconds=float(value.get("elapsed_seconds", 0.0)),
            cancelled=bool(value.get("cancelled", False)),
            paused_curve_id=value.get("paused_curve_id"),
        )


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise FitCancelled("Fit cancelled by the user.")


class _Problem:
    def __init__(
        self,
        curves: Sequence[Curve],
        models: Mapping[str, Model],
        plan: FitPlan,
        registry: FunctionRegistry,
        cancellation: CancellationToken,
        progress: ProgressCallback | None,
    ) -> None:
        self.curves = list(curves)
        self.models = models
        self.plan = plan
        self.registry = registry
        self.cancellation = cancellation
        self.progress = progress
        self.parameters: dict[str, Parameter] = {}
        self.free_paths: list[str] = []
        self._data: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray | None, np.ndarray]] = {}
        self.evaluations = 0
        self._last_progress = 0.0

        for curve in self.curves:
            if curve.id not in models:
                raise FitError(f"Curve '{curve.name}' has no model.")
            model = models[curve.id]
            model.validate(registry)
            for path, parameter in model.parameter_map(curve.id).items():
                if path in self.parameters:
                    raise FitError(f"Duplicate parameter path: {path}")
                self.parameters[path] = parameter
            self._data[curve.id] = curve.fit_arrays()
        resolve_parameter_values(self.parameters)
        self.free_paths = [path for path, parameter in self.parameters.items() if parameter.is_free]
        if not self.free_paths:
            raise FitError("The selected models contain no free parameters.")

    @property
    def initial(self) -> np.ndarray:
        return np.asarray([self.parameters[path].value for path in self.free_paths], dtype=float)

    @property
    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        lower = np.asarray([self.parameters[path].minimum for path in self.free_paths], dtype=float)
        upper = np.asarray([self.parameters[path].maximum for path in self.free_paths], dtype=float)
        return lower, upper

    def values(self, vector: np.ndarray, *, commit: bool = False) -> dict[str, float]:
        for path, value in zip(self.free_paths, vector, strict=True):
            self.parameters[path].value = float(value)
        values = resolve_parameter_values(self.parameters)
        if commit:
            for path, value in values.items():
                self.parameters[path].value = float(value)
        return values

    def residual(self, vector: np.ndarray) -> np.ndarray:
        self.cancellation.raise_if_cancelled()
        self.evaluations += 1
        values = self.values(vector)
        residuals: list[np.ndarray] = []
        for curve in self.curves:
            x, observed, point_scale, _ = self._data[curve.id]
            fitted = np.asarray(
                self.models[curve.id].evaluate(
                    x, curve_id=curve.id, values=values, registry=self.registry
                )
            )
            if not np.all(np.isfinite(fitted)):
                raise FitError(f"Model for curve '{curve.name}' returned non-finite values.")
            residual = fitted - observed
            if point_scale is not None:
                residual = residual * point_scale
            spectrum_weight = self.plan.spectrum_weights.get(curve.id, 1.0)
            residual = residual * math.sqrt(spectrum_weight)
            if self.plan.equal_contribution:
                residual = residual / math.sqrt(len(residual))
            residuals.append(residual)
        now = time.monotonic()
        if self.progress and now - self._last_progress > 0.08:
            maximum = max(1, self.plan.settings.max_nfev)
            self.progress(min(self.evaluations / maximum, 0.99), f"Evaluation {self.evaluations}")
            self._last_progress = now
        return np.concatenate(residuals)

    def outputs(self, values: Mapping[str, float]) -> dict[str, CurveFitOutput]:
        result: dict[str, CurveFitOutput] = {}
        for curve in self.curves:
            x, observed, point_scale, indices = self._data[curve.id]
            fitted = np.asarray(
                self.models[curve.id].evaluate(
                    x, curve_id=curve.id, values=values, registry=self.registry
                )
            )
            residual = observed - fitted
            weighted = residual.copy()
            if point_scale is not None:
                weighted *= point_scale
            weighted *= math.sqrt(self.plan.spectrum_weights.get(curve.id, 1.0))
            if self.plan.equal_contribution:
                weighted /= math.sqrt(len(weighted))
            rss = float(np.dot(residual, residual))
            tss = float(np.dot(observed - np.mean(observed), observed - np.mean(observed)))
            result[curve.id] = CurveFitOutput(
                curve_id=curve.id,
                indices=indices,
                x=x,
                observed=observed,
                fitted=fitted,
                residual=residual,
                weighted_residual=weighted,
                statistics={
                    "N": len(observed),
                    "RSS": rss,
                    "RMSE": math.sqrt(rss / len(observed)),
                    "R_squared": 1 - rss / tss if tss > 0 else None,
                },
            )
        return result


class Fitter:
    def __init__(self, registry: FunctionRegistry | None = None) -> None:
        self.registry = registry or default_registry()

    def fit(
        self,
        plan: FitPlan,
        curves: Mapping[str, Curve] | Sequence[Curve],
        models: Mapping[str, Model],
        *,
        cancellation: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> FitResult:
        plan.validate()
        curve_map = {curve.id: curve for curve in curves} if not isinstance(curves, Mapping) else curves
        try:
            selected = [curve_map[curve_id] for curve_id in plan.curve_ids]
        except KeyError as exc:
            raise FitError(f"Fit plan references unknown curve: {exc.args[0]}") from exc
        cancellation = cancellation or CancellationToken()
        started = time.monotonic()
        if plan.mode == FitMode.GLOBAL:
            result = self._fit_problem(selected, models, plan, cancellation, progress)
        elif plan.mode == FitMode.SEQUENTIAL:
            result = self._fit_sequential(selected, models, plan, cancellation, progress)
        else:
            result = self._fit_independent(selected, models, plan, cancellation, progress)
        result.elapsed_seconds = time.monotonic() - started
        if progress:
            progress(1.0, result.message)
        return result

    def fit_single(
        self,
        curve: Curve,
        model: Model,
        settings: FitSettings | None = None,
        *,
        cancellation: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> FitResult:
        plan = FitPlan([curve.id], FitMode.INDEPENDENT, settings or FitSettings())
        return self.fit(
            plan,
            {curve.id: curve},
            {curve.id: model},
            cancellation=cancellation,
            progress=progress,
        )

    def _fit_independent(
        self,
        curves: Sequence[Curve],
        models: Mapping[str, Model],
        plan: FitPlan,
        cancellation: CancellationToken,
        progress: ProgressCallback | None,
    ) -> FitResult:
        results: list[FitResult] = []
        for index, curve in enumerate(curves):
            cancellation.raise_if_cancelled()
            if progress:
                progress(index / len(curves), f"Fitting {curve.name}")
            local_plan = FitPlan(
                [curve.id],
                FitMode.INDEPENDENT,
                copy.deepcopy(plan.settings),
                {curve.id: plan.spectrum_weights.get(curve.id, 1.0)},
                plan.equal_contribution,
            )
            results.append(
                self._fit_problem([curve], models, local_plan, cancellation, progress=None)
            )
        return _merge_results(results, plan.mode, plan.settings)

    def _fit_sequential(
        self,
        curves: Sequence[Curve],
        models: Mapping[str, Model],
        plan: FitPlan,
        cancellation: CancellationToken,
        progress: ProgressCallback | None,
    ) -> FitResult:
        results: list[FitResult] = []
        previous_model: Model | None = None
        for index, curve in enumerate(curves):
            cancellation.raise_if_cancelled()
            model = models[curve.id]
            if previous_model is not None:
                _copy_matching_values(previous_model, model)
            if progress:
                progress(index / len(curves), f"Sequential fit: {curve.name}")
            local_plan = FitPlan(
                [curve.id],
                FitMode.SEQUENTIAL,
                copy.deepcopy(plan.settings),
                {curve.id: plan.spectrum_weights.get(curve.id, 1.0)},
                plan.equal_contribution,
            )
            try:
                current = self._fit_problem([curve], models, local_plan, cancellation, progress=None)
            except (FitError, ConstraintError) as exc:
                merged = _merge_results(results, plan.mode, plan.settings)
                merged.success = False
                merged.status = -2
                merged.message = (
                    f"Sequential fit paused at '{curve.name}': {exc}. "
                    "Correct the model manually, then continue explicitly."
                )
                merged.paused_curve_id = curve.id
                curve.state = CurveState.FAILED
                return merged
            results.append(current)
            previous_model = model
        return _merge_results(results, plan.mode, plan.settings)

    def _fit_problem(
        self,
        curves: Sequence[Curve],
        models: Mapping[str, Model],
        plan: FitPlan,
        cancellation: CancellationToken,
        progress: ProgressCallback | None,
    ) -> FitResult:
        original_states = {curve.id: curve.state for curve in curves}
        original_parameter_state = {
            path: (
                parameter.value,
                parameter.standard_error,
                parameter.ci_low,
                parameter.ci_high,
            )
            for curve in curves
            for path, parameter in models[curve.id].parameter_map(curve.id).items()
        }
        for curve in curves:
            curve.state = CurveState.RUNNING
        try:
            problem = _Problem(curves, models, plan, self.registry, cancellation, progress)
            lower, upper = problem.bounds
            settings = plan.settings
            initial = np.clip(problem.initial, lower, upper)
            if settings.solver == "differential_evolution":
                if not np.all(np.isfinite(lower)) or not np.all(np.isfinite(upper)):
                    unbounded = [
                        path
                        for path, lo, hi in zip(problem.free_paths, lower, upper, strict=True)
                        if not (math.isfinite(lo) and math.isfinite(hi))
                    ]
                    raise FitError(
                        "Differential Evolution requires finite user bounds for: "
                        + ", ".join(unbounded)
                    )
                if progress:
                    progress(0.0, "Differential Evolution initial search")
                differential = optimize.differential_evolution(
                    lambda vector: _sum_of_squares(problem.residual(vector)),
                    list(zip(lower, upper, strict=True)),
                    seed=settings.seed,
                    maxiter=settings.de_maxiter,
                    popsize=settings.de_popsize,
                    workers=settings.workers,
                    updating="immediate" if settings.workers == 1 else "deferred",
                    polish=False,
                    callback=lambda intermediate_result: cancellation.cancelled,
                )
                cancellation.raise_if_cancelled()
                initial = differential.x
            method = _select_method(settings, lower, upper)
            least_squares = optimize.least_squares(
                problem.residual,
                initial,
                bounds=(lower, upper),
                method=method,
                loss=settings.loss,
                f_scale=settings.f_scale,
                x_scale=settings.x_scale,
                max_nfev=settings.max_nfev,
                ftol=settings.ftol,
                xtol=settings.xtol,
                gtol=settings.gtol,
            )
        except FitCancelled:
            _restore_parameters(problem.parameters if "problem" in locals() else {}, original_parameter_state)
            for curve in curves:
                curve.state = original_states[curve.id]
            raise
        except Exception as exc:
            parameters = problem.parameters if "problem" in locals() else {
                path: parameter
                for curve in curves
                for path, parameter in models[curve.id].parameter_map(curve.id).items()
            }
            _restore_parameters(parameters, original_parameter_state)
            for curve in curves:
                curve.state = CurveState.FAILED
            if isinstance(exc, (FitError, ConstraintError)):
                raise
            raise FitError(f"Least-squares solver failed: {exc}") from exc

        values = problem.values(least_squares.x, commit=True)
        outputs = problem.outputs(values)
        warnings: list[str] = []
        covariance, correlation, errors = _covariance(
            least_squares.jac,
            np.asarray(least_squares.fun),
            settings,
            curves,
            warnings,
        )
        estimates = _parameter_estimates(
            problem,
            least_squares.x,
            values,
            covariance,
            errors,
            settings,
            warnings,
        )
        statistics = _global_statistics(outputs, len(problem.free_paths), settings.loss)
        if correlation is not None and correlation.size:
            upper_triangle = np.abs(correlation[np.triu_indices_from(correlation, 1)])
            if upper_triangle.size and np.nanmax(upper_triangle) >= 0.95:
                warnings.append("At least one free-parameter correlation has |r| >= 0.95.")
        if least_squares.jac.shape[0] <= least_squares.jac.shape[1]:
            warnings.append("The fit is underdetermined or has no positive degrees of freedom.")
        if not least_squares.success:
            warnings.append(f"Solver did not converge: {least_squares.message}")
        result = FitResult(
            success=bool(least_squares.success),
            mode=plan.mode,
            message=str(least_squares.message),
            status=int(least_squares.status),
            evaluations=int(least_squares.nfev),
            parameters=estimates,
            curve_outputs=outputs,
            statistics=statistics,
            warnings=warnings,
            settings=copy.deepcopy(settings),
            free_parameter_paths=list(problem.free_paths),
            covariance=covariance,
            correlation=correlation,
        )
        if least_squares.success:
            for curve in curves:
                curve.state = CurveState.FITTED
        else:
            _restore_parameters(problem.parameters, original_parameter_state)
            for curve in curves:
                curve.state = CurveState.FAILED
        return result


def _select_method(settings: FitSettings, lower: np.ndarray, upper: np.ndarray) -> str:
    has_bounds = bool(np.any(np.isfinite(lower)) or np.any(np.isfinite(upper)))
    method = settings.local_method
    if method == "auto":
        return "trf" if has_bounds or settings.loss != "linear" else "lm"
    if method == "lm" and (has_bounds or settings.loss != "linear"):
        raise FitError("Levenberg-Marquardt requires an unbounded model and ordinary least squares.")
    return method


def _sum_of_squares(residual: np.ndarray) -> float:
    return float(np.dot(residual, residual))


def _restore_parameters(
    parameters: Mapping[str, Parameter],
    snapshot: Mapping[str, tuple[float, float | None, float | None, float | None]],
) -> None:
    for path, state in snapshot.items():
        if path not in parameters:
            continue
        parameter = parameters[path]
        parameter.value, parameter.standard_error, parameter.ci_low, parameter.ci_high = state


def _covariance(
    jacobian: np.ndarray,
    weighted_residual: np.ndarray,
    settings: FitSettings,
    curves: Sequence[Curve],
    warnings: list[str],
) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    rows, columns = jacobian.shape
    if rows <= columns or columns == 0:
        warnings.append("Covariance is unavailable because degrees of freedom are not positive.")
        return None, None, None
    try:
        _, singular_values, vh = np.linalg.svd(jacobian, full_matrices=False)
        threshold = np.finfo(float).eps * max(jacobian.shape) * singular_values[0]
        keep = singular_values > threshold
        if np.count_nonzero(keep) < columns:
            warnings.append("Covariance is rank-deficient; pseudo-inverse uncertainties are reported.")
        bread = (vh[keep].T / singular_values[keep] ** 2) @ vh[keep]
        if settings.loss != "linear":
            meat = jacobian.T @ ((weighted_residual**2)[:, None] * jacobian)
            covariance = bread @ meat @ bread * rows / (rows - columns)
            warnings.append(
                "Robust-loss uncertainty uses a sandwich covariance; resampling is recommended."
            )
        else:
            absolute = settings.absolute_sigma
            if absolute is None:
                absolute = all(curve.current_sigma_y is not None for curve in curves)
            covariance = bread
            if not absolute:
                covariance = covariance * float(np.dot(weighted_residual, weighted_residual)) / (
                    rows - columns
                )
        errors = np.sqrt(np.clip(np.diag(covariance), 0, math.inf))
        denominator = np.outer(errors, errors)
        with np.errstate(divide="ignore", invalid="ignore"):
            correlation = covariance / denominator
        np.fill_diagonal(correlation, 1.0)
        return covariance, correlation, errors
    except np.linalg.LinAlgError:
        warnings.append("Covariance calculation failed because the Jacobian is singular.")
        return None, None, None


def _parameter_estimates(
    problem: _Problem,
    optimum: np.ndarray,
    values: Mapping[str, float],
    covariance: np.ndarray | None,
    free_errors: np.ndarray | None,
    settings: FitSettings,
    warnings: list[str],
) -> dict[str, ParameterEstimate]:
    free_index = {path: index for index, path in enumerate(problem.free_paths)}
    z_value = float(stats.norm.ppf(0.5 + settings.confidence_level / 2))
    estimates: dict[str, ParameterEstimate] = {}
    linked_gradients: dict[str, np.ndarray] = {}
    if covariance is not None:
        base = np.asarray([values[path] for path in problem.parameters], dtype=float)
        all_paths = list(problem.parameters)
        gradients = np.zeros((len(all_paths), len(problem.free_paths)), dtype=float)
        for index in range(len(problem.free_paths)):
            step = math.sqrt(np.finfo(float).eps) * max(1.0, abs(optimum[index]))
            shifted = optimum.copy()
            shifted[index] = min(max(shifted[index] + step, problem.bounds[0][index]), problem.bounds[1][index])
            actual = shifted[index] - optimum[index]
            if actual == 0:
                continue
            shifted_values = problem.values(shifted)
            gradients[:, index] = (
                np.asarray([shifted_values[path] for path in all_paths], dtype=float) - base
            ) / actual
        problem.values(optimum, commit=True)
        linked_gradients = {path: gradients[index] for index, path in enumerate(all_paths)}

    for path, parameter in problem.parameters.items():
        error: float | None = None
        if path in free_index and free_errors is not None:
            error = float(free_errors[free_index[path]])
        elif parameter.link and covariance is not None:
            gradient = linked_gradients[path]
            variance = float(gradient @ covariance @ gradient)
            error = math.sqrt(max(variance, 0))
        value = float(values[path])
        tolerance = 1e-8 * max(1.0, abs(value))
        at_bound = (
            math.isfinite(parameter.minimum) and abs(value - parameter.minimum) <= tolerance
        ) or (math.isfinite(parameter.maximum) and abs(value - parameter.maximum) <= tolerance)
        if at_bound:
            warnings.append(f"Parameter '{path}' is at an active bound; its interval is asymmetric.")
        ci_low = max(parameter.minimum, value - z_value * error) if error is not None else None
        ci_high = min(parameter.maximum, value + z_value * error) if error is not None else None
        parameter.standard_error = error
        parameter.ci_low = ci_low
        parameter.ci_high = ci_high
        estimates[path] = ParameterEstimate(
            path=path,
            value=value,
            standard_error=error,
            ci_low=ci_low,
            ci_high=ci_high,
            minimum=parameter.minimum,
            maximum=parameter.maximum,
            status=parameter.status,
            link=parameter.link,
            at_bound=at_bound,
        )
    return estimates


def _global_statistics(
    outputs: Mapping[str, CurveFitOutput], k: int, loss: str
) -> dict[str, float | int | None]:
    residual = np.concatenate([item.residual for item in outputs.values()])
    weighted = np.concatenate([item.weighted_residual for item in outputs.values()])
    observed = np.concatenate([item.observed for item in outputs.values()])
    n = len(residual)
    dof = n - k
    rss = float(np.dot(residual, residual))
    chi_square = float(np.dot(weighted, weighted))
    tss = float(np.dot(observed - np.mean(observed), observed - np.mean(observed)))
    result: dict[str, float | int | None] = {
        "N": n,
        "k": k,
        "degrees_of_freedom": dof,
        "RSS": rss,
        "RMSE": math.sqrt(rss / n) if n else None,
        "chi_square": chi_square,
        "reduced_chi_square": chi_square / dof if dof > 0 else None,
        "R_squared": 1 - rss / tss if tss > 0 else None,
        "AIC": None,
        "AICc": None,
        "BIC": None,
    }
    if loss == "linear" and n > 0 and rss > 0:
        aic = n * math.log(rss / n) + 2 * k
        result["AIC"] = aic
        result["AICc"] = aic + 2 * k * (k + 1) / (n - k - 1) if n > k + 1 else None
        result["BIC"] = n * math.log(rss / n) + k * math.log(n)
    return result


def _copy_matching_values(source: Model, target: Model) -> None:
    for source_component, target_component in zip(source.components, target.components, strict=False):
        if source_component.function_id != target_component.function_id:
            continue
        for name, source_parameter in source_component.parameters.items():
            if name not in target_component.parameters:
                continue
            parameter = target_component.parameters[name]
            if parameter.is_free:
                parameter.value = min(max(source_parameter.value, parameter.minimum), parameter.maximum)


def _merge_results(results: Sequence[FitResult], mode: FitMode, settings: FitSettings) -> FitResult:
    if not results:
        return FitResult(
            False,
            mode,
            "No fit completed.",
            -1,
            0,
            {},
            {},
            {},
            [],
            settings,
            [],
        )
    if len(results) == 1:
        results[0].mode = mode
        return results[0]
    parameters = {path: value for result in results for path, value in result.parameters.items()}
    outputs = {path: value for result in results for path, value in result.curve_outputs.items()}
    warnings = [warning for result in results for warning in result.warnings]
    free_paths = [path for result in results for path in result.free_parameter_paths]
    covariance = None
    correlation = None
    if all(result.covariance is not None for result in results):
        from scipy.linalg import block_diag

        covariance = block_diag(*(result.covariance for result in results))
        errors = np.sqrt(np.clip(np.diag(covariance), 0, math.inf))
        with np.errstate(divide="ignore", invalid="ignore"):
            correlation = covariance / np.outer(errors, errors)
        np.fill_diagonal(correlation, 1.0)
    return FitResult(
        success=all(result.success for result in results),
        mode=mode,
        message=f"Completed {len(results)} fit(s).",
        status=1 if all(result.success for result in results) else -1,
        evaluations=sum(result.evaluations for result in results),
        parameters=parameters,
        curve_outputs=outputs,
        statistics=_global_statistics(outputs, len(free_paths), settings.loss),
        warnings=warnings,
        settings=copy.deepcopy(settings),
        free_parameter_paths=free_paths,
        covariance=covariance,
        correlation=correlation,
    )
