"""Least-squares fitting workflows and transparent fit statistics."""

from __future__ import annotations

import copy
import math
import multiprocessing
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import numpy as np

from curvemole.core.data import Curve, CurveState
from curvemole.core.dynamic_bounds import DynamicParameterCoordinates
from curvemole.core.errors import ConstraintError, FitCancelled, FitError
from curvemole.core.jacobians import jacobian_svd, residual_sparsity, weighted_gram
from curvemole.core.matrices import (
    BlockDiagonalMatrix,
    covariance_statistics,
    matrix_from_value,
    matrix_payload,
)
from curvemole.core.models import Model
from curvemole.core.numerics import (
    characteristic_scale,
    derivative_steps,
    parameter_scales,
    scale_jacobian,
)
from curvemole.core.parameters import EqualityParameterResolver, Parameter
from curvemole.core.process_pool import bounded_results, managed_process_pool
from curvemole.core.registry import FunctionRegistry, default_registry
from curvemole.core.worker_functions import registry_from_worker_formulas, worker_formula_specs

ProgressCallback = Callable[[float | None, str], None]
CurveResultCallback = Callable[[str, "FitResult"], None]


def _batch_progress(progress: ProgressCallback | None, completed: int, total: int) -> ProgressCallback | None:
    if progress is None:
        return None

    def report(value: float | None, text: str) -> None:
        progress((completed + (value or 0.0)) / total, text)

    return report


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
    max_nfev: int = 1000
    ftol: float = 1e-10
    xtol: float = 1e-8
    gtol: float = 1e-10
    x_scale: str | float = "jac"
    seed: int = 1729
    workers: int = 1
    de_maxiter: int = 400
    de_popsize: int = 15
    de_lower_percent: float = 50.0
    de_upper_percent: float = 50.0
    confidence_level: float = 0.95
    absolute_sigma: bool | None = None

    de_mutation_min: float = 0.5
    de_mutation_max: float = 1.0
    de_recombination: float = 0.7
    de_tol: float = 0.01
    de_atol: float = 0.0
    nm_xatol: float = 1e-4
    nm_fatol: float = 1e-4
    nm_adaptive: bool = False
    nm_initial_simplex: list[list[float]] | None = None
    minimize_maxiter: int = 0  # zero preserves the solver's automatic limit
    powell_xtol: float = 1e-4
    powell_ftol: float = 1e-4
    lbfgsb_ftol: float = 2.220446049250313e-9
    lbfgsb_gtol: float = 1e-5
    lbfgsb_maxls: int = 20
    lbfgsb_maxcor: int = 10
    use_data_errors: bool = True

    def validate(self) -> None:
        from curvemole.core.extensions import extensions
        if not isinstance(self.use_data_errors, bool):
            raise FitError("Use data errors must be a boolean.")
        if self.solver not in {"local", "differential_evolution", "trf", "dogbox", "lm",
                               "nelder_mead", "powell", "lbfgsb"} and not any(
                entry.identifier == self.solver for entry in extensions.values("fit_solvers")):
            raise FitError(f"Unknown solver: {self.solver}")
        if self.local_method not in {"auto", "trf", "dogbox", "lm"}:
            raise FitError(f"Unknown local method: {self.local_method}")
        if self.loss not in {"linear", "soft_l1", "huber", "cauchy"}:
            raise FitError(f"Unknown least-squares loss: {self.loss}")
        if not math.isfinite(self.f_scale) or self.f_scale <= 0:
            raise FitError("Loss scale must be finite and positive.")
        if not all(math.isfinite(value) and value > 0 for value in
                   (self.de_lower_percent, self.de_upper_percent)):
            raise FitError("Automatic search bound percentages must be finite and positive.")
        if not 0 < self.confidence_level < 1:
            raise FitError("Confidence level must be between zero and one.")
        if self.max_nfev <= 0:
            raise FitError("Maximum function evaluations must be positive.")
        if not isinstance(self.workers, int) or isinstance(self.workers, bool) or self.workers < 1:
            raise FitError("Worker process count must be a positive integer.")
        positive = ("ftol", "xtol", "gtol", "nm_xatol", "nm_fatol",
                    "powell_xtol", "powell_ftol", "lbfgsb_ftol", "lbfgsb_gtol")
        for name in positive:
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise FitError(f"{name} must be finite and positive.")
        if min(self.ftol, self.xtol, self.gtol) <= np.finfo(float).eps:
            raise FitError("Least-squares tolerances must exceed machine precision.")
        if self.x_scale != "jac":
            try:
                scale = float(self.x_scale)
            except (TypeError, ValueError) as exc:
                raise FitError("Parameter scale must be 'jac' or a positive number.") from exc
            if not math.isfinite(scale) or scale <= 0:
                raise FitError("Parameter scale must be 'jac' or a positive number.")
        for name in ("max_nfev", "de_maxiter", "de_popsize", "lbfgsb_maxls", "lbfgsb_maxcor"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise FitError(f"{name} must be a positive integer.")
        if not isinstance(self.minimize_maxiter, int) or self.minimize_maxiter < 0:
            raise FitError("Iteration limit must be a nonnegative integer (0 means automatic).")
        if not isinstance(self.seed, int) or not 0 <= self.seed <= 2**32 - 1:
            raise FitError("Random seed must be an integer between 0 and 4294967295.")
        if not (0 <= self.de_mutation_min <= self.de_mutation_max < 2):
            raise FitError("DE mutation bounds must satisfy 0 <= minimum <= maximum < 2.")
        if not 0 <= self.de_recombination <= 1:
            raise FitError("DE recombination must be between 0 and 1.")
        if any(not math.isfinite(v) or v < 0 for v in (self.de_tol, self.de_atol)):
            raise FitError("DE tolerances must be finite and nonnegative.")
        if self.nm_initial_simplex is not None:
            try:
                simplex = np.asarray(self.nm_initial_simplex, dtype=float)
            except (TypeError, ValueError) as exc:
                raise FitError("Initial simplex must be a numeric matrix.") from exc
            if simplex.ndim != 2 or simplex.shape[0] != simplex.shape[1] + 1 or not np.all(np.isfinite(simplex)):
                raise FitError("Initial simplex must be a finite (N+1) by N matrix.")



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
    fixed: bool = False
    link_relation: str = "equal"
    link_tolerance: float = 0.0
    link_tolerance_mode: str = "absolute"
    global_minimum: float | None = None
    global_maximum: float | None = None

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
    covariance: np.ndarray | BlockDiagonalMatrix | None = None
    correlation: np.ndarray | BlockDiagonalMatrix | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    elapsed_seconds: float = 0.0
    cancelled: bool = False
    paused_curve_id: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

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
            "covariance": matrix_payload(self.covariance) if arrays else None,
            "correlation": matrix_payload(self.correlation) if arrays else None,
            "timestamp": self.timestamp,
            "elapsed_seconds": self.elapsed_seconds,
            "cancelled": self.cancelled,
            "paused_curve_id": self.paused_curve_id,
            "provenance": self.provenance,
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
                matrix_from_value(value["covariance"])
                if value.get("covariance") is not None
                else None
            ),
            correlation=(
                matrix_from_value(value["correlation"])
                if value.get("correlation") is not None
                else None
            ),
            timestamp=str(value.get("timestamp", datetime.now(UTC).isoformat())),
            elapsed_seconds=float(value.get("elapsed_seconds", 0.0)),
            cancelled=bool(value.get("cancelled", False)),
            paused_curve_id=value.get("paused_curve_id"),
            provenance=copy.deepcopy(value.get("provenance", {})),
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


