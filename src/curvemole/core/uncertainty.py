"""On-demand profile, Monte Carlo, and bootstrap uncertainty analyses."""

from __future__ import annotations

import copy
import math
import multiprocessing
import os
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from curvemole.core.data import Curve
from curvemole.core.diagnostics import estimate_block_length
from curvemole.core.errors import ConstraintError, FitError
from curvemole.core.expressions import SafeExpression
from curvemole.core.fitting import (
    CancellationToken,
    FitMode,
    FitPlan,
    FitResult,
    Fitter,
    _ProcessCancellationToken,
)
from curvemole.core.models import Model
from curvemole.core.parameters import resolve_parameter_values
from curvemole.core.worker_functions import registry_from_worker_formulas, worker_formula_specs


@dataclass(frozen=True, slots=True)
class AdaptiveReplicateSettings:
    """Stop resampling when all percentile endpoints remain numerically stable."""

    initial_successes: int = 500
    batch_successes: int = 200
    tolerance: float = 0.05
    consecutive_checks: int = 3
    maximum_attempts: int = 10_000

    def validate(self) -> None:
        for value in (self.initial_successes, self.batch_successes,
                      self.consecutive_checks, self.maximum_attempts):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise FitError("Adaptive replicate counts must be positive integers.")
        if self.initial_successes < 2:
            raise FitError("Adaptive analysis requires at least two initial successful replicates.")
        if self.maximum_attempts < self.initial_successes:
            raise FitError("Maximum attempts must be at least the initial successful replicate count.")
        if not math.isfinite(self.tolerance) or not 0 < self.tolerance < 1:
            raise FitError("Adaptive tolerance must be finite and between 0 and 1.")


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
_WORKER_FITTER: Fitter | None = None


def _init_uncertainty_worker(stop: Any, formulas: Mapping[str, Any], *context: Any) -> None:
    global _WORKER_CONTEXT, _WORKER_FITTER
    _WORKER_CONTEXT = (stop, *context)
    _WORKER_FITTER = Fitter(registry_from_worker_formulas(formulas))


def _parallel_map(
    function: Callable[[Any], Any], inputs: Sequence[Any], workers: int,
    context: tuple[Any, ...], cancellation: CancellationToken,
    progress: Callable[[int], None] | None,
    on_result: Callable[[int, Any], None] | None = None,
    *, pool: ProcessPoolExecutor | None = None, stop: Any = None,
    formulas: Mapping[str, Any] | None = None,
) -> list[Any]:
    """Keep only a few spawned-process jobs queued and return results in input order."""
    results: list[Any] = [None] * len(inputs)
    with ExitStack() as stack:
        if pool is None:
            mp_context = multiprocessing.get_context("spawn")
            stop = mp_context.Event()
            pool = stack.enter_context(ProcessPoolExecutor(
                max_workers=min(workers, len(inputs), os.cpu_count() or 1),
                mp_context=mp_context, initializer=_init_uncertainty_worker,
                initargs=(stop, formulas or {}, *context),
            ))
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
                    if on_result:
                        on_result(index, results[index])
                    completed += 1
                    if progress:
                        progress(completed)
        except BaseException:
            stop.set()
            for future in pending:
                future.cancel()
            raise
    return results


def _worker_formulas(
    fitter: Fitter, models: Mapping[str, Model], curve_ids: Sequence[str],
) -> dict[str, Any] | None:
    return worker_formula_specs(fitter.registry, models, curve_ids)


def _parallel_safe(fitter: Fitter, models: Mapping[str, Model], curve_ids: Sequence[str]) -> bool:
    return _worker_formulas(fitter, models, curve_ids) is not None


def _resample_trial(
    seed: int, method: str, baseline: FitResult, plan: FitPlan,
    curves: Mapping[str, Curve], models: Mapping[str, Model],
    lengths: Mapping[str, int], fitter: Fitter, cancellation: CancellationToken,
) -> tuple[list[float] | None, str | None]:
    cancellation.raise_if_cancelled()
    rng = np.random.default_rng(seed)
    trial_models = {key: model.clone() for key, model in models.items()}
    try:
        resolved = resolve_parameter_values({
            path: parameter
            for curve_id, model in trial_models.items()
            for path, parameter in model.parameter_map(curve_id).items()
        })
    except ConstraintError as exc:
        return None, str(exc)
    trial_curves: dict[str, Curve] = {}
    for curve_id in plan.curve_ids:
        curve = curves[curve_id]
        trial = copy.deepcopy(curve)
        output = baseline.curve_outputs[curve_id]
        full_fit = np.asarray(trial_models[curve_id].evaluate(
            curve.x, curve_id=curve_id, values=resolved, registry=fitter.registry))
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
    except (FitError, ConstraintError) as exc:
        return None, str(exc)


