from __future__ import annotations

import os

import numpy as np
import pytest

from curvemole import Component, Fitter, Model
from curvemole.core.fitting import FitMode, FitPlan
from curvemole.core.uncertainty import UncertaintyAnalyzer


def test_batch_resampling_uses_one_pool_and_preserves_results(gaussian_curve, monkeypatch) -> None:
    from curvemole import Curve
    from curvemole.core import uncertainty

    analyzer = UncertaintyAnalyzer()
    x = gaussian_curve.x.copy()
    curves = [gaussian_curve, Curve("second", x, gaussian_curve.y.copy())]
    jobs = []
    for curve in curves:
        model = Model(components=[Component.create(
            "gaussian", initial={"area": 3, "center": .7, "sigma": .8})])
        plan = FitPlan([curve.id])
        baseline = analyzer.fitter.fit(plan, [curve], {curve.id: model})
        jobs.append((baseline, plan, {curve.id: curve}, {curve.id: model}))

    serial = analyzer.resampling_batch("residual_bootstrap", jobs, replicates=5, workers=1)
    original = uncertainty._parallel_map
    calls = []

    def count_pools(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(uncertainty, "_parallel_map", count_pools)
    parallel = analyzer.resampling_batch("residual_bootstrap", jobs, replicates=5, workers=2)
    assert len(calls) == 1
    for expected, actual in zip(serial, parallel, strict=True):
        assert actual.completed == expected.completed == 5
        np.testing.assert_array_equal(actual.samples, expected.samples)


def test_parametric_monte_carlo_is_reproducible(gaussian_curve) -> None:
    model = Model(components=[Component.create("gaussian", initial={"area": 3, "center": 0.7, "sigma": 0.8})])
    models = {gaussian_curve.id: model}
    plan = FitPlan([gaussian_curve.id], FitMode.GLOBAL)
    fitter = Fitter()
    baseline = fitter.fit(plan, [gaussian_curve], models)
    analyzer = UncertaintyAnalyzer(fitter)
    first = analyzer.parametric_monte_carlo(
        baseline, plan, [gaussian_curve], models, replicates=10, seed=123
    )
    second = analyzer.parametric_monte_carlo(
        baseline, plan, [gaussian_curve], models, replicates=10, seed=123
    )
    assert first.completed == 10
    assert first.samples.tolist() == second.samples.tolist()
    assert first.intervals


@pytest.mark.parametrize("method", ["parametric_monte_carlo", "residual_bootstrap", "block_bootstrap"])
def test_uncertainty_replicates_match_across_process_counts(gaussian_curve, method: str) -> None:
    model = Model(components=[Component.create("gaussian", initial={"area": 3, "center": 0.7, "sigma": 0.8})])
    models = {gaussian_curve.id: model}
    plan = FitPlan([gaussian_curve.id], FitMode.GLOBAL)
    analyzer = UncertaintyAnalyzer()
    baseline = analyzer.fitter.fit(plan, [gaussian_curve], models)
    run = getattr(analyzer, method)
    serial = run(baseline, plan, [gaussian_curve], models, replicates=5, seed=42, workers=1)
    parallel = run(baseline, plan, [gaussian_curve], models, replicates=5, seed=42, workers=2)
    assert parallel.configuration["workers_used"] == min(2, os.cpu_count() or 1)
    assert parallel.completed == serial.completed
    np.testing.assert_allclose(parallel.samples, serial.samples, rtol=0, atol=0)


def test_profile_grid_matches_across_process_counts(gaussian_curve) -> None:
    model = Model(components=[Component.create("gaussian", initial={"area": 3, "center": 0.7, "sigma": 0.8})])
    plan = FitPlan([gaussian_curve.id], FitMode.GLOBAL)
    analyzer = UncertaintyAnalyzer()
    baseline = analyzer.fitter.fit(plan, [gaussian_curve], {gaussian_curve.id: model})
    center = next(path for path in baseline.free_parameter_paths if path.endswith(".center"))
    serial = analyzer.profile_parameter(baseline, gaussian_curve, model, center, points=5, workers=1)
    parallel = analyzer.profile_parameter(baseline, gaussian_curve, model, center, points=5, workers=2)
    np.testing.assert_allclose(parallel.delta_chi_square, serial.delta_chi_square, rtol=0, atol=0)
