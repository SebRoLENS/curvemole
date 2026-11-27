import numpy as np
import pytest

from curvemole.core.data import Curve
from curvemole.core.fitting import FitPlan, FitSettings, Fitter
from curvemole.core.models import Component, Model
from curvemole.core.uncertainty import UncertaintyAnalyzer


def _fit(absolute_sigma):
    rng = np.random.default_rng(1)
    x = np.linspace(-5, 5, 200)
    y = 10 * np.exp(-0.5 * (x / 0.8) ** 2) / (0.8 * np.sqrt(2 * np.pi)) + rng.normal(0, 0.3, x.size)
    curve = Curve("c", x, y, sigma_y=np.full_like(x, 0.1))  # three times smaller than the real scatter
    model = Model()
    model.add(Component.create("gaussian", initial=dict(area=9, center=0.1, sigma=1)))
    plan = FitPlan([curve.id], settings=FitSettings(absolute_sigma=absolute_sigma))
    result = Fitter().fit(plan, {curve.id: curve}, {curve.id: model})
    return result, plan, {curve.id: curve}, {curve.id: model}


def test_monte_carlo_with_relative_errors_uses_residual_scale():
    result, plan, curves, models = _fit(absolute_sigma=False)
    analysis = UncertaintyAnalyzer().parametric_monte_carlo(result, plan, curves, models, replicates=200, seed=3)
    spread = analysis.samples.std(axis=0, ddof=1)
    for path, value in zip(analysis.parameter_paths, spread, strict=True):
        assert value == pytest.approx(result.parameters[path].standard_error, rel=0.25), path
    (scale,) = analysis.configuration["parametric_noise_scale"].values()
    assert scale == pytest.approx(np.sqrt(7.81), rel=0.05)


def test_monte_carlo_with_absolute_errors_keeps_declared_amplitude():
    result, plan, curves, models = _fit(absolute_sigma=True)
    analysis = UncertaintyAnalyzer().parametric_monte_carlo(result, plan, curves, models, replicates=200, seed=3)
    assert analysis.configuration["parametric_noise_scale"] is None
    spread = analysis.samples.std(axis=0, ddof=1)
    for path, value in zip(analysis.parameter_paths, spread, strict=True):
        assert value == pytest.approx(result.parameters[path].standard_error, rel=0.25), path