class _ProcessCancellationToken:
    """Read a shared cancellation flag inside a spawned fit process."""

    def __init__(self, event: Any) -> None:
        self._event = event

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise FitCancelled("Fit cancelled by the user.")


_FIT_STOP_EVENT: Any = None
_FIT_WORKER_REGISTRY: FunctionRegistry | None = None


def _init_fit_process(event: Any, formulas: Mapping[str, Any] | None = None) -> None:
    global _FIT_STOP_EVENT, _FIT_WORKER_REGISTRY
    _FIT_STOP_EVENT = event
    _FIT_WORKER_REGISTRY = registry_from_worker_formulas(formulas or {})


def _fit_in_process(curve: Curve, model: Model, plan: FitPlan) -> FitResult:
    # A separate process owns its copy of the spectrum and model. The parent
    # commits the returned estimates only after the task has completed.
    try:
        return Fitter(_FIT_WORKER_REGISTRY)._fit_problem(
            [curve], {curve.id: model}, plan, _ProcessCancellationToken(_FIT_STOP_EVENT), None,
        )
    except FitCancelled:
        raise
    except (FitError, ConstraintError) as exc:
        return _failed_fit_result(curve, plan, exc)


def _failed_fit_result(curve: Curve, plan: FitPlan, error: Exception) -> FitResult:
    message = f"Fit failed for '{curve.name}': {error}"
    return FitResult(False, plan.mode, message, -1, 0, {}, {}, {}, [message],
                     copy.deepcopy(plan.settings), [])


