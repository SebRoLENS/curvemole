from __future__ import annotations

import os

import numpy as np
import pytest

from curvemole import Component, Fitter, Model
from curvemole.core.fitting import FitMode, FitPlan
from curvemole.core.uncertainty import UncertaintyAnalyzer


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
