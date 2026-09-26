"""On-demand profile, Monte Carlo, and bootstrap uncertainty analyses."""

from __future__ import annotations

import copy
import math
import multiprocessing
import os
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from curvemole.core.data import Curve
from curvemole.core.diagnostics import estimate_block_length
from curvemole.core.errors import FitError
from curvemole.core.fitting import (
    CancellationToken,
    FitPlan,
    FitResult,
    Fitter,
    _ProcessCancellationToken,
)
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


_WORKER_CONTEXT: tuple[Any, ...] | None = None


def _init_uncertainty_worker(stop: Any, *context: Any) -> None:
    global _WORKER_CONTEXT
    _WORKER_CONTEXT = (stop, *context)


def _parallel_map(
    function: Callable[[Any], Any], inputs: Sequence[Any], workers: int,
    context: tuple[Any, ...], cancellation: CancellationToken,
    progress: Callable[[int], None] | None,
) -> list[Any]:
    """Keep only a few spawned-process jobs queued and return results in input order."""
    mp_context = multiprocessing.get_context("spawn")
    stop = mp_context.Event()
    results: list[Any] = [None] * len(inputs)
    with ProcessPoolExecutor(
        max_workers=min(workers, len(inputs), os.cpu_count() or 1),
        mp_context=mp_context, initializer=_init_uncertainty_worker,
        initargs=(stop, *context),
    ) as pool:
        pending = {}
        next_index = 0
        completed = 0
        try:
            while completed < len(inputs):
                cancellation.raise_if_cancelled()
                while next_index < len(inputs) and len(pending) < 2 * workers:
                    future = pool.submit(function, inputs[next_index])
                    pending[future] = next_index
                    next_index += 1
                done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in done:
                    index = pending.pop(future)
                    results[index] = future.result()
                    completed += 1
                    if progress:
                        progress(completed)
        except BaseException:
            stop.set()
            for future in pending:
                future.cancel()
            raise
    return results


def _parallel_safe(fitter: Fitter, models: Mapping[str, Model], curve_ids: Sequence[str]) -> bool:
    """A spawned process can reconstruct builtin evaluators, but not plugin callbacks."""
    from curvemole.core.functions import builtin_definitions

    builtins = {definition.identifier: definition.evaluator for definition in builtin_definitions()}
    return all(
        component.function_id in builtins
        and fitter.registry.get(component.function_id).evaluator is builtins[component.function_id]
        for curve_id in curve_ids for component in models[curve_id].components if component.enabled
    )


def _resample_trial(
    seed: int, method: str, baseline: FitResult, plan: FitPlan,
    curves: Mapping[str, Curve], models: Mapping[str, Model],
    lengths: Mapping[str, int], fitter: Fitter, cancellation: CancellationToken,
) -> tuple[list[float] | None, str | None]:
    cancellation.raise_if_cancelled()
    rng = np.random.default_rng(seed)
    trial_models = {key: model.clone() for key, model in models.items()}
    trial_curves: dict[str, Curve] = {}
    for curve_id in plan.curve_ids:
        curve = curves[curve_id]
        trial = copy.deepcopy(curve)
        output = baseline.curve_outputs[curve_id]
        full_fit = np.asarray(models[curve_id].evaluate(
            curve.x, curve_id=curve_id, registry=fitter.registry))
        if method == "parametric_monte_carlo":
            sigma = curve.current_sigma_y
            assert sigma is not None
            synthetic = full_fit + rng.normal(0.0, sigma)
        elif method == "residual_bootstrap":
            residual = np.asarray(output.residual)
            synthetic = full_fit + rng.choice(residual - np.mean(residual), size=len(curve), replace=True)
        else:
            residual = np.asarray(output.residual) - np.mean(output.residual)
            length = max(1, min(lengths[curve_id], len(residual)))
            blocks = []
            count = 0
            while count < len(residual):
                start = int(rng.integers(0, len(residual)))
                blocks.append(residual[(start + np.arange(length)) % len(residual)])
                count += length
            synthetic = full_fit.copy()
            synthetic[output.indices] += np.concatenate(blocks)[:len(residual)]
        trial.original_x = np.asarray(curve.x).copy()
        trial.original_y = np.asarray(synthetic).copy()
        trial.sigma_y = (None if curve.current_sigma_y is None
                         else np.asarray(curve.current_sigma_y).copy())
        trial.transformations = []
        trial.redo_transformations = []
        trial.__post_init__()
        trial_curves[curve_id] = trial
    try:
        result = fitter.fit(copy.deepcopy(plan), trial_curves, trial_models, cancellation=cancellation)
        if result.success:
            return [result.parameters[path].value for path in baseline.free_parameter_paths], None
        return None, result.message
    except FitError as exc:
        return None, str(exc)


