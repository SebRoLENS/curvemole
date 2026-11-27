import numpy as np
import pytest

from curvemole.core.data import Curve, Transformation


def _normalised(x, y, **errors):
    curve = Curve("c", x, y, **errors)
    curve.apply_transformation(Transformation("normalize_area", {}))
    return curve


def _area(curve):
    order = np.argsort(curve.x)
    return np.trapezoid(curve.y[order], curve.x[order])


@pytest.mark.parametrize("order", ["ascending", "descending", "shuffled"])
def test_area_normalisation_is_independent_of_row_order(order):
    x = np.linspace(400, 4000, 301)
    y = np.exp(-0.5 * ((x - 1600) / 40) ** 2)
    rows = {"ascending": np.arange(301), "descending": np.arange(301)[::-1],
            "shuffled": np.random.default_rng(0).permutation(301)}[order]
    curve = _normalised(x[rows], y[rows], sigma_y=np.full(301, 0.01))
    assert curve.y.min() >= 0
    assert _area(curve) == pytest.approx(1.0)
    reference = _normalised(x, y, sigma_y=np.full(301, 0.01))
    np.testing.assert_allclose(curve.current_sigma_y, reference.current_sigma_y[rows])


def test_one_missing_error_does_not_invalidate_the_other_rows():
    x = np.linspace(0, 10, 11)
    sigma = np.full(11, 0.5)
    sigma[5] = np.nan
    curve = _normalised(x, 1 + x, sigma_y=sigma)
    assert np.isnan(curve.current_sigma_y[5])
    assert np.all(np.isfinite(np.delete(curve.current_sigma_y, 5)))
    weights = np.full(11, 4.0)
    weights[5] = 0.0
    curve = _normalised(x, 1 + x, weights=weights)
    assert len(curve.fit_arrays()[0]) == 10
