from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from curvemole import Component, Fitter, Model
from curvemole.core import uncertainty
from curvemole.core.errors import FitError
from curvemole.core.fitting import CancellationToken, FitCancelled, FitPlan
from curvemole.core.uncertainty import AdaptiveReplicateSettings, UncertaintyAnalyzer


def _analysis(gaussian_curve):
    model = Model(components=[Component.create(
        "gaussian", initial={"area": 3, "center": .7, "sigma": .8})])
    plan = FitPlan([gaussian_curve.id])
    models = {gaussian_curve.id: model}
    analyzer = UncertaintyAnalyzer()
    baseline = analyzer.fitter.fit(plan, [gaussian_curve], models)
    return analyzer, baseline, plan, models


def test_adaptive_defaults_require_three_checks_after_500_successes(gaussian_curve, monkeypatch):
    analyzer, baseline, plan, models = _analysis(gaussian_curve)
    monkeypatch.setattr(uncertainty, "_resample_trial", lambda *args: ([1., 2., 3.], None))
    result = analyzer.residual_bootstrap(baseline, plan, [gaussian_curve], models,
                                         adaptive=AdaptiveReplicateSettings())
    adaptive = result.configuration["adaptive"]
    assert result.completed == 1100
    assert adaptive["attempted"] == 1100
    assert adaptive["converged"]
    assert adaptive["stop_reason"] == "stable_intervals"
    assert [check["successful"] for check in adaptive["history"]] == [500, 700, 900, 1100]
    assert adaptive["checks_completed"] == adaptive["stable_checks"] == 3
    assert result.to_dict(include_samples=False)["configuration"]["adaptive"] == adaptive


def test_failed_and_nonfinite_fits_do_not_count_toward_checkpoints(gaussian_curve, monkeypatch):
    analyzer, baseline, plan, models = _analysis(gaussian_curve)
    outcomes = iter([(None, "failed"), ([np.nan, 2., 3.], None), ([1., 2., 3.], None)] * 20)
    monkeypatch.setattr(uncertainty, "_resample_trial", lambda *args: next(outcomes))
    settings = AdaptiveReplicateSettings(5, 2, .05, 2, 40)
    result = analyzer.residual_bootstrap(baseline, plan, [gaussian_curve], models, adaptive=settings)
    assert result.completed == 9
    assert result.failed == 18
    assert result.configuration["adaptive"]["attempted"] == 27
    assert [c["successful"] for c in result.configuration["adaptive"]["history"]] == [5, 7, 9]


def test_unstable_check_resets_consecutive_counter(gaussian_curve, monkeypatch):
    analyzer, baseline, plan, models = _analysis(gaussian_curve)
    monkeypatch.setattr(uncertainty, "_resample_trial", lambda *args: ([1., 2., 3.], None))
    changes = iter([.01, .10, .01, .01, .01])
    monkeypatch.setattr(uncertainty, "_endpoint_change", lambda *args: next(changes))
    result = analyzer.residual_bootstrap(baseline, plan, [gaussian_curve], models,
                                         adaptive=AdaptiveReplicateSettings(5, 2, .05, 3, 20))
    adaptive = result.configuration["adaptive"]
    assert result.completed == 15
    assert [c["stable_checks"] for c in adaptive["history"]] == [0, 1, 0, 1, 2, 3]
    assert adaptive["converged"]


@pytest.mark.parametrize("failed", [False, True])
def test_maximum_attempts_is_a_hard_cap_even_without_stability(gaussian_curve, monkeypatch, failed):
    analyzer, baseline, plan, models = _analysis(gaussian_curve)
    monkeypatch.setattr(uncertainty, "_resample_trial",
                        lambda *args: (None, "failed") if failed else ([1., 2., 3.], None))
    monkeypatch.setattr(uncertainty, "_endpoint_change", lambda *args: .5)
    result = analyzer.residual_bootstrap(baseline, plan, [gaussian_curve], models,
                                         adaptive=AdaptiveReplicateSettings(5, 3, .05, 3, 13))
    adaptive = result.configuration["adaptive"]
    assert result.completed + result.failed == adaptive["attempted"] == 13
    assert not adaptive["converged"]
    assert adaptive["stop_reason"] == "maximum_attempts"
    assert result.completed == (0 if failed else 13)
    if failed:
        assert not result.intervals
    else:
        assert [c["successful"] for c in adaptive["history"]] == [5, 8, 11]


def test_endpoint_change_checks_both_ends_of_every_interval():
    previous = np.array([[0., 10.], [0., 2.]])
    # Small absolute movement of the second parameter can exceed its own tolerance.
    current = np.array([[.1, 10.1], [.2, 2.]])
    assert uncertainty._endpoint_change(previous, current) == pytest.approx(.2 / 1.8)
    current = np.array([[0., 10.], [0., 2.2]])
    assert uncertainty._endpoint_change(previous, current) == pytest.approx(.2 / 2.2)
    assert uncertainty._endpoint_change(previous, previous) == 0
    assert uncertainty._endpoint_change(np.array([[1., 1.]]), np.array([[1., 1.]])) == 0
    assert np.isinf(uncertainty._endpoint_change(np.array([[0., 1.]]), np.array([[1., 1.]])))