def weighted_residual(residual, point_scale, spectrum_weight):
    if point_scale is not None:
        residual = residual * point_scale
    return residual * math.sqrt(spectrum_weight)


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
        self._jacobian_base: tuple[np.ndarray, np.ndarray] | None = None

        for curve in self.curves:
            if curve.id not in models:
                raise FitError(f"Curve '{curve.name}' has no model.")
            model = models[curve.id]
            model.validate(registry)
            for path, parameter in model.parameter_map(curve.id).items():
                if path in self.parameters:
                    raise FitError(f"Duplicate parameter path: {path}")
                self.parameters[path] = parameter
            self._data[curve.id] = curve.fit_arrays(use_data_errors=plan.settings.use_data_errors)
        # Only enabled model parameters and their transitive link dependencies
        # affect the objective. Disabled independent components must not add DOF.
        from curvemole.core.expressions import SafeExpression
        active = {model.parameter_path(curve.id, component.id, name)
                  for curve in self.curves for model in [models[curve.id]]
                  for component in model.components if component.enabled
                  for name in component.parameters}
        pending = list(active)
        while pending:
            path = pending.pop()
            if path not in self.parameters:
                raise ConstraintError(f"Linked parameter does not exist: {path}")
            link = self.parameters[path].link
            if link:
                for dependency in SafeExpression.compile(link).references:
                    if dependency not in active:
                        active.add(dependency)
                        pending.append(dependency)
        self.parameters = {path: value for path, value in self.parameters.items() if path in active}
        self.free_paths = [path for path, parameter in self.parameters.items() if parameter.is_free]
        if not self.free_paths:
            raise FitError("The selected models contain no free parameters.")
        self.coordinates = (
            DynamicParameterCoordinates(self.parameters, self.free_paths)
            if any(parameter.link and (parameter.link_relation != "equal"
                                       or math.isfinite(parameter.minimum)
                                       or math.isfinite(parameter.maximum))
                   for parameter in self.parameters.values()) else None
        )
        if self.coordinates is None:
            self._parameter_resolver = EqualityParameterResolver(self.parameters)
            self._parameter_resolver.resolve()
        else:
            # A newly added bound may exclude the previous starting value.
            # Build a feasible starting point before validating the graph.
            self.values(self.initial)
        self.scales = parameter_scales(self.parameters, self.free_paths, self.curves, self.coordinates)
        structure = residual_sparsity(
            self.curves, self.models, self.parameters, self.free_paths, self._data)
        self._jacobian_sparsity = None
        if structure is not None:
            from scipy.optimize._numdiff import group_columns
            self._jacobian_sparsity = (structure, group_columns(structure))

    @property
    def initial(self) -> np.ndarray:
        if self.coordinates is not None:
            return self.coordinates.initial()
        return np.asarray([self.parameters[path].value for path in self.free_paths], dtype=float)

    @property
    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        if self.coordinates is not None:
            return self.coordinates.bounds
        lower = np.asarray([self.parameters[path].minimum for path in self.free_paths], dtype=float)
        upper = np.asarray([self.parameters[path].maximum for path in self.free_paths], dtype=float)
        return lower, upper

    def values(self, vector: np.ndarray, *, commit: bool = False) -> dict[str, float]:
        if self.coordinates is None:
            for path, value in zip(self.free_paths, vector, strict=True):
                self.parameters[path].value = float(value)
            values = self._parameter_resolver.resolve()
        else:
            values = self.coordinates.decode(vector)
            for path, value in values.items():
                self.parameters[path].value = float(value)
        if commit:
            for path, value in values.items():
                self.parameters[path].value = float(value)
        return values

    def physical_bounds(self, path: str, values: Mapping[str, float]) -> tuple[float, float]:
        if self.coordinates is not None:
            return self.coordinates.physical_bounds(path, values)
        parameter = self.parameters[path]
        return parameter.minimum, parameter.maximum

    def physical_free_jacobian(self, vector: np.ndarray) -> np.ndarray:
        """Differentiate physical free parameters with respect to solver coordinates."""
        if self.coordinates is None:
            return np.eye(len(self.free_paths))

        def physical(point: np.ndarray) -> np.ndarray:
            values = self.values(point)
            return np.asarray([values[path] for path in self.free_paths])

        from scipy.optimize._numdiff import approx_derivative
        try:
            return np.atleast_2d(approx_derivative(
                physical,
                vector, method="3-point", bounds=self.bounds,
                abs_step=derivative_steps(vector, self.scales),
            ))
        finally:
            self.values(vector, commit=True)

    def residual(self, vector: np.ndarray, *, report: bool = True) -> np.ndarray:
        self.cancellation.raise_if_cancelled()
        if report:
            self.evaluations += 1
        values = self.values(vector)
        residuals: list[np.ndarray] = []
        for curve in self.curves:
            _, observed, point_scale, indices = self._data[curve.id]
            fitted = self.models[curve.id].evaluate_for_curve(
                curve, indices, values=values, registry=self.registry
            )
            if not np.all(np.isfinite(fitted)):
                raise FitError(f"Model for curve '{curve.name}' returned non-finite values.")
            point_scale = self._point_scale(curve, fitted, indices, point_scale)
            residuals.append(weighted_residual(fitted - observed, point_scale, self.objective_weight(curve)))
        from curvemole.core.live_fit_progress import LIVE_REFRESH_EVERY
        if report and self.progress and (self.evaluations % LIVE_REFRESH_EVERY == 0
                                         or self.evaluations == self.plan.settings.max_nfev):
            maximum = max(1, self.plan.settings.max_nfev)
            self.progress(min(self.evaluations / maximum, 1.0), f"Evaluation {self.evaluations}")
        residual = np.concatenate(residuals)
        if report:
            self._jacobian_base = (vector.copy(), residual)
        return residual

    def jacobian(self, vector: np.ndarray, *, dense: bool = False):
        # Keep numerical-difference probes out of the solver's nfev budget.
        # Use SciPy's bound-aware two-point routine, as least_squares does.
        from scipy.optimize._numdiff import approx_derivative
        base = self._jacobian_base
        f0 = base[1] if base is not None and np.array_equal(base[0], vector) else None
        try:
            result = approx_derivative(
                lambda point: self.residual(point, report=False),
                vector, method="3-point", bounds=self.bounds, f0=f0,
                abs_step=derivative_steps(vector, self.scales),
                sparsity=self._jacobian_sparsity,
            )
            return result.toarray() if dense and hasattr(result, "toarray") else result
        finally:
            self.values(vector)

    def _point_scale(self, curve, fitted, indices, point_scale):
        if curve.current_error_y_minus is not None:
            return curve.residual_scale(
                fitted, indices, use_data_errors=self.plan.settings.use_data_errors)
        return point_scale

    def objective_weight(self, curve):
        weight = self.plan.spectrum_weights.get(curve.id, 1.0)
        return weight / len(self._data[curve.id][0]) if self.plan.equal_contribution else weight

    def outputs(self, values: Mapping[str, float]) -> dict[str, CurveFitOutput]:
        result: dict[str, CurveFitOutput] = {}
        for curve in self.curves:
            x, observed, point_scale, indices = self._data[curve.id]
            fitted = np.asarray(
                self.models[curve.id].evaluate_for_curve(
                    curve, indices, values=values, registry=self.registry
                )
            )
            residual = observed - fitted
            point_scale = self._point_scale(curve, fitted, indices, point_scale)
            weighted = weighted_residual(residual, point_scale, self.objective_weight(curve))
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
                    "likelihood_supported": int(
                        not curve.has_correlated_y_errors
                        and (not self.plan.settings.use_data_errors or curve.current_error_y_minus is None)
                        and not self.plan.equal_contribution
                        and self.plan.spectrum_weights.get(curve.id, 1.0) == 1.0),
                    "noise_scale_known": int(absolute_noise_scale(self.plan.settings, self.curves)),
                    "log_precision_sum": (float(np.log(point_scale).sum())
                                          if point_scale is not None else 0.0),
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
        on_curve_result: CurveResultCallback | None = None,
        _record_provenance: bool = True,
    ) -> FitResult:
        plan.validate()
        curve_map = {curve.id: curve for curve in curves} if not isinstance(curves, Mapping) else curves
        try:
            selected = [curve_map[curve_id] for curve_id in plan.curve_ids]
        except KeyError as exc:
            raise FitError(f"Fit plan references unknown curve: {exc.args[0]}") from exc
        cancellation = cancellation or CancellationToken()
        from curvemole.core.provenance import fit_record
        record = fit_record(plan, selected, models, self.registry) if _record_provenance else None
        if on_curve_result is not None and record is not None:
            callback = on_curve_result
            def on_curve_result(curve_id, current):
                from curvemole.core.provenance import select_fit_record
                local_record = select_fit_record(record, curve_id)
                local_record['executions'] = copy.deepcopy(current.provenance.get('executions', []))
                current.provenance = local_record
                callback(curve_id, current)
        started = time.monotonic()
        if plan.mode == FitMode.GLOBAL:
            result = self._fit_problem(selected, models, plan, cancellation, progress)
        elif plan.mode == FitMode.SEQUENTIAL:
            result = self._fit_sequential(selected, models, plan, cancellation, progress)
        elif plan.mode == FitMode.INDEPENDENT and len(selected) > 1 and plan.settings.workers > 1:
            result = self._fit_independent_parallel(selected, models, plan, cancellation, progress, on_curve_result)
        else:
            result = self._fit_independent(selected, models, plan, cancellation, progress, on_curve_result)
        result.elapsed_seconds = time.monotonic() - started
        if record is not None:
            record['executions'] = result.provenance.get('executions', [])
            result.provenance = record
        if progress and not result.paused_curve_id:
            progress(1.0, result.message)
        return result

    def replay(self, result: FitResult, curves, *, verify_environment=True, **kwargs):
        """Replay saved initial conditions, rejecting changed data/definitions."""
        from curvemole.core.provenance import environment_record, function_records
        record = result.provenance
        if record.get('kind') != 'fit' or not record.get('initial_models'):
            raise FitError('This result has no replayable initial-state provenance.')
        available = {c.id: c for c in curves} if not isinstance(curves, Mapping) else curves
        schema = record.get("schema_version", 1)
        use_data_errors = record["plan"]["settings"].get("use_data_errors", True)
        for cid, digest in record["input_hashes"].items():
            curve = available.get(cid)
            if curve is None or curve.fit_input_hash(schema) != digest:
                raise FitError(f"Cannot replay: input data changed or missing for {cid}.")
            if schema == 1 and not use_data_errors:
                output = result.curve_outputs.get(cid)
                if output is None or not np.array_equal(
                        curve.fit_arrays(use_data_errors=False)[3], output.indices):
                    raise FitError(f"Cannot replay: input data changed or legacy fitted rows are missing for {cid}.")
        models = {cid: Model.from_dict(copy.deepcopy(value))
                  for cid, value in record['initial_models'].items()}
        if {key: value['sha256'] for key, value in function_records(self.registry, models).items()} != {key: value['sha256'] for key, value in record['functions'].items()}:
            raise FitError('Cannot replay: function definitions changed.')
        if verify_environment and environment_record() != record['environment']:
            raise FitError('Cannot replay exactly: numerical environment changed.')
        from curvemole.core.extensions import extensions
        extension = next((entry for entry in extensions.values('fit_solvers')
                          if entry.identifier == record['plan']['settings']['solver']), None)
        identity = None if extension is None else {'identifier': extension.identifier,
                    'owner': extension.owner, 'source_sha256': extension.source_sha256}
        if identity != record.get('solver_extension'):
            raise FitError('Cannot replay: solver extension changed or missing.')
        saved = record['plan']
        if saved['mode'] == 'sequential':
            from curvemole.core.sequential_fit import SequentialFitPlan
            plan_type = SequentialFitPlan
        else:
            plan_type = FitPlan
        plan = plan_type(list(saved['curve_ids']), FitMode(saved['mode']),
                       FitSettings(**saved['settings']), dict(saved['spectrum_weights']),
                       saved['equal_contribution'], **record.get('sequential_options', {}))
        return self.fit(plan, available, models, **kwargs)

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
        on_curve_result: CurveResultCallback | None = None,
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
            try:
                current = self._fit_problem(
                    [curve], models, local_plan, cancellation,
                    progress=_batch_progress(progress, index, len(curves)),
                )
            except FitCancelled:
                raise
            except (FitError, ConstraintError) as exc:
                curve.state = CurveState.FAILED
                current = _failed_fit_result(curve, local_plan, exc)
            results.append(current)
            if on_curve_result:
                on_curve_result(curve.id, current)
            if progress:
                progress((index + 1) / len(curves), f"Completed {curve.name}")
        return _merge_results(results, plan.mode, plan.settings)

    def _fit_independent_parallel(
        self,
        curves: Sequence[Curve],
        models: Mapping[str, Model],
        plan: FitPlan,
        cancellation: CancellationToken,
        progress: ProgressCallback | None,
        on_curve_result: CurveResultCallback | None = None,
    ) -> FitResult:
        from curvemole.core.extensions import extensions

        formulas = worker_formula_specs(self.registry, models, [curve.id for curve in curves])
        # Declarative formulas are rebuilt in workers; executable plugin
        # callbacks and plugin solvers still require the current process.
        if (formulas is None or any(entry.identifier == plan.settings.solver
                                   for entry in extensions.values("fit_solvers"))):
            return self._fit_independent(curves, models, plan, cancellation, progress, on_curve_result)

        jobs = []
        for curve in curves:
            settings = copy.deepcopy(plan.settings)
            settings.workers = 1  # No nested pools for differential evolution.
            local_plan = FitPlan(
                [curve.id], FitMode.INDEPENDENT, settings,
                {curve.id: plan.spectrum_weights.get(curve.id, 1.0)},
                plan.equal_contribution,
            )
            jobs.append((curve, models[curve.id], local_plan))

        # Spawn also works when the GUI invokes the fitter from a QThread.
        context = multiprocessing.get_context("spawn")
        results: dict[str, FitResult] = {}
        stop = context.Event()
        with managed_process_pool(ProcessPoolExecutor(
            max_workers=min(plan.settings.workers, len(curves), os.cpu_count() or 1),
            mp_context=context,
            initializer=_init_fit_process,
            initargs=(stop, formulas),
        )) as pool:
            for index, result in bounded_results(
                pool, jobs, lambda executor, job: executor.submit(_fit_in_process, *job),
                cancellation, stop, limit=2 * min(plan.settings.workers, len(curves), os.cpu_count() or 1),
            ):
                curve = curves[index]
                results[curve.id] = result
                if on_curve_result:
                    on_curve_result(curve.id, result)
                if progress:
                    progress(len(results) / len(curves), f"Completed {curve.name}")

        # Match the serial path: failed fits leave the original model intact.
        for curve in curves:
            result = results[curve.id]
            curve.state = CurveState.FITTED if result.success else CurveState.FAILED
            if result.success:
                for path, parameter in models[curve.id].parameter_map(curve.id).items():
                    estimate = result.parameters.get(path)
                    if estimate is not None:
                        parameter.value = estimate.value
                        parameter.standard_error = estimate.standard_error
                        parameter.ci_low = estimate.ci_low
                        parameter.ci_high = estimate.ci_high
        return _merge_results([results[curve.id] for curve in curves], plan.mode, plan.settings)

    def _fit_sequential(
        self,
        curves: Sequence[Curve],
        models: Mapping[str, Model],
        plan: FitPlan,
        cancellation: CancellationToken,
        progress: ProgressCallback | None,
    ) -> FitResult:
        from curvemole.core.sequential_fit import _fit_sequential_propagating
        return _fit_sequential_propagating(self, curves, models, plan, cancellation, progress)

    def _fit_problem(
        self,
        curves: Sequence[Curve],
        models: Mapping[str, Model],
        plan: FitPlan,
        cancellation: CancellationToken,
        progress: ProgressCallback | None,
    ) -> FitResult:
        from scipy import optimize

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
            scales = problem.scales
            execution = {'curve_ids': [curve.id for curve in curves],
                         'parameter_order': list(problem.free_paths),
                         'initial_solver_vector': initial.tolist(),
                         'parameter_scales': scales.tolist()}
            if plan.mode == FitMode.SEQUENTIAL:
                execution['initial_models'] = {curve.id: copy.deepcopy(models[curve.id].to_dict())
                                               for curve in curves}

            # Solver stopping tolerances operate on dimensionless residuals for
            # unweighted data. A common factor preserves the objective minimum.
            unweighted = not settings.use_data_errors or all(
                not curve.has_y_errors and curve.current_weights is None for curve in curves)
            residual_unit = max(characteristic_scale(data[1]) for data in problem._data.values()) if unweighted else 1.0
            execution['residual_unit'] = residual_unit
            solver_settings = copy.copy(settings)
            solver_settings.f_scale /= residual_unit

            def scaled_residual(vector, *, report=True):
                return problem.residual(vector * scales, report=report) / residual_unit

            def scaled_jacobian(vector, *, dense=False):
                return scale_jacobian(problem.jacobian(vector * scales, dense=dense),
                                      scales / residual_unit)

            if settings.solver == "differential_evolution":
                lower, upper = _automatic_de_bounds(problem, settings)
                if progress:
                    progress(0.0, "Differential Evolution initial search")
                differential = optimize.differential_evolution(
                    lambda vector: _objective(scaled_residual(vector, report=False), solver_settings),
                    list(zip(lower / scales, upper / scales, strict=True)),
                    seed=settings.seed,
                    maxiter=settings.de_maxiter,
                    popsize=settings.de_popsize,
                    mutation=(settings.de_mutation_min, settings.de_mutation_max),
                    recombination=settings.de_recombination,
                    tol=settings.de_tol,
                    atol=settings.de_atol,
                    workers=1,
                    updating="immediate",
                    polish=False,
                    callback=lambda intermediate_result: cancellation.cancelled,
                )
                cancellation.raise_if_cancelled()
                initial = differential.x * scales
            execution['solver_bounds'] = [lower.tolist(), upper.tolist()]
            from curvemole.core.extensions import extensions
            custom = next((entry for entry in extensions.values("fit_solvers")
                           if entry.identifier == settings.solver), None)
            if custom is not None:
                from types import SimpleNamespace
                request = SimpleNamespace(residual=problem.residual,
                    jacobian=lambda vector: problem.jacobian(vector, dense=True),
                    initial=initial.copy(), bounds=(lower.copy(), upper.copy()),
                    settings=copy.deepcopy(settings), cancellation=cancellation)
                least_squares = custom.callback(request)
                cancellation.raise_if_cancelled()
                vector = np.asarray(least_squares.x, dtype=float)
                if (vector.shape != initial.shape or not np.all(np.isfinite(vector))
                        or np.any(vector < lower) or np.any(vector > upper)):
                    raise FitError("Plugin solver returned invalid or out-of-bounds parameters.")
                # Recompute residuals/Jacobian through the standard constrained problem.
                least_squares = SimpleNamespace(x=vector, fun=problem.residual(vector, report=False),
                    jac=problem.jacobian(vector), nfev=int(least_squares.nfev),
                    success=bool(least_squares.success), status=int(least_squares.status),
                    message=str(least_squares.message))
            elif settings.solver in {"nelder_mead", "powell", "lbfgsb"}:
                method = {"nelder_mead": "Nelder-Mead", "powell": "Powell",
                          "lbfgsb": "L-BFGS-B"}[settings.solver]
                options = _minimize_options(settings)
                if settings.solver == "nelder_mead" and settings.nm_initial_simplex is not None:
                    simplex = np.asarray(settings.nm_initial_simplex, dtype=float)
                    if simplex.shape != (len(initial) + 1, len(initial)):
                        raise FitError("Initial simplex dimension does not match the free parameters.")
                    if problem.coordinates is not None:
                        simplex = np.asarray([problem.coordinates.encode(vertex) for vertex in simplex])
                    options["initial_simplex"] = simplex / scales
                    if np.any(simplex < lower) or np.any(simplex > upper):
                        raise FitError("Initial simplex vertices must satisfy parameter bounds.")
                minimised = optimize.minimize(
                    lambda vector: _objective(scaled_residual(vector), solver_settings),
                    initial / scales, method=method,
                    bounds=list(zip(lower / scales, upper / scales, strict=True)),
                    options=options,
                )
                cancellation.raise_if_cancelled()
                from types import SimpleNamespace
                vector = np.clip(minimised.x * scales, lower, upper)
                least_squares = SimpleNamespace(
                    x=vector, fun=problem.residual(vector, report=False),
                    jac=problem.jacobian(vector), nfev=minimised.nfev,
                    success=minimised.success, status=minimised.status,
                    message=minimised.message,
                )
            else:
                method = (settings.solver if settings.solver in {"trf", "dogbox", "lm"}
                          else _select_method(settings, lower, upper))
                if (method == "lm" and settings.local_method == "auto" and settings.solver != "lm"
                        and problem._jacobian_sparsity is not None):
                    method = "trf"
                if method == "lm" and (np.any(np.isfinite(lower)) or
                                       np.any(np.isfinite(upper)) or settings.loss != "linear"):
                    raise FitError("Levenberg-Marquardt requires no bounds and linear loss.")
                least_squares = optimize.least_squares(
                    scaled_residual,
                    initial / scales,
                    jac=(lambda vector: scaled_jacobian(vector, dense=True)) if method == "lm"
                        else scaled_jacobian,
                    bounds=(lower / scales, upper / scales),
                    method=method,
                    loss=settings.loss,
                    f_scale=solver_settings.f_scale,
                    x_scale=settings.x_scale,
                    max_nfev=settings.max_nfev,
                    ftol=settings.ftol,
                    xtol=settings.xtol,
                    gtol=settings.gtol,
                )
                least_squares.x = least_squares.x * scales
                least_squares.jac = scale_jacobian(least_squares.jac, residual_unit / scales)
                least_squares.fun = least_squares.fun * residual_unit
            execution['resolved_method'] = (settings.solver if custom is not None else method)
            if progress:
                progress(
                    min(least_squares.nfev / settings.max_nfev, 1.0),
                    f"Evaluation {least_squares.nfev}",
                )
            cancellation.raise_if_cancelled()
            # Only scipy least_squares modifies J for a robust loss. Minimize
            # and extension paths above already reconstructed the raw J.
            covariance_jacobian = (
                problem.jacobian(least_squares.x)
                if settings.loss != "linear" and custom is None
                and settings.solver not in {"nelder_mead", "powell", "lbfgsb"}
                else least_squares.jac)
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
        weights = [problem.objective_weight(curve) for curve in curves]
        objective_weights = (None if all(weight == 1.0 for weight in weights) else
                             np.repeat(weights, [len(problem._data[c.id][0]) for c in curves]))
        nullspace = []
        covariance, correlation, errors = _covariance(
            scale_jacobian(covariance_jacobian, scales),
            np.asarray(least_squares.fun),
            settings,
            curves,
            warnings,
            objective_weights=objective_weights,
            nullspace=nullspace,
        )
        if covariance is not None:
            covariance = covariance * np.outer(scales, scales)
            errors, correlation = covariance_statistics(covariance)
        estimates = _parameter_estimates(
            problem,
            least_squares.x,
            values,
            covariance,
            errors,
            settings,
            warnings,
            nullspace[0] if nullspace else None,
        )
        if nullspace:
            # The pseudo-inverse is only meaningful on the identifiable subspace.
            covariance = correlation = None
        if covariance is not None and problem.coordinates is not None:
            # Saved/exported covariance is labelled with physical parameter
            # paths, so it must not contain latent gaps or fractions.
            transform = problem.physical_free_jacobian(least_squares.x)
            covariance = transform @ covariance @ transform.T
            errors, correlation = covariance_statistics(covariance)
        statistics = _global_statistics(outputs, len(problem.free_paths), settings.loss)
        if correlation is not None and correlation.size:
            upper_triangle = np.abs(correlation[np.triu_indices_from(correlation, 1)])
            finite_correlations = upper_triangle[np.isfinite(upper_triangle)]
            if finite_correlations.size and np.max(finite_correlations) >= 0.95:
                warnings.append("At least one free-parameter correlation has |r| >= 0.95.")
        rows, columns = least_squares.jac.shape
        if rows < columns:
            warnings.append("The fit is underdetermined.")
        elif rows == columns:
            warnings.append("The fit has no positive residual degrees of freedom.")
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
            provenance={'executions': [execution]},
        )
        if least_squares.success:
            for curve in curves:
                curve.state = CurveState.FITTED
        else:
            _restore_parameters(problem.parameters, original_parameter_state)
            for curve in curves:
                curve.state = CurveState.FAILED
        return result


