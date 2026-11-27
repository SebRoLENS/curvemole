import numpy as np
import pytest

from curvemole.core.data import Curve
from curvemole.core.diagnostics import contiguous_residual_segments
from curvemole.core.errors import FitError
from curvemole.core.fitting import FitPlan, Fitter
from curvemole.core.models import Component, Model
from curvemole.core.uncertainty import UncertaintyAnalyzer


def _segment_lengths(x, rows=None):
    rows = np.arange(len(x)) if rows is None else rows
    return [segment.stop - segment.start for segment in contiguous_residual_segments(rows, x)]


@pytest.mark.parametrize("x", [
    500 + 0.1 * np.arange(300) + 2e-5 * np.arange(300) ** 2,  # smooth CCD calibration
    np.round(np.linspace(100, 101.4, 1000), 3),  # values rounded in a text file
    np.linspace(4000, 400, 500),  # descending wavenumbers
])
def test_calibrated_rounded_and_descending_axes_stay_one_segment(x):
    assert _segment_lengths(x) == [len(x)]


def test_real_gaps_reversals_and_row_gaps_still_split():
    assert _segment_lengths(np.r_[np.linspace(0, 1, 50), np.linspace(2, 3, 50)]) == [50, 50]
    assert _segment_lengths(np.r_[np.linspace(0, 1, 70), np.linspace(0.99, 0.8, 20)])[0] == 70
    rows = np.r_[np.arange(40), np.arange(60, 100)]
    assert _segment_lengths(np.linspace(0, 1, 80), rows) == [40, 40]


def _fit(x, masked=()):
    rng = np.random.default_rng(5)
    y = 50 * np.exp(-0.5 * ((x - x.mean()) / 3) ** 2) / (3 * np.sqrt(2 * np.pi)) + rng.normal(0, 0.3, x.size)
    curve = Curve("data", x, y)
    for value in masked:
        curve.mask_point(value)
    model = Model()
    model.add(Component.create("gaussian", initial=dict(area=45, center=x.mean() + 0.3, sigma=2.5)))
    plan = FitPlan([curve.id])
    result = Fitter().fit(plan, {curve.id: curve}, {curve.id: model})
    return result, plan, {curve.id: curve}, {curve.id: model}


def test_block_bootstrap_spread_on_calibrated_axis_matches_covariance():
    index = np.arange(300.)
    result, plan, curves, models = _fit(500 + 0.1 * index + 2e-5 * index ** 2)
    analysis = UncertaintyAnalyzer().block_bootstrap(result, plan, curves, models, replicates=100, seed=1)
    spread = analysis.samples.std(axis=0, ddof=1)
    for path, value in zip(analysis.parameter_paths, spread, strict=True):
        covariance = result.parameters[path].standard_error
        assert 0.5 * covariance < value < 2 * covariance, path


def test_block_bootstrap_rejects_fragmented_axes():
    x = 500 + 0.1 * np.arange(300)
    result, plan, curves, models = _fit(x, masked=x[1::2])  # every fitted row is isolated
    with pytest.raises(FitError, match="fragmented"):
        UncertaintyAnalyzer().block_bootstrap(result, plan, curves, models, replicates=10, seed=1)