def _resample_in_process(seed: int) -> tuple[list[float] | None, str | None]:
    assert _WORKER_CONTEXT is not None
    stop, method, baseline, plan, curves, models, lengths = _WORKER_CONTEXT
    return _resample_trial(seed, method, baseline, plan, curves, models, lengths,
                           Fitter(), _ProcessCancellationToken(stop))


def _profile_trial(
    value: float, curve: Curve, model: Model, parameter_path: str,
    baseline: FitResult, baseline_chi: float, spectrum_weight: float,
    equal_contribution: bool, fitter: Fitter, cancellation: CancellationToken,
) -> float | None:
    cancellation.raise_if_cancelled()
    trial_model = model.clone()
    trial_parameter = trial_model.parameter_map(curve.id)[parameter_path]
    trial_parameter.value = float(value)
    trial_parameter.fixed = True
    settings = copy.deepcopy(baseline.settings)
    settings.solver = "local"
    settings.workers = 1
    try:
        if any(p.is_free and path in baseline.free_parameter_paths
               for path, p in trial_model.parameter_map(curve.id).items()):
            trial_plan = FitPlan([curve.id], settings=settings,
                                 spectrum_weights={curve.id: spectrum_weight},
                                 equal_contribution=equal_contribution)
            result = fitter.fit(trial_plan, [copy.deepcopy(curve)],
                                {curve.id: trial_model}, cancellation=cancellation)
            if not result.success:
                raise FitError(result.message)
            chi = float(result.statistics["chi_square"])
        else:
            x, observed, scale, _ = curve.fit_arrays()
            residual = observed - trial_model.evaluate(
                x, curve_id=curve.id, registry=fitter.registry)
            if scale is not None:
                residual = residual * scale
            residual *= math.sqrt(spectrum_weight)
            if equal_contribution:
                residual /= math.sqrt(len(residual))
            chi = float(np.dot(residual, residual))
        return max(0.0, chi - baseline_chi)
    except FitError:
        return None