def _minimize_options(settings: FitSettings) -> dict[str, Any]:
    """Translate explicit controls without changing the historical SciPy defaults."""
    if settings.solver == "nelder_mead":
        options = dict(maxfev=settings.max_nfev, xatol=settings.nm_xatol,
                       fatol=settings.nm_fatol, adaptive=settings.nm_adaptive)
        if settings.nm_initial_simplex is not None:
            options["initial_simplex"] = np.asarray(settings.nm_initial_simplex, dtype=float)
    elif settings.solver == "powell":
        options = dict(maxfev=settings.max_nfev, xtol=settings.powell_xtol,
                       ftol=settings.powell_ftol)
    else:
        options = dict(maxfun=settings.max_nfev, ftol=settings.lbfgsb_ftol,
                       gtol=settings.lbfgsb_gtol, maxls=settings.lbfgsb_maxls,
                       maxcor=settings.lbfgsb_maxcor)
    if settings.minimize_maxiter:
        options["maxiter"] = settings.minimize_maxiter
    return options


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


def _objective(residual: np.ndarray, settings: FitSettings) -> float:
    """The same robust loss used by least_squares, including f_scale."""
    if settings.loss == "linear":
        return _sum_of_squares(residual)
    z = (residual / settings.f_scale) ** 2
    if settings.loss == "soft_l1":
        rho = 2 * np.expm1(np.log1p(z) / 2)
    elif settings.loss == "huber":
        rho = np.where(z <= 1, z, 2 * np.sqrt(z) - 1)
    else:
        rho = np.log1p(z)
    return float(settings.f_scale**2 * np.sum(rho))