@pytest.mark.parametrize("changes", [
    {"initial_successes": 1}, {"initial_successes": True}, {"batch_successes": 0},
    {"consecutive_checks": 0}, {"maximum_attempts": 499}, {"tolerance": 0.},
    {"tolerance": 1.}, {"tolerance": np.nan},
])
def test_adaptive_settings_reject_invalid_values(changes):
    with pytest.raises(FitError):
        replace(AdaptiveReplicateSettings(), **changes).validate()


def test_adaptive_analysis_can_be_cancelled(gaussian_curve, monkeypatch):
    analyzer, baseline, plan, models = _analysis(gaussian_curve)
    token = CancellationToken()
    monkeypatch.setattr(uncertainty, "_resample_trial", lambda *args: ([1., 2., 3.], None))
    with pytest.raises(FitCancelled):
        analyzer.residual_bootstrap(baseline, plan, [gaussian_curve], models,
                                    adaptive=AdaptiveReplicateSettings(5, 2, .05, 3, 20),
                                    cancellation=token, progress=lambda *args: token.cancel())


@pytest.mark.parametrize("method", ["parametric_monte_carlo", "residual_bootstrap", "block_bootstrap"])
def test_adaptive_replicates_are_reproducible_across_worker_counts(gaussian_curve, method):
    analyzer, baseline, plan, models = _analysis(gaussian_curve)
    settings = AdaptiveReplicateSettings(3, 2, .99, 1, 9)
    run = getattr(analyzer, method)
    serial = run(baseline, plan, [gaussian_curve], models, adaptive=settings, seed=42)
    parallel = run(baseline, plan, [gaussian_curve], models, adaptive=settings, seed=42, workers=2)
    np.testing.assert_array_equal(parallel.samples, serial.samples)
    assert parallel.intervals == serial.intervals
    assert parallel.configuration["adaptive"] == serial.configuration["adaptive"]
    assert parallel.configuration["workers_used"] == min(2, uncertainty.os.cpu_count() or 1)
    assert len(parallel.samples) <= 9


@pytest.mark.parametrize("adaptive_mode", [False, True])
def test_custom_formula_batch_runs_in_worker_processes(gaussian_curve, monkeypatch, adaptive_mode):
    from curvemole import Curve
    from curvemole.core.functions import builtin_definitions, formula_definition
    from curvemole.core.registry import FunctionRegistry

    registry = FunctionRegistry()
    registry.extend(builtin_definitions())
    definition = formula_definition(
        "custom_peak", "Custom peak", "area * exp(-0.5 * ((x - center) / sigma) ** 2)",
        defaults={"area": 1.5, "center": .7, "sigma": .8}, bounds={"sigma": (.01, 10.)},
    )
    # Presentation metadata must not leak into formula builder arguments in workers.
    definition.custom_metadata["peak_roles"] = {"center": "center", "width": "sigma"}
    registry.register(definition)
    analyzer = UncertaintyAnalyzer(Fitter(registry))
    jobs = []
    for index in range(3):
        curve = Curve(f"spectrum {index}", gaussian_curve.x, gaussian_curve.y + .005 * index)
        model = Model(components=[Component.create("custom_peak", registry=registry)])
        plan = FitPlan([curve.id])
        models = {curve.id: model}
        baseline = analyzer.fitter.fit(plan, [curve], models)
        jobs.append((baseline, plan, {curve.id: curve}, models))
    settings = AdaptiveReplicateSettings(3, 2, .99, 1, 7) if adaptive_mode else None
    serial = analyzer.resampling_batch("block_bootstrap", jobs, replicates=5, adaptive=settings)
    original = uncertainty._parallel_map
    pools = []

    def capture_pool(*args, **kwargs):
        pools.append((args[2], kwargs.get("formulas")))
        return original(*args, **kwargs)

    monkeypatch.setattr(uncertainty, "_parallel_map", capture_pool)
    published = []
    parallel = analyzer.resampling_batch(
        "block_bootstrap", jobs, replicates=5, workers=3, adaptive=settings,
        on_result=lambda index, result: published.append((index, result.configuration["batch_workers_used"])),
    )
    assert len(pools) == 1 and pools[0][0] == 3
    assert "custom_peak" in pools[0][1]
    assert len(published) == 3
    for expected, actual in zip(serial, parallel, strict=True):
        assert actual.failed == expected.failed == 0
        np.testing.assert_array_equal(actual.samples, expected.samples)
        assert actual.configuration["batch_workers_used"] == min(3, uncertainty.os.cpu_count() or 1)
        if adaptive_mode:
            assert actual.configuration["adaptive"] == expected.configuration["adaptive"]


def test_executable_callback_does_not_get_reconstructed_as_a_formula(gaussian_curve):
    from curvemole.core.functions import FunctionDefinition, ParameterSpec
    from curvemole.core.registry import FunctionRegistry

    registry = FunctionRegistry()
    registry.register(FunctionDefinition(
        "callback", "Callback", "generic", lambda x, p, m: np.full_like(x, p["a"]),
        parameter_specs=(ParameterSpec("a", 1.),), custom_metadata={"formula": "a + 0*x"},
    ))
    model = Model(components=[Component.create("callback", registry=registry)])
    assert not uncertainty._parallel_safe(Fitter(registry), {gaussian_curve.id: model}, [gaussian_curve.id])
