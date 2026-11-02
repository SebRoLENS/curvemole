"""Scientific equivalence and sparse/dense parity for the second audit fixes."""
from __future__ import annotations

import copy

import numpy as np
import pytest
from scipy import sparse
from scipy.optimize._numdiff import approx_derivative

from curvemole import Component, Curve, Fitter, Model
from curvemole.core.errors import DataValidationError, FitError
from curvemole.core.fitting import (
    CancellationToken,
    FitMode,
    FitPlan,
    FitSettings,
    _covariance,
    _Problem,
)
from curvemole.core.initialization import find_peak_suggestions
from curvemole.core.registry import default_registry
from curvemole.core.uncertainty import UncertaintyAnalyzer


@pytest.mark.parametrize('method', ['residual_bootstrap', 'block_bootstrap'])
def test_bootstrap_samples_match_for_equivalent_sigma_and_inverse_variance(method):
    sigma = np.array([1, 1, 2, 2, 4, 4, 8, 8.])
    y = np.array([0, 1, -2, 4, -8, 16, -30, 70.])
    results = []
    for errors in [dict(sigma_y=sigma), dict(weights=1 / sigma**2)]:
        c = Curve('weighted', np.arange(len(y)), y, **errors)
        m = Model(components=[Component.create('constant')])
        settings = FitSettings(absolute_sigma=False)
        baseline = Fitter().fit_single(c, m, settings)
        kwargs = dict(replicates=32, seed=1729)
        # Auto block-length selection must use the same standardized residuals.
        result = getattr(UncertaintyAnalyzer(), method)(
            baseline, FitPlan([c.id], settings=settings), [c], {c.id: m}, **kwargs)
        assert result.completed == 32 and result.failed == 0
        assert result.configuration['residual_standardization']
        results.append(result)
    assert results[0].samples == pytest.approx(results[1].samples)
    if method == 'block_bootstrap':
        assert list(results[0].configuration['block_lengths'].values()) == list(
            results[1].configuration['block_lengths'].values())


def test_bootstrap_still_requires_valid_noise_when_the_fit_ignores_errors():
    c = Curve('unweighted', np.arange(5.), [0, 1, 1, 2, 3], sigma_y=[0, 0, 0, 0, 0])
    m = Model(components=[Component.create('constant')])
    settings = FitSettings(use_data_errors=False)
    baseline = Fitter().fit_single(c, m, settings)
    with pytest.raises(FitError, match='finite positive'):
        UncertaintyAnalyzer().residual_bootstrap(
            baseline, FitPlan([c.id], settings=settings), [c], {c.id: m}, replicates=4)


@pytest.mark.parametrize('ordering', ['ascending', 'descending', 'shuffled'])
def test_peak_width_uses_local_coordinates_on_irregular_grid(ordering):
    x = np.r_[np.arange(-301., -1.), np.linspace(-1, 1, 201), np.arange(2., 302.)]
    y = np.exp(-.5 * (x / .1)**2)
    order = np.arange(len(x))
    if ordering == 'descending':
        order = order[::-1]
    elif ordering == 'shuffled':
        order = np.random.default_rng(42).permutation(order)
    [peak] = find_peak_suggestions(Curve('irregular', x[order], y[order]), prominence=.1)
    assert peak.x == pytest.approx(0)
    assert peak.fwhm == pytest.approx(2 * np.sqrt(2 * np.log(2)) * .1, rel=.001)


def test_peak_search_reports_duplicate_coordinates_explicitly():
    with pytest.raises(DataValidationError, match='unique X'):
        find_peak_suggestions(Curve('duplicates', [0, 1, 1, 2], [0, 1, 2, 0]))


def global_problem(relation=None):
    curves = [Curve(str(i), np.arange(20.), .5 + .03 * i + .01 * np.sin(np.arange(20.)))
              for i in range(20)]
    models = {c.id: Model(components=[Component.create('constant', initial={'offset': .2})])
              for c in curves}
    source = models[curves[0].id].components[0]
    reference = f'${{{curves[0].id}.{source.id}.offset}}'
    if relation == 'equal':
        linked = Component.create('constant', initial={'offset': .2})
        linked.parameters['offset'].link = reference
        models[curves[-1].id].add(linked)
    elif relation == 'lower':
        target = models[curves[-1].id].components[0].parameters['offset']
        target.value = .3
        target.link = reference
        target.link_relation = 'lower'
    plan = FitPlan([c.id for c in curves], mode=FitMode.GLOBAL)
    return curves, models, plan


@pytest.mark.parametrize('relation', [None, 'equal', 'lower'])
def test_sparse_derivatives_keep_cross_curve_equality_and_dynamic_bound_dependencies(relation):
    curves, models, plan = global_problem(relation)
    problem = _Problem(curves, models, plan, default_registry(), CancellationToken(), None)
    vector = problem.initial
    jac = problem.jacobian(vector)
    reference = approx_derivative(lambda v: problem.residual(v, report=False), vector,
                                  method='2-point', bounds=problem.bounds)
    assert sparse.issparse(jac)
    assert jac.toarray() == pytest.approx(reference, abs=1e-7)
    assert jac.data.nbytes + jac.indices.nbytes + jac.indptr.nbytes < reference.nbytes / 4
    assert problem.jacobian(vector, dense=True) == pytest.approx(reference, abs=1e-7)


@pytest.mark.parametrize('loss', ['linear', 'huber', 'soft_l1', 'cauchy'])
def test_sparse_covariance_matches_dense_svd_and_robust_sandwich(loss):
    curves, models, plan = global_problem('equal')
    problem = _Problem(curves, models, plan, default_registry(), CancellationToken(), None)
    jac = problem.jacobian(problem.initial)
    residual = np.random.default_rng(1729).normal(scale=.2, size=jac.shape[0])
    settings = FitSettings(loss=loss)
    sparse_result = _covariance(jac, residual, settings, curves, [])
    dense_result = _covariance(jac.toarray(), residual, settings, curves, [])
    assert sparse_result[0] is not None
    for actual, expected in zip(sparse_result, dense_result, strict=True):
        assert actual == pytest.approx(expected, rel=1e-8, abs=1e-10)


def test_automatic_sparse_fit_matches_explicit_dense_lm_results():
    curves, models, plan = global_problem('equal')
    dense_models = copy.deepcopy(models)
    automatic = Fitter().fit(plan, curves, models)
    plan.settings.solver = 'lm'
    dense = Fitter().fit(plan, curves, dense_models)
    assert automatic.success and dense.success
    assert [p.value for p in automatic.parameters.values()] == pytest.approx(
        [p.value for p in dense.parameters.values()], abs=1e-7)
    assert automatic.covariance == pytest.approx(dense.covariance, rel=1e-6, abs=1e-10)


def test_chunked_sparse_svd_keeps_small_singular_values_without_normal_equations():
    from curvemole.core.jacobians import jacobian_svd
    rng = np.random.default_rng(42)
    dense = rng.normal(size=(3100, 20))
    dense[:, -1] = dense[:, 0] + 1e-7 * dense[:, -1]
    actual, _ = jacobian_svd(sparse.csr_matrix(dense))
    expected = np.linalg.svd(dense, compute_uv=False)
    assert actual == pytest.approx(expected, rel=1e-8)