def _automatic_de_bounds(problem: _Problem, settings: FitSettings) -> tuple[np.ndarray, np.ndarray]:
    """Fill only missing bounds, centred on each current parameter value."""
    lower, upper = (array.copy() for array in problem.bounds)
    xs = np.concatenate([data[0] for data in problem._data.values()])
    ys = np.concatenate([data[1] for data in problem._data.values()])
    x_span = float(np.ptp(xs))
    y_span = float(np.ptp(ys))
    for index, path in enumerate(problem.free_paths):
        value = float(problem.initial[index])
        if not math.isfinite(value):
            raise FitError(f"Differential Evolution needs a finite initial value for {path}.")
        if value:
            scale = abs(value)
        else:
            name = problem.parameters[path].name.lower()
            if name in {"center", "position"}:
                scale = x_span
            elif name == "area":
                scale = y_span * x_span
            elif name == "slope":
                scale = y_span / x_span if x_span else y_span
            else:
                scale = y_span
            scale = max(scale, float(problem.scales[index]))
        if not math.isfinite(lower[index]):
            lower[index] = value - scale * settings.de_lower_percent / 100
        if not math.isfinite(upper[index]):
            upper[index] = value + scale * settings.de_upper_percent / 100
        if not (math.isfinite(lower[index]) and math.isfinite(upper[index])
                and lower[index] < upper[index]):
            raise FitError(f"Cannot create finite search bounds for {path}; adjust its limits.")
    return lower, upper