def _resample_in_process(seed: int) -> tuple[list[float] | None, str | None]:
    assert _WORKER_CONTEXT is not None and _WORKER_FITTER is not None
    stop, method, baseline, plan, curves, models, lengths = _WORKER_CONTEXT
    return _resample_trial(seed, method, baseline, plan, curves, models, lengths,
                           _WORKER_FITTER, _ProcessCancellationToken(stop))


def _batch_resample_in_process(job: tuple[Any, ...]) -> ResamplingResult:
    assert _WORKER_CONTEXT is not None
    stop = _WORKER_CONTEXT[0]
    method, baseline, plan, curves, models, replicates, option, adaptive = job
    analyzer = UncertaintyAnalyzer(_WORKER_FITTER)
    arguments = dict(replicates=replicates, workers=1, adaptive=adaptive,
                     cancellation=_ProcessCancellationToken(stop))
    if method == "monte_carlo":
        return analyzer.parametric_monte_carlo(baseline, plan, curves, models, **arguments)
    if method == "block_bootstrap":
        return analyzer.block_bootstrap(baseline, plan, curves, models,
                                        block_length=option, **arguments)
    return analyzer.residual_bootstrap(baseline, plan, curves, models, **arguments)


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
    except (FitError, ConstraintError):
        return None


def _profile_in_process(value: float) -> float | None:
    assert _WORKER_CONTEXT is not None and _WORKER_FITTER is not None
    stop, curve, model, parameter_path, baseline, baseline_chi, spectrum_weight, equal = _WORKER_CONTEXT
    return _profile_trial(value, curve, model, parameter_path, baseline, baseline_chi,
                          spectrum_weight, equal, _WORKER_FITTER, _ProcessCancellationToken(stop))


