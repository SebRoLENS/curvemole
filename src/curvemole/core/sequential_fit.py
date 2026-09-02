"""Propagating sequential-fit workflow with anomaly monitoring and pause/resume support."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from curvemole.core.data import Curve, CurveState
from curvemole.core.errors import ConstraintError, FitError
from curvemole.core.fitting import (
    CancellationToken,
    FitMode,
    FitPlan,
    FitResult,
    Fitter,
    ProgressCallback,
    _merge_results,
)
from curvemole.core.models import Model
from curvemole.core.parameters import Parameter, resolve_parameter_values


@dataclass(slots=True)
class SequentialFitPlan(FitPlan):
    """Fit plan carrying monitoring preferences for propagating sequential fits."""

    monitor_residuals: bool = True
    residual_ratio_limit: float = 2.5
    residual_nrmse_delta: float = 0.02
    monitor_parameters: bool = True
    parameter_change_limit: float = 0.75

    def validate(self) -> None:
        super().validate()
        if self.residual_ratio_limit <= 1 or not math.isfinite(self.residual_ratio_limit):
            raise FitError("Sequential residual ratio must be finite and greater than 1.")
        if self.residual_nrmse_delta < 0 or not math.isfinite(self.residual_nrmse_delta):
            raise FitError("Sequential residual increase must be finite and non-negative.")
        if self.parameter_change_limit <= 0 or not math.isfinite(self.parameter_change_limit):
            raise FitError("Sequential parameter-change threshold must be finite and positive.")


def _clone_model_for_target(source: Model, source_curve_id: str, target: Curve) -> Model:
    clone = Model.from_dict(copy.deepcopy(source.to_dict()))
    clone.name = f"Model for {target.name}"
    for component in clone.components:
        for parameter in component.parameters.values():
            if parameter.link:
                parameter.link = parameter.link.replace(
                    "${" + source_curve_id + ".",
                    "${" + target.id + ".",
                )
            parameter.standard_error = None
            parameter.ci_low = None
            parameter.ci_high = None
    return clone


def _robust_span(values: np.ndarray) -> float:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return 1.0
    if len(finite) >= 4:
        low, high = np.percentile(finite, [5.0, 95.0])
        span = float(high - low)
        if math.isfinite(span) and span > 0:
            return span
    span = float(np.ptp(finite))
    if math.isfinite(span) and span > 0:
        return span
    scale = float(np.max(np.abs(finite)))
    return scale if math.isfinite(scale) and scale > 0 else 1.0


def _model_nrmse(curve: Curve, model: Model, registry: Any) -> float | None:
    try:
        x, observed, _point_scale, _indices = curve.fit_arrays()
        parameters = model.parameter_map(curve.id)
        values = resolve_parameter_values(parameters)
        fitted = np.asarray(
            model.evaluate(x, curve_id=curve.id, values=values, registry=registry),
            dtype=float,
        )
        residual = np.asarray(observed, dtype=float) - fitted
        if not len(residual) or not np.all(np.isfinite(residual)):
            return None
        rmse = math.sqrt(float(np.dot(residual, residual)) / len(residual))
        return rmse / _robust_span(np.asarray(observed, dtype=float))
    except Exception:
        return None


def _parameter_floor(name: str, curve: Curve, parameter: Parameter) -> float:
    if math.isfinite(parameter.minimum) and math.isfinite(parameter.maximum):
        span = parameter.maximum - parameter.minimum
        if span > 0:
            return 0.10 * span

    lowered = name.casefold()
    x_scale = _robust_span(curve.x)
    y_scale = _robust_span(curve.y)
    if any(token in lowered for token in ("center", "centre", "position", "location", "x0")):
        return 0.05 * x_scale
    if any(token in lowered for token in ("sigma", "width", "gamma", "fwhm", "tau")):
        return 0.05 * x_scale
    if "slope" in lowered:
        return 0.05 * y_scale / max(x_scale, np.finfo(float).eps)
    if any(token in lowered for token in ("area", "amplitude", "height", "offset", "intercept")):
        return 0.05 * y_scale
    return np.finfo(float).eps


def _largest_parameter_jump(
    seed: Model,
    fitted: Model,
    curve: Curve,
) -> tuple[float, str | None, float, float]:
    seed_by_id = {component.id: component for component in seed.components}
    largest = 0.0
    label: str | None = None
    before_value = 0.0
    after_value = 0.0

    for component in fitted.components:
        source_component = seed_by_id.get(component.id)
        if source_component is None:
            continue
        for name, parameter in component.parameters.items():
            source_parameter = source_component.parameters.get(name)
            if source_parameter is None or not parameter.is_free:
                continue
            before = float(source_parameter.value)
            after = float(parameter.value)
            denominator = max(
                abs(before),
                abs(after),
                _parameter_floor(name, curve, parameter),
                np.finfo(float).eps,
            )
            score = abs(after - before) / denominator
            if score > largest:
                largest = score
                label = f"{component.name}.{name}"
                before_value = before
                after_value = after
    return largest, label, before_value, after_value


def _pause_result(
    results: Sequence[FitResult],
    plan: FitPlan,
    curve: Curve,
    message: str,
    *,
    status: int,
    failed: bool,
) -> FitResult:
    merged = _merge_results(results, plan.mode, plan.settings)
    merged.success = False
    merged.status = status
    merged.message = message
    merged.paused_curve_id = curve.id
    if failed:
        curve.state = CurveState.FAILED
    return merged


def _fit_sequential_propagating(
    fitter: Fitter,
    curves: Sequence[Curve],
    models: Mapping[str, Model],
    plan: FitPlan,
    cancellation: CancellationToken,
    progress: ProgressCallback | None,
) -> FitResult:
    if not curves:
        return _merge_results([], plan.mode, plan.settings)
    if not isinstance(models, MutableMapping):
        raise FitError("Sequential propagation requires a writable model collection.")

    source_curve = curves[0]
    source_model = models.get(source_curve.id)
    if source_model is None or not source_model.components:
        return _pause_result(
            [],
            plan,
            source_curve,
            f"Sequential fit needs a prepared source model on '{source_curve.name}'. "
            "Add and adjust the source functions manually, then continue explicitly.",
            status=-2,
            failed=False,
        )

    monitor_residuals = bool(getattr(plan, "monitor_residuals", True))
    residual_ratio_limit = float(getattr(plan, "residual_ratio_limit", 2.5))
    residual_nrmse_delta = float(getattr(plan, "residual_nrmse_delta", 0.02))
    monitor_parameters = bool(getattr(plan, "monitor_parameters", True))
    parameter_change_limit = float(getattr(plan, "parameter_change_limit", 0.75))

    previous_nrmse = _model_nrmse(source_curve, source_model, fitter.registry)
    results: list[FitResult] = []

    # The first curve is deliberately not re-fitted. It is the user-approved seed.
    for index, curve in enumerate(curves[1:], start=1):
        cancellation.raise_if_cancelled()
        previous_curve = curves[index - 1]
        previous_model = models[previous_curve.id]
        propagated = _clone_model_for_target(previous_model, previous_curve.id, curve)
        models[curve.id] = propagated
        seed_model = Model.from_dict(copy.deepcopy(propagated.to_dict()))

        if progress:
            progress(
                index / max(1, len(curves) - 1),
                f"Sequential fit: copy {previous_curve.name} → {curve.name}, then fit",
            )

        local_plan = FitPlan(
            [curve.id],
            FitMode.SEQUENTIAL,
            copy.deepcopy(plan.settings),
            {curve.id: plan.spectrum_weights.get(curve.id, 1.0)},
            plan.equal_contribution,
        )
        try:
            current = fitter._fit_problem(
                [curve],
                models,
                local_plan,
                cancellation,
                progress=None,
            )
        except (FitError, ConstraintError) as exc:
            return _pause_result(
                results,
                plan,
                curve,
                f"Sequential fit paused at '{curve.name}': {exc}. "
                "The propagated model is available for manual correction. "
                "Finish this spectrum manually, then continue the sequence.",
                status=-2,
                failed=True,
            )

        if not current.success:
            return _pause_result(
                results,
                plan,
                curve,
                f"Sequential fit paused at '{curve.name}' because the solver did not converge. "
                "Finish this spectrum manually, then continue the sequence.",
                status=-2,
                failed=True,
            )

        results.append(current)
        reasons: list[str] = []

        output = current.curve_outputs.get(curve.id)
        current_nrmse: float | None = None
        if output is not None:
            rmse = output.statistics.get("RMSE")
            if isinstance(rmse, (int, float)) and math.isfinite(float(rmse)):
                current_nrmse = float(rmse) / _robust_span(output.observed)

        if (
            monitor_residuals
            and previous_nrmse is not None
            and current_nrmse is not None
            and current_nrmse > previous_nrmse * residual_ratio_limit
            and current_nrmse - previous_nrmse >= residual_nrmse_delta
        ):
            reasons.append(
                "normalized residual RMSE increased "
                f"from {previous_nrmse:.4g} to {current_nrmse:.4g} "
                f"({current_nrmse / max(previous_nrmse, np.finfo(float).eps):.2f}×)"
            )

        if monitor_parameters:
            jump, label, before, after = _largest_parameter_jump(seed_model, models[curve.id], curve)
            if label is not None and jump >= parameter_change_limit:
                reasons.append(
                    f"parameter {label} changed strongly: {before:.6g} → {after:.6g} "
                    f"(normalized change {jump * 100:.1f}%)"
                )

        if reasons:
            curve.state = CurveState.FITTED
            return _pause_result(
                results,
                plan,
                curve,
                f"Sequential fit paused for manual review at '{curve.name}' because "
                + "; ".join(reasons)
                + ". Adjust/refit this spectrum manually if needed, then choose Continue paused sequence.",
                status=-3,
                failed=False,
            )

        if current_nrmse is not None:
            previous_nrmse = current_nrmse

    if not results:
        return FitResult(
            success=True,
            mode=FitMode.SEQUENTIAL,
            message="Sequential sequence is complete; there are no subsequent spectra to fit.",
            status=1,
            evaluations=0,
            parameters={},
            curve_outputs={},
            statistics={},
            warnings=[],
            settings=copy.deepcopy(plan.settings),
            free_parameter_paths=[],
        )
    merged = _merge_results(results, FitMode.SEQUENTIAL, plan.settings)
    merged.message = f"Sequential propagation completed {len(results)} spectrum fit(s)."
    return merged


def install_sequential_fit_support() -> None:
    if getattr(Fitter, "_curvemole_propagating_sequential_fit", False):
        return
    Fitter._fit_sequential = _fit_sequential_propagating
    Fitter._curvemole_propagating_sequential_fit = True


install_sequential_fit_support()