def _restore_parameters(
    parameters: Mapping[str, Parameter],
    snapshot: Mapping[str, tuple[float, float | None, float | None, float | None]],
) -> None:
    for path, state in snapshot.items():
        if path not in parameters:
            continue
        parameter = parameters[path]
        parameter.value, parameter.standard_error, parameter.ci_low, parameter.ci_high = state


def absolute_noise_scale(settings: FitSettings, curves: Sequence[Curve]) -> bool:
    """Whether residual scale is known, rather than estimated from fitted RSS."""
    if not settings.use_data_errors:
        return False
    if settings.absolute_sigma is not None:
        return settings.absolute_sigma
    return all(curve.has_y_errors for curve in curves)


def _covariance(
    jacobian: np.ndarray,
    weighted_residual: np.ndarray,
    settings: FitSettings,
    curves: Sequence[Curve],
    warnings: list[str],
    *,
    objective_weights: np.ndarray | None = None,
    nullspace: list[np.ndarray] | None = None,
) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    rows, columns = jacobian.shape
    if any(curve.has_correlated_y_errors for curve in curves):
        warnings.append("Covariance is unavailable for correlated data errors after preprocessing.")
        return None, None, None
    absolute = absolute_noise_scale(settings, curves)
    if rows < columns or columns == 0 or (rows == columns and (not absolute or settings.loss != "linear")):
        warnings.append("Covariance is unavailable because degrees of freedom are not positive.")
        return None, None, None
    try:
        singular_values, vh = jacobian_svd(jacobian)
        # Three-point numerical derivatives have rounding and truncation
        # noise beyond machine epsilon; don't invert those null directions.
        precision = np.finfo(float).eps
        threshold = max(precision * max(jacobian.shape), 8 * precision**(2/3)) * singular_values[0]
        keep = singular_values > threshold
        if np.count_nonzero(keep) < columns:
            warnings.append("Covariance is rank-deficient; only identifiable parameter combinations have errors.")
            if nullspace is not None:
                nullspace.append(vh[~keep])
            if rows == columns:
                return None, None, None
        bread = (vh[keep].T / singular_values[keep] ** 2) @ vh[keep]
        if settings.loss != "linear":
            # J must differentiate the original weighted residual, not SciPy's
            # loss-modified Jacobian. psi is expressed in residual units.
            z = (weighted_residual / settings.f_scale) ** 2
            if settings.loss == "huber":
                root = np.sqrt(np.maximum(z, np.finfo(float).tiny))
                rho_prime = np.where(z <= 1, 1.0, 1 / root)
                psi_prime = (z < 1).astype(float)
            elif settings.loss == "soft_l1":
                rho_prime = 1 / np.sqrt(1 + z)
                psi_prime = (1 + z) ** -1.5
            else:  # cauchy
                rho_prime = 1 / (1 + z)
                psi_prime = (1 - z) / (1 + z) ** 2
            influence = weighted_residual * rho_prime
            sensitivity = weighted_gram(jacobian, psi_prime)
            if np.linalg.matrix_rank(sensitivity) < columns:
                warnings.append("Robust covariance is unavailable: singular influence sensitivity.")
                return None, None, None
            bread = np.linalg.pinv(sensitivity, hermitian=True)
            meat = weighted_gram(jacobian, influence ** 2)
            covariance = bread @ meat @ bread.T * rows / (rows - columns)
            warnings.append(
                "Robust-loss uncertainty uses a sandwich covariance; resampling is recommended."
            )
        else:
            covariance = bread
            if objective_weights is not None:
                if absolute:
                    covariance = bread @ weighted_gram(jacobian, objective_weights) @ bread.T
                elif np.all(objective_weights == objective_weights[0]):
                    # A uniform multiplier cancels in RSS-scaled covariance.
                    pass
                else:
                    warnings.append("Covariance is unavailable with arbitrary spectrum weights and unknown noise scale.")
                    return None, None, None
            if not absolute:
                covariance = covariance * float(np.dot(weighted_residual, weighted_residual)) / (
                    rows - columns
                )
        errors, correlation = covariance_statistics(covariance)
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
    nullspace: np.ndarray | None = None,
) -> dict[str, ParameterEstimate]:
    free_index = {path: index for index, path in enumerate(problem.free_paths)}
    from scipy.special import ndtri
    z_value = float(ndtri(0.5 + settings.confidence_level / 2))
    estimates: dict[str, ParameterEstimate] = {}
    linked_gradients: dict[str, np.ndarray] = {}
    all_paths = [path for path, parameter in problem.parameters.items()
                 if parameter.link and not (parameter.fixed and parameter.link_relation != "equal")]
    if covariance is not None and all_paths:
        from scipy.optimize._numdiff import approx_derivative

        def linked(point):
            current = problem.values(point)
            return np.asarray([current[path] for path in all_paths], dtype=float)

        step = derivative_steps(optimum, problem.scales)
        try:
            coarse = np.atleast_2d(approx_derivative(linked, optimum, method="3-point",
                                                   bounds=problem.bounds, abs_step=step))
            fine = np.atleast_2d(approx_derivative(linked, optimum, method="3-point",
                                                 bounds=problem.bounds, abs_step=step / 2))
            gradients = (4 * fine - coarse) / 3
        finally:
            problem.values(optimum, commit=True)
        linked_gradients = {path: gradients[index] for index, path in enumerate(all_paths)}

    for path, parameter in problem.parameters.items():
        error: float | None = None
        if (path in free_index and free_errors is not None
                and not (problem.coordinates is not None and path in problem.coordinates.dynamic)):
            index = free_index[path]
            if nullspace is None or np.linalg.norm(nullspace[:, index]) <= 1e-8:
                error = float(free_errors[index])
        elif (parameter.link and covariance is not None
              and not (parameter.fixed and parameter.link_relation != "equal")):
            gradient = linked_gradients[path]
            scaled_gradient = gradient * problem.scales
            if (nullspace is None or np.linalg.norm(nullspace @ scaled_gradient)
                    <= 1e-8 * np.linalg.norm(scaled_gradient)):
                variance = float(gradient @ covariance @ gradient)
                error = math.sqrt(max(variance, 0))
        value = float(values[path])
        minimum, maximum = problem.physical_bounds(path, values)
        physical_scale = (problem.scales[free_index[path]] if path in free_index
                          else max(abs(value), np.finfo(float).tiny))
        if problem.coordinates is not None and path in problem.coordinates.dynamic:
            physical_scale = max(abs(value), abs(values[problem.coordinates.sources[path]]),
                                 np.finfo(float).tiny)
        tolerance = max(1e-8 * physical_scale, 4 * abs(np.spacing(value)))
        global_minimum, global_maximum = (
            problem.coordinates.domains[path] if problem.coordinates is not None
            else (parameter.minimum, parameter.maximum)
        )
        at_bound = (
            math.isfinite(minimum) and abs(value - minimum) <= tolerance
        ) or (math.isfinite(maximum) and abs(value - maximum) <= tolerance)
        if at_bound:
            warnings.append(f"Parameter '{path}' is at an active bound; its interval is asymmetric.")
        # A confidence interval is marginal over the source's uncertainty.
        # Its source can move together with this parameter, so current-source
        # bounds describe the optimum, not the allowed marginal interval.
        ci_low = max(global_minimum, value - z_value * error) if error is not None else None
        ci_high = min(global_maximum, value + z_value * error) if error is not None else None
        parameter.standard_error = error
        parameter.ci_low = ci_low
        parameter.ci_high = ci_high
        estimates[path] = ParameterEstimate(
            path=path,
            value=value,
            standard_error=error,
            ci_low=ci_low,
            ci_high=ci_high,
            minimum=minimum,
            maximum=maximum,
            status=parameter.status,
            link=parameter.link,
            at_bound=at_bound,
            fixed=parameter.fixed and not (parameter.link and parameter.link_relation == "equal"),
            link_relation=parameter.link_relation,
            link_tolerance=parameter.link_tolerance,
            link_tolerance_mode=parameter.link_tolerance_mode,
            global_minimum=global_minimum,
            global_maximum=global_maximum,
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
    supported = all(item.statistics.get("likelihood_supported", int(np.array_equal(
        item.residual, item.weighted_residual))) for item in outputs.values())
    if loss == "linear" and n > 0 and supported:
        known = all(item.statistics.get("noise_scale_known", 0) for item in outputs.values())
        log_precision = sum(float(item.statistics.get("log_precision_sum", 0.0))
                            for item in outputs.values())
        if known:
            deviance = chi_square + n * math.log(2 * math.pi) - 2 * log_precision
            likelihood_k = k
        elif chi_square > 0:
            deviance = n * (math.log(2 * math.pi) + 1 + math.log(chi_square / n)) - 2 * log_precision
            likelihood_k = k + 1  # the estimated common noise scale is a parameter
        else:
            return result  # zero estimated variance has no finite maximised likelihood
        _information_criteria(result, deviance, likelihood_k, n)
    return result


def _information_criteria(result, deviance: float, parameter_count: int, n: int) -> None:
    result["negative_twice_log_likelihood"] = deviance
    result["likelihood_parameters"] = parameter_count
    result["AIC"] = deviance + 2 * parameter_count
    result["AICc"] = (result["AIC"] + 2 * parameter_count * (parameter_count + 1)
                      / (n - parameter_count - 1) if n > parameter_count + 1 else None)
    result["BIC"] = deviance + parameter_count * math.log(n)


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
    completed = sum(result.success for result in results)
    message = (f"Completed {len(results)} fit(s)." if completed == len(results)
               else f"Completed {completed} of {len(results)} fit(s); {len(results) - completed} failed.")
    covariance = None
    correlation = None
    if all(result.covariance is not None for result in results):
        blocks = []
        for result in results:
            blocks.extend(result.covariance.blocks if isinstance(result.covariance, BlockDiagonalMatrix)
                          else (result.covariance,))
        covariance = BlockDiagonalMatrix(blocks)
        correlations = []
        for block in blocks:
            _, corr = covariance_statistics(block)
            correlations.append(corr)
        correlation = BlockDiagonalMatrix(correlations)
    statistics = _global_statistics(outputs, len(free_paths), settings.loss) if outputs else {}
    if all("negative_twice_log_likelihood" in r.statistics for r in results):
        _information_criteria(statistics,
            sum(r.statistics["negative_twice_log_likelihood"] for r in results),
            sum(r.statistics["likelihood_parameters"] for r in results),
            int(statistics["N"]))
    else:
        for key in ("AIC", "AICc", "BIC"):
            statistics[key] = None
    return FitResult(
        success=all(result.success for result in results),
        mode=mode,
        message=message,
        status=1 if all(result.success for result in results) else -1,
        evaluations=sum(result.evaluations for result in results),
        parameters=parameters,
        curve_outputs=outputs,
        statistics=statistics,
        warnings=warnings,
        settings=copy.deepcopy(settings),
        free_parameter_paths=free_paths,
        covariance=covariance,
        correlation=correlation,
        provenance={'executions': [execution for result in results
                                   for execution in result.provenance.get('executions', [])]},
    )