class UncertaintyAnalyzer:
    def __init__(self, fitter: Fitter | None = None) -> None:
        self.fitter = fitter or Fitter()

    def resampling_batch(
        self, method: str, jobs: Sequence[tuple[FitResult, FitPlan,
                                               Mapping[str, Curve], Mapping[str, Model]]],
        *, replicates: int, option: int | None = None, workers: int = 1,
        adaptive: AdaptiveReplicateSettings | None = None,
        cancellation: CancellationToken | None = None,
        progress: Callable[[int], None] | None = None,
        on_result: Callable[[int, ResamplingResult], None] | None = None,
    ) -> list[ResamplingResult]:
        """Process independent spectra in one pool, without spawning per spectrum.

        Each process runs a spectrum's replicates serially. A joint/global fit
        is one job, so its replicates also run on one core.
        """
        if method not in {"monte_carlo", "block_bootstrap", "residual_bootstrap"}:
            raise FitError(f"Unknown resampling method: {method}")
        if not isinstance(workers, int) or workers < 1:
            raise FitError("Worker process count must be a positive integer.")
        if adaptive is not None:
            adaptive.validate()
        token = cancellation or CancellationToken()
        parallel = (workers > 1 and len(jobs) > 1 and all(
            _parallel_safe(self.fitter, models, plan.curve_ids)
            for _, plan, _, models in jobs
        ))
        if parallel:
            formulas = {}
            for _, plan, _, models in jobs:
                formulas.update(_worker_formulas(self.fitter, models, plan.curve_ids) or {})
            payloads = [(method, baseline, plan, curves, models, replicates, option, adaptive)
                        for baseline, plan, curves, models in jobs]
            batch_workers = min(workers, len(jobs), os.cpu_count() or 1)

            def publish(index: int, result: ResamplingResult) -> None:
                result.configuration["batch_workers_used"] = batch_workers
                if on_result:
                    on_result(index, result)

            return _parallel_map(_batch_resample_in_process, payloads, workers,
                                 (), token, progress, publish, formulas=formulas)
        results = []
        for baseline, plan, curves, models in jobs:
            token.raise_if_cancelled()
            arguments = dict(replicates=replicates, workers=1, cancellation=token, adaptive=adaptive)
            if method == "monte_carlo":
                result = self.parametric_monte_carlo(baseline, plan, curves, models, **arguments)
            elif method == "block_bootstrap":
                result = self.block_bootstrap(baseline, plan, curves, models,
                                             block_length=option, **arguments)
            else:
                result = self.residual_bootstrap(baseline, plan, curves, models, **arguments)
            results.append(result)
            result.configuration["batch_workers_used"] = 1
            if on_result:
                on_result(len(results) - 1, result)
            if progress:
                progress(len(results))
        return results

    def parametric_monte_carlo(
        self,
        baseline: FitResult,
        plan: FitPlan,
        curves: Mapping[str, Curve] | Sequence[Curve],
        models: Mapping[str, Model],
        *,
        replicates: int = 200,
        adaptive: AdaptiveReplicateSettings | None = None,
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
            adaptive,
        )

    def residual_bootstrap(
        self,
        baseline: FitResult,
        plan: FitPlan,
        curves: Mapping[str, Curve] | Sequence[Curve],
        models: Mapping[str, Model],
        *,
        replicates: int = 200,
        adaptive: AdaptiveReplicateSettings | None = None,
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
            adaptive,
        )

    def block_bootstrap(
        self,
        baseline: FitResult,
        plan: FitPlan,
        curves: Mapping[str, Curve] | Sequence[Curve],
        models: Mapping[str, Model],
        *,
        replicates: int = 200,
        adaptive: AdaptiveReplicateSettings | None = None,
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
            adaptive,
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
        if baseline.mode == FitMode.GLOBAL and len(baseline.curve_outputs) > 1:
            for path, estimate in baseline.parameters.items():
                if estimate.link and any(
                    reference.split(".", 1)[0] != path.split(".", 1)[0]
                    for reference in SafeExpression.compile(estimate.link).references
                ):
                    raise FitError(
                        "Profile likelihood for linked spectra requires a joint profile. "
                        "Use Monte Carlo or bootstrap for this global fit."
                    )
        if parameter_path not in model.parameter_map(curve.id):
            raise FitError(f"Unknown profile parameter: {parameter_path}")
        parameter = model.parameter_map(curve.id)[parameter_path]
        if parameter.link and parameter.link_relation == "equal":
            raise FitError("Profile likelihood requires a free parameter, not an equality-linked parameter.")
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
                formulas=_worker_formulas(self.fitter, {curve.id: model}, [curve.id]),
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
        adaptive: AdaptiveReplicateSettings | None = None,
    ) -> ResamplingResult:
        if adaptive is not None:
            adaptive.validate()
        elif replicates <= 0:
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
        if adaptive is not None:
            if not paths:
                raise FitError("Adaptive uncertainty analysis requires at least one free parameter.")
            return self._adaptive_resample(
                method, baseline, trial_plan, curves, base_models, adaptive,
                selected_seed, workers, token, progress, extra_configuration,
            )
        seeds = rng.integers(0, np.iinfo(np.int64).max, size=replicates).tolist()
        parallel = workers > 1 and replicates > 1 and _parallel_safe(self.fitter, base_models, plan.curve_ids)

        def report(count: int) -> None:
            if progress:
                progress(count / replicates, f"{method}: {count}/{replicates}")

        if parallel:
            outcomes = _parallel_map(
                _resample_in_process, seeds, workers,
                (method, baseline, trial_plan, curves, base_models, lengths), token, report,
                formulas=_worker_formulas(self.fitter, base_models, plan.curve_ids),
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

    def _adaptive_resample(
        self, method: str, baseline: FitResult, plan: FitPlan,
        curves: Mapping[str, Curve], models: Mapping[str, Model],
        adaptive: AdaptiveReplicateSettings, seed: int, workers: int,
        token: CancellationToken, progress: Callable[[float | None, str], None] | None,
        extra_configuration: dict[str, Any],
    ) -> ResamplingResult:
        paths = list(baseline.free_parameter_paths)
        seeds = np.random.default_rng(seed).integers(
            0, np.iinfo(np.int64).max, size=adaptive.maximum_attempts).tolist()
        lengths = extra_configuration.get("block_lengths", {})
        context = (method, baseline, plan, curves, models, lengths)
        parallel = (workers > 1 and adaptive.maximum_attempts > 1
                    and _parallel_safe(self.fitter, models, plan.curve_ids))
        collected: list[list[float]] = []
        failures: list[str] = []
        attempts = stable_checks = checks_completed = 0
        previous: np.ndarray | None = None
        history: list[dict[str, Any]] = []
        target = adaptive.initial_successes
        converged = False

        def report(_count: int = 0) -> None:
            if progress:
                progress(attempts / adaptive.maximum_attempts,
                         f"{method}: {len(collected)} successful, {attempts}/"
                         f"{adaptive.maximum_attempts} attempts; stable checks "
                         f"{stable_checks}/{adaptive.consecutive_checks}")

        with ExitStack() as stack:
            pool = stop = None
            if parallel:
                mp_context = multiprocessing.get_context("spawn")
                stop = mp_context.Event()
                pool = stack.enter_context(ProcessPoolExecutor(
                    max_workers=min(workers, adaptive.maximum_attempts, os.cpu_count() or 1),
                    mp_context=mp_context, initializer=_init_uncertainty_worker,
                    initargs=(stop, _worker_formulas(self.fitter, models, plan.curve_ids) or {}, *context),
                ))
            while attempts < adaptive.maximum_attempts and not converged:
                token.raise_if_cancelled()
                # Limit each chunk to the successes still needed. Failed fits are
                # replaced before checking, without overshooting a checkpoint.
                count = min(target - len(collected), adaptive.maximum_attempts - attempts)
                trial_seeds = seeds[attempts:attempts + count]

                def collect(_index: int, outcome: Any) -> None:
                    nonlocal attempts
                    sample, message = outcome
                    attempts += 1
                    if (sample is not None and len(sample) == len(paths)
                            and np.all(np.isfinite(sample))):
                        collected.append(sample)
                    else:
                        failures.append(message or "Replica returned no finite parameter sample.")
                    report()

                if parallel:
                    # Consume in seed order, independently of worker completion
                    # order, so checkpoints and saved samples are reproducible.
                    batch_size = len(trial_seeds)
                    outcomes = _parallel_map(
                        _resample_in_process, trial_seeds, workers, context, token,
                        lambda count, batch_size=batch_size: progress(
                            (attempts + count) / adaptive.maximum_attempts,
                            f"{method}: fitting batch, {count}/{batch_size} attempts complete",
                        ) if progress else None,
                        pool=pool, stop=stop,
                    )
                    for index, outcome in enumerate(outcomes):
                        collect(index, outcome)
                else:
                    for index, trial_seed in enumerate(trial_seeds):
                        token.raise_if_cancelled()
                        collect(index, _resample_trial(
                            trial_seed, method, baseline, plan, curves, models,
                            lengths, self.fitter, token))
                token.raise_if_cancelled()
                if len(collected) == target:
                    current = _percentile_endpoints(collected, plan.settings.confidence_level)
                    change = None
                    if previous is not None:
                        checks_completed += 1
                        change = _endpoint_change(previous, current)
                        stable_checks = stable_checks + 1 if change < adaptive.tolerance else 0
                        converged = stable_checks >= adaptive.consecutive_checks
                    history.append({
                        "successful": len(collected), "attempts": attempts,
                        "maximum_endpoint_change_fraction": (
                            change if change is not None and math.isfinite(change) else None),
                        "stable_checks": stable_checks,
                    })
                    previous = current
                    target += adaptive.batch_successes
                    report()
        samples = np.asarray(collected, dtype=float).reshape(-1, len(paths))
        endpoints = _percentile_endpoints(samples, plan.settings.confidence_level) if len(samples) else []
        intervals = {path: tuple(map(float, endpoints[index]))
                     for index, path in enumerate(paths) if len(samples)}
        configuration = {
            "fit_settings": asdict(plan.settings),
            "workers_used": min(workers, adaptive.maximum_attempts, os.cpu_count() or 1) if parallel else 1,
            **extra_configuration,
            "adaptive": {
                **asdict(adaptive), "converged": converged,
                "stop_reason": "stable_intervals" if converged else "maximum_attempts",
                "attempted": attempts, "checks_completed": checks_completed,
                "stable_checks": stable_checks, "history": history,
            },
        }
        if progress:
            progress(1.0, f"{method}: {'stable intervals' if converged else 'maximum attempts reached'}; "
                     f"{len(samples)} successful, {len(failures)} failed")
        return ResamplingResult(
            method, adaptive.maximum_attempts, len(samples), len(failures), seed,
            paths, samples, intervals, plan.settings.confidence_level, configuration,
            failures[:100],
        )


def _percentile_endpoints(samples: Any, confidence_level: float) -> np.ndarray:
    alpha = (1 - confidence_level) / 2
    return np.quantile(np.asarray(samples), [alpha, 1 - alpha], axis=0).T


def _endpoint_change(previous: np.ndarray, current: np.ndarray) -> float:
    """Worst endpoint movement, normalized by each current interval's width."""
    movement = np.max(np.abs(current - previous), axis=1)
    width = current[:, 1] - current[:, 0]
    fractions = np.full_like(width, np.inf)
    np.divide(movement, width, out=fractions, where=width > 0)
    fractions[(width == 0) & (movement == 0)] = 0
    return float(np.max(fractions)) if np.all(np.isfinite(fractions)) else math.inf


def _curve_map(curves: Mapping[str, Curve] | Sequence[Curve]) -> Mapping[str, Curve]:
    return curves if isinstance(curves, Mapping) else {curve.id: curve for curve in curves}


def _chi2_one(confidence_level: float) -> float:
    from scipy.stats import chi2

    return float(chi2.ppf(confidence_level, 1))