def _profile_in_process(value: float) -> float | None:
    assert _WORKER_CONTEXT is not None
    stop, curve, model, parameter_path, baseline, baseline_chi, spectrum_weight, equal = _WORKER_CONTEXT
    return _profile_trial(value, curve, model, parameter_path, baseline, baseline_chi,
                          spectrum_weight, equal, Fitter(), _ProcessCancellationToken(stop))


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
        replicates: int = 200,
        seed: int | None = None,
        workers: int = 1,
        cancellation: CancellationToken | None = None,
        progress: Callable[[float | None, str], None] | None = None,
    ) -> ResamplingResult:
        curve_map = _curve_map(curves)
        for curve_id in plan.curve_ids:
            if curve_map[curve_id].current_sigma_y is None:
                raise FitError(
                    f"Parametric Monte Carlo requires absolute sigma_y for '{curve_map[curve_id].name}'."
                )

        return self._resample(
            "parametric_monte_carlo",
            baseline,
            plan,
            curve_map,
            models,
            replicates,
            seed,
            workers,
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
        replicates: int = 200,
        seed: int | None = None,
        workers: int = 1,
        cancellation: CancellationToken | None = None,
        progress: Callable[[float | None, str], None] | None = None,
    ) -> ResamplingResult:
        curve_map = _curve_map(curves)

        return self._resample(
            "residual_bootstrap",
            baseline,
            plan,
            curve_map,
            models,
            replicates,
            seed,
            workers,
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
        replicates: int = 200,
        block_length: int | None = None,
        seed: int | None = None,
        workers: int = 1,
        cancellation: CancellationToken | None = None,
        progress: Callable[[float | None, str], None] | None = None,
    ) -> ResamplingResult:
        curve_map = _curve_map(curves)
        lengths = {
            curve_id: block_length or estimate_block_length(baseline.curve_outputs[curve_id].residual)
            for curve_id in plan.curve_ids
        }

        return self._resample(
            "block_bootstrap",
            baseline,
            plan,
            curve_map,
            models,
            replicates,
            seed,
            workers,
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
        spectrum_weight: float = 1.0,
        equal_contribution: bool = False,
        workers: int = 1,
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
        if not math.isfinite(spectrum_weight) or spectrum_weight <= 0:
            raise FitError("Profile spectrum weight must be positive and finite.")
        if not 0 < confidence_level < 1 or points < 3:
            raise FitError("Profile requires 0 < confidence < 1 and at least three grid points.")
        if not isinstance(workers, int) or workers < 1:
            raise FitError("Worker process count must be a positive integer.")
        if lo < parameter.minimum or hi > parameter.maximum:
            raise FitError("Profile scan limits must respect parameter bounds.")
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
        def report(count: int) -> None:
            if progress:
                progress(count / points, f"Profile point {count}/{points}")

        if workers > 1 and _parallel_safe(self.fitter, {curve.id: model}, [curve.id]):
            values = _parallel_map(
                _profile_in_process, grid.tolist(), workers,
                (curve, model, parameter_path, baseline, baseline_chi,
                 spectrum_weight, equal_contribution), token, report,
            )
        else:
            values = []
            for index, value in enumerate(grid):
                values.append(_profile_trial(
                    value, curve, model, parameter_path, baseline, baseline_chi,
                    spectrum_weight, equal_contribution, self.fitter, token))
                report(index + 1)
        for index, value in enumerate(values):
            if value is None:
                failed += 1
            else:
                delta[index] = value
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
        replicates: int,
        seed: int | None,
        workers: int,
        cancellation: CancellationToken | None,
        progress: Callable[[float | None, str], None] | None,
        extra_configuration: dict[str, Any],
    ) -> ResamplingResult:
        if replicates <= 0:
            raise FitError("The requested number of replicates must be positive.")
        if not isinstance(workers, int) or workers < 1:
            raise FitError("Worker process count must be a positive integer.")
        token = cancellation or CancellationToken()
        selected_seed = baseline.settings.seed if seed is None else seed
        rng = np.random.default_rng(selected_seed)
        paths = list(baseline.free_parameter_paths)
        base_models = {key: model.clone() for key, model in models.items()}
        settings = copy.deepcopy(plan.settings)
        settings.solver = "local"
        settings.workers = 1
        trial_plan = copy.deepcopy(plan)
        trial_plan.settings = settings
        lengths = extra_configuration.get("block_lengths", {})
        seeds = rng.integers(0, np.iinfo(np.int64).max, size=replicates).tolist()
        parallel = workers > 1 and replicates > 1 and _parallel_safe(self.fitter, base_models, plan.curve_ids)

        def report(count: int) -> None:
            if progress:
                progress(count / replicates, f"{method}: {count}/{replicates}")

        if parallel:
            outcomes = _parallel_map(
                _resample_in_process, seeds, workers,
                (method, baseline, trial_plan, curves, base_models, lengths), token, report,
            )
        else:
            outcomes = []
            for replicate, trial_seed in enumerate(seeds):
                outcomes.append(_resample_trial(
                    trial_seed, method, baseline, trial_plan, curves, base_models,
                    lengths, self.fitter, token))
                report(replicate + 1)
        collected = [sample for sample, _ in outcomes if sample is not None]
        failures = [message for _, message in outcomes if message is not None]
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
            configuration={"fit_settings": asdict(settings),
                           "workers_used": min(workers, replicates, os.cpu_count() or 1) if parallel else 1,
                           **extra_configuration},
            failure_messages=failures[:100],
        )


def _curve_map(curves: Mapping[str, Curve] | Sequence[Curve]) -> Mapping[str, Curve]:
    return curves if isinstance(curves, Mapping) else {curve.id: curve for curve in curves}


def _chi2_one(confidence_level: float) -> float:
    from scipy.stats import chi2

    return float(chi2.ppf(confidence_level, 1))
