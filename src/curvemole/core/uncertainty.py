"""On-demand profile, Monte Carlo, and bootstrap uncertainty analyses."""

from __future__ import annotations

import copy
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from curvemole.core.data import Curve
from curvemole.core.diagnostics import estimate_block_length
from curvemole.core.errors import FitCancelled, FitError
from curvemole.core.fitting import CancellationToken, FitPlan, FitResult, Fitter
from curvemole.core.models import Model


@dataclass(slots=True)
class ResamplingResult:
    method: str
    requested: int
    completed: int
    failed: int
    seed: int
    parameter_paths: list[str]
    samples: np.ndarray
    intervals: dict[str, tuple[float, float]]
    confidence_level: float
    configuration: dict[str, Any]
    failure_messages: list[str] = field(default_factory=list)

    def to_dict(self, *, include_samples: bool = True) -> dict[str, Any]:
        return {
            "method": self.method,
            "requested": self.requested,
            "completed": self.completed,
            "failed": self.failed,
            "seed": self.seed,
            "parameter_paths": self.parameter_paths,
            "samples": self.samples.tolist() if include_samples else None,
            "intervals": {key: list(value) for key, value in self.intervals.items()},
            "confidence_level": self.confidence_level,
            "configuration": self.configuration,
            "failure_messages": self.failure_messages,
        }


@dataclass(slots=True)
class ProfileResult:
    parameter_path: str
    values: np.ndarray
    delta_chi_square: np.ndarray
    confidence_level: float
    interval: tuple[float | None, float | None]
    failed_points: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_path": self.parameter_path,
            "values": self.values.tolist(),
            "delta_chi_square": self.delta_chi_square.tolist(),
            "confidence_level": self.confidence_level,
            "interval": list(self.interval),
            "failed_points": self.failed_points,
        }


