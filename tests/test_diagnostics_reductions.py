"""Lazy normal quantiles retain the established diagnostic definitions."""
import numpy as np
import pytest
from scipy.stats import norm

from curvemole.core.diagnostics import residual_diagnostics


@pytest.mark.parametrize("size", [501, 100_000])
def test_correlations_and_quantiles_match_reference(size):
    residual = np.random.default_rng(42).normal(loc=0.15, scale=2, size=size)
    residual[2] = np.nan
    diagnostic = residual_diagnostics(residual, max_lag=100)
    finite = residual[np.isfinite(residual)]
    centred = finite - finite.mean()
    reference = np.array([np.dot(centred[:-lag], centred[lag:]) / np.dot(centred, centred)
                          for lag in range(1, 101)])
    np.testing.assert_allclose(diagnostic.autocorrelation[1:], reference, atol=1e-14, rtol=1e-12)
    np.testing.assert_allclose(diagnostic.qq_theoretical,
                               norm.ppf((np.arange(len(finite)) + .5) / len(finite)),
                               atol=1e-14, rtol=1e-14)
    assert diagnostic.durbin_watson == pytest.approx(
        np.dot(np.diff(finite), np.diff(finite)) / np.dot(finite, finite))


def test_constant_and_insufficient_residuals_preserve_undefined_statistics():
    assert np.isnan(residual_diagnostics(np.ones(40_000)).autocorrelation[1:]).all()
    assert residual_diagnostics(np.zeros(40_000)).durbin_watson is None
    assert residual_diagnostics(np.array([np.nan, 1., 2.])).autocorrelation.size == 0
