from __future__ import annotations

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