class UncertaintyAnalyzer:
    def __init__(self, fitter: Fitter | None = None) -> None:
        self.fitter = fitter or Fitter()

    def parametric_monte_carlo(
        self,
        baseline: FitResult,
        plan: FitPlan,
        curves: Mapping[str, Curve] | Sequence[Curve],
        models: Mapping[str, Model],
        *,
        replicates: int = 1000,
        seed: int | None = None,
        cancellation: CancellationToken | None = None,
        progress: Callable[[float | None, str], None] | None = None,
    ) -> ResamplingResult:
        curve_map = _curve_map(curves)
        for curve_id in plan.curve_ids:
            if curve_map[curve_id].current_sigma_y is None:
                raise FitError(
                    f"Parametric Monte Carlo requires absolute sigma_y for '{curve_map[curve_id].name}'."
                )

        def simulate(rng: np.random.Generator, curve: Curve, output: Any) -> np.ndarray:
            sigma = curve.current_sigma_y
            assert sigma is not None
            full_fit = np.asarray(
                models[curve.id].evaluate(curve.x, curve_id=curve.id, registry=self.fitter.registry)
            )
            return full_fit + rng.normal(0.0, sigma)

        return self._resample(
            "parametric_monte_carlo",
            baseline,
            plan,
            curve_map,
            models,
            simulate,
            replicates,
            seed,
            cancellation,
            progress,
            {},
        )

    def residual_bootstrap(
        self,
        baseline: FitResult,
        plan: FitPlan,
        curves: Mapping[str, Curve] | Sequence[Curve],
        models: Mapping[str, Model],
        *,
        replicates: int = 1000,
        seed: int | None = None,
        cancellation: CancellationToken | None = None,
        progress: Callable[[float | None, str], None] | None = None,
    ) -> ResamplingResult:
        curve_map = _curve_map(curves)

        def simulate(rng: np.random.Generator, curve: Curve, output: Any) -> np.ndarray:
            full_fit = np.asarray(
                models[curve.id].evaluate(curve.x, curve_id=curve.id, registry=self.fitter.registry)
            )
            residual = np.asarray(output.residual)
            sampled = rng.choice(residual - np.mean(residual), size=len(curve), replace=True)
            return full_fit + sampled

        return self._resample(
            "residual_bootstrap",
            baseline,
            plan,
            curve_map,
            models,
            simulate,
            replicates,
            seed,
            cancellation,
            progress,
            {},
        )

    def block_bootstrap(
        self,
        baseline: FitResult,
        plan: FitPlan,
        curves: Mapping[str, Curve] | Sequence[Curve],
        models: Mapping[str, Model],
        *,
        replicates: int = 1000,
        block_length: int | None = None,
        seed: int | None = None,
        cancellation: CancellationToken | None = None,
        progress: Callable[[float | None, str], None] | None = None,
    ) -> ResamplingResult:
        curve_map = _curve_map(curves)
        lengths = {
            curve_id: block_length or estimate_block_length(baseline.curve_outputs[curve_id].residual)
            for curve_id in plan.curve_ids
        }

        def simulate(rng: np.random.Generator, curve: Curve, output: Any) -> np.ndarray:
            full_fit = np.asarray(
                models[curve.id].evaluate(curve.x, curve_id=curve.id, registry=self.fitter.registry)
            )
            residual = np.asarray(output.residual) - np.mean(output.residual)
            length = max(1, min(lengths[curve.id], len(residual)))
            blocks: list[np.ndarray] = []
            while sum(len(item) for item in blocks) < len(residual):
                start = int(rng.integers(0, len(residual)))
                indices = (start + np.arange(length)) % len(residual)
                blocks.append(residual[indices])
            sampled = np.concatenate(blocks)[: len(residual)]
            return full_fit + sampled

        return self._resample(
            "block_bootstrap",
            baseline,
            plan,
            curve_map,
            models,
            simulate,
            replicates,
            seed,
            cancellation,
            progress,
            {"block_lengths": lengths},
        )

    def profile_parameter(
        self,
        baseline: FitResult,
        curve: Curve,
        model: Model,
        parameter_path: str,
        *,
        lower: float | None = None,
        upper: float | None = None,
        points: int = 31,
        confidence_level: float = 0.95,
        cancellation: CancellationToken | None = None,
        progress: Callable[[float | None, str], None] | None = None,
    ) -> ProfileResult:
        if parameter_path not in model.parameter_map(curve.id):
            raise FitError(f"Unknown profile parameter: {parameter_path}")
        parameter = model.parameter_map(curve.id)[parameter_path]
        if parameter.link:
            raise FitError("Profile likelihood requires an independent, non-linked parameter.")
        estimate = baseline.parameters.get(parameter_path)
        error = estimate.standard_error if estimate else None
        span = 3 * error if error and error > 0 else max(abs(parameter.value) * 0.25, 1.0)
        lo = max(parameter.minimum, parameter.value - span) if lower is None else lower
        hi = min(parameter.maximum, parameter.value + span) if upper is None else upper
        if not math.isfinite(lo) or not math.isfinite(hi) or lo >= hi:
            raise FitError("Profile likelihood needs a finite, increasing interval.")
        grid = np.linspace(lo, hi, points)
        delta = np.full(points, np.nan)
        token = cancellation or CancellationToken()
        failed = 0
        if curve.id not in baseline.curve_outputs:
            raise FitError(f"The baseline result does not contain curve '{curve.name}'.")
        baseline_weighted = baseline.curve_outputs[curve.id].weighted_residual
        baseline_chi = float(np.dot(baseline_weighted, baseline_weighted))
        for index, value in enumerate(grid):
            token.raise_if_cancelled()
            trial_model = model.clone()
            trial_parameter = trial_model.parameter_map(curve.id)[parameter_path]
            trial_parameter.value = float(value)
            trial_parameter.fixed = True
            settings = copy.deepcopy(baseline.settings)
            settings.solver = "local"
            try:
                result = self.fitter.fit_single(curve, trial_model, settings, cancellation=token)
                chi = float(result.statistics.get("chi_square") or math.nan)
                delta[index] = max(0.0, chi - baseline_chi)
            except FitError:
                failed += 1
            if progress:
                progress((index + 1) / points, f"Profile point {index + 1}/{points}")
        threshold = 3.841458820694124 if math.isclose(confidence_level, 0.95) else _chi2_one(confidence_level)
        inside = np.isfinite(delta) & (delta <= threshold)
        interval = (
            float(grid[np.flatnonzero(inside)[0]]) if np.any(inside) else None,
            float(grid[np.flatnonzero(inside)[-1]]) if np.any(inside) else None,
        )
        return ProfileResult(parameter_path, grid, delta, confidence_level, interval, failed)

    def _resample(
        self,
        method: str,
        baseline: FitResult,
        plan: FitPlan,
        curves: Mapping[str, Curve],
        models: Mapping[str, Model],
        simulate: Callable[[np.random.Generator, Curve, Any], np.ndarray],
        replicates: int,
        seed: int | None,
        cancellation: CancellationToken | None,
        progress: Callable[[float | None, str], None] | None,
        extra_configuration: dict[str, Any],
    ) -> ResamplingResult:
        if replicates <= 0:
            raise FitError("The requested number of replicates must be positive.")
        token = cancellation or CancellationToken()
        selected_seed = baseline.settings.seed if seed is None else seed
        rng = np.random.default_rng(selected_seed)
        paths = list(baseline.free_parameter_paths)
        collected: list[list[float]] = []
        failures: list[str] = []
        base_models = {key: model.clone() for key, model in models.items()}
        settings = copy.deepcopy(plan.settings)
        settings.solver = "local"
        for replicate in range(replicates):
            token.raise_if_cancelled()
            trial_curves: dict[str, Curve] = {}
            trial_models = {key: model.clone() for key, model in base_models.items()}
            for curve_id in plan.curve_ids:
                curve = curves[curve_id]
                trial = copy.deepcopy(curve)
                synthetic = simulate(rng, curve, baseline.curve_outputs[curve_id])
                trial.original_x = np.asarray(curve.x).copy()
                trial.original_y = np.asarray(synthetic).copy()
                trial.transformations = []
                trial.redo_transformations = []
                trial.__post_init__()
                trial_curves[curve_id] = trial
            trial_plan = copy.deepcopy(plan)
            trial_plan.settings = copy.deepcopy(settings)
            try:
                result = self.fitter.fit(
                    trial_plan,
                    trial_curves,
                    trial_models,
                    cancellation=token,
                )
                if result.success:
                    collected.append([result.parameters[path].value for path in paths])
                else:
                    failures.append(result.message)
            except (FitError, FitCancelled) as exc:
                if isinstance(exc, FitCancelled):
                    raise
                failures.append(str(exc))
            if progress:
                progress((replicate + 1) / replicates, f"{method}: {replicate + 1}/{replicates}")
        samples = np.asarray(collected, dtype=float)
        if samples.size == 0:
            samples = np.empty((0, len(paths)), dtype=float)
        alpha = (1 - settings.confidence_level) / 2
        intervals = {
            path: (
                float(np.quantile(samples[:, index], alpha)),
                float(np.quantile(samples[:, index], 1 - alpha)),
            )
            for index, path in enumerate(paths)
            if len(samples)
        }
        return ResamplingResult(
            method=method,
            requested=replicates,
            completed=len(samples),
            failed=len(failures),
            seed=selected_seed,
            parameter_paths=paths,
            samples=samples,
            intervals=intervals,
            confidence_level=settings.confidence_level,
            configuration={"fit_settings": asdict(settings), **extra_configuration},
            failure_messages=failures[:100],
        )


def _curve_map(curves: Mapping[str, Curve] | Sequence[Curve]) -> Mapping[str, Curve]:
    return curves if isinstance(curves, Mapping) else {curve.id: curve for curve in curves}


def _chi2_one(confidence_level: float) -> float:
    from scipy.stats import chi2

    return float(chi2.ppf(confidence_level, 1))
