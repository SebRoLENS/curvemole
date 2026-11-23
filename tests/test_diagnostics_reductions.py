"""Lazy normal quantiles retain the established diagnostic definitions."""
import numpy as np
import pytest
from scipy.stats import norm

from curvemole.core.diagnostics import estimate_block_length, residual_diagnostics


@pytest.mark.parametrize("size", [501, 100_000])
def test_correlations_and_quantiles_match_reference(size):
    residual = np.random.default_rng(42).normal(loc=0.15, scale=2, size=size)
    residual[2] = np.nan
    diagnostic = residual_diagnostics(residual, max_lag=100)
    finite = residual[np.isfinite(residual)]
    centred = finite - finite.mean()
    segments = (centred[:2], centred[2:])
    reference = np.array([sum(np.dot(part[:-lag], part[lag:]) for part in segments if len(part) > lag)
                          / np.dot(centred, centred) for lag in range(1, 101)])
    np.testing.assert_allclose(diagnostic.autocorrelation[1:], reference, atol=1e-14, rtol=1e-12)
    np.testing.assert_allclose(diagnostic.qq_theoretical,
                               norm.ppf((np.arange(len(finite)) + .5) / len(finite)),
                               atol=1e-14, rtol=1e-14)
    assert diagnostic.durbin_watson == pytest.approx(
        sum(np.dot(np.diff(part), np.diff(part)) for part in (finite[:2], finite[2:])) / np.dot(finite, finite))


def test_constant_and_insufficient_residuals_preserve_undefined_statistics():
    assert np.isnan(residual_diagnostics(np.ones(40_000)).autocorrelation[1:]).all()
    assert residual_diagnostics(np.zeros(40_000)).durbin_watson is None
    assert residual_diagnostics(np.array([np.nan, 1., 2.])).autocorrelation.size == 0


@pytest.mark.parametrize("factor", [1e-200, 1e200])
def test_dimensionless_statistics_are_invariant_under_unit_changes(factor):
    residual = np.array([-2., 1., 3., -1., 2., 0.])
    reference = residual_diagnostics(residual, max_lag=3)
    actual = residual_diagnostics(residual * factor, max_lag=3)
    np.testing.assert_allclose(actual.standardised, reference.standardised)
    np.testing.assert_allclose(actual.autocorrelation, reference.autocorrelation)
    np.testing.assert_allclose(actual.histogram_edges / factor, reference.histogram_edges, atol=1e-14)
    assert actual.durbin_watson == pytest.approx(reference.durbin_watson)


def test_zero_lag_and_invalid_lag():
    np.testing.assert_array_equal(residual_diagnostics(np.arange(10), max_lag=0).autocorrelation, [1.])
    with pytest.raises(ValueError, match="lag"):
        residual_diagnostics(np.arange(10), max_lag=-1)

@pytest.mark.parametrize("value", [1e200, -1e200, np.finfo(float).max])
def test_large_constant_residuals_have_defined_histogram(value):
    diagnostic = residual_diagnostics(np.full(15, value))
    assert diagnostic.histogram_counts.sum() == 15
    assert np.isfinite(diagnostic.histogram_edges).all()
    np.testing.assert_array_equal(diagnostic.standardised, np.zeros(15))
    assert np.isnan(diagnostic.autocorrelation[1:]).all()
    assert diagnostic.durbin_watson == 0


@pytest.mark.parametrize("values", [np.arange(250.), np.ones(600), np.array([np.nan, 1.]),
                                    np.random.default_rng(58).normal(size=128)])
def test_automatic_block_length_matches_full_diagnostics(values):
    acf = residual_diagnostics(values).autocorrelation
    crossings = np.flatnonzero(np.abs(acf[1:]) < np.exp(-1))
    expected = crossings[0] + 1 if crossings.size else max(1, min(len(values) // 10, len(acf) - 1))
    assert estimate_block_length(values) == expected
