"""Regression tests for fitting (formerly grouped by audit)."""
from __future__ import annotations

import copy
import itertools

import numpy as np
import pytest
from scipy import sparse
from scipy.optimize._numdiff import approx_derivative
from scipy.stats import t

from curvemole import Component, Curve, Fitter, Model, Project, Transformation
from curvemole.core.calculator import (
    apply_background_subtraction,
    apply_column_formula,
    apply_curve_operation,
)
from curvemole.core.errors import (
    FitError,
)
from curvemole.core.fit_records import baseline_for_curve
from curvemole.core.fitting import (
    CancellationToken,
    FitMode,
    FitPlan,
    FitSettings,
    _covariance,
    _Problem,
)
from curvemole.core.functions import FunctionDefinition, ParameterSpec, formula_definition
from curvemole.core.matrices import BlockDiagonalMatrix
from curvemole.core.parameters import Parameter
from curvemole.core.registry import default_registry


def line():
    x = np.linspace(0, 1, 20)
    return Curve("line", x, 1 + 2*x + .01*np.sin(15*x), sigma_y=np.full(20, .1))

def project_with_curves(count=3):
    project = Project()
    for i in range(count):
        curve = Curve(f"Data {i}", np.linspace(-5., 5., 101), np.full(101, i + 1.))
        project.add_curve(curve)
        project.model_for(curve.id).add(Component.create("constant", initial={"offset": i + 1.}))
    return project

def constant(value=0.):
    return Model(components=[Component.create("constant", initial={"offset": value})])

def constant_fit(y, *, settings=None, **kwargs):
    c = Curve("c", np.arange(len(y), dtype=float), y, **kwargs)
    m = Model(components=[Component.create("constant")])
    return c, m, Fitter().fit_single(c, m, settings)

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


def test_disabled_parameters_do_not_change_statistics_but_link_dependencies_remain():
    c = line()
    m = Model(components=[Component.create("linear")])
    baseline = Fitter().fit_single(c, m)
    disabled = Component.create("gaussian")
    disabled.enabled = False
    m.add(disabled)
    result = Fitter().fit_single(c, m)
    assert result.statistics["k"] == 2
    assert result.statistics["degrees_of_freedom"] == 18
    assert result.statistics["AIC"] == pytest.approx(baseline.statistics["AIC"])
    assert not any("rank-deficient" in w for w in result.warnings)
    # A disabled component can still supply a genuinely used linked parameter.
    m.components[0].parameters["intercept"].link = "${" + m.parameter_path(c.id, disabled.id, "center") + "}"
    result = Fitter().fit_single(c, m)
    assert result.success and result.statistics["k"] == 2
    assert disabled.parameters["center"].value == pytest.approx(1, abs=.01)

@pytest.mark.parametrize("count", [100, 101])
@pytest.mark.parametrize("selection", ["mask", "ranges"])
@pytest.mark.parametrize("descending", [False, True])
def test_convolution_selects_residuals_without_changing_model(count, selection, descending):
    x = np.linspace(-5., 5., count)
    if descending:
        x = x[::-1]
    model = Model(components=[Component.create("gaussian", initial={"center": .5, "sigma": .5}),
                              Component.create("gaussian", operator="convolve", initial={"sigma": .4})])
    curve = Curve("Convolution", x, model.evaluate(x))
    if selection == "mask":
        curve.masks[curve.active_mask].excluded[(x > -.3) & (x < .3)] = True
    else:
        curve.fit_ranges = [(-4., -1.), (1., 4.)]
    problem = _Problem([curve], {curve.id: model}, FitPlan([curve.id]),
                       default_registry(), CancellationToken(), None)
    np.testing.assert_allclose(problem.residual(problem.initial), 0., atol=1e-14)
    values = problem.values(problem.initial)
    output = problem.outputs(values)[curve.id]
    np.testing.assert_allclose(output.fitted, model.evaluate(curve.x)[output.indices])

def test_baseline_extracts_blocks_without_dense_conversion():
    project = project_with_curves()
    result = Fitter().fit(FitPlan([c.id for c in project.curves]), project.curves, project.models)
    reference = np.asarray(result.covariance)
    class BlocksOnly(BlockDiagonalMatrix):
        def __array__(self, *args, **kwargs):
            raise AssertionError("An independent baseline must never allocate the full matrix")
    result.covariance = BlocksOnly(result.covariance.blocks)
    result.correlation = BlocksOnly(result.correlation.blocks)
    for i, curve in enumerate(project.curves):
        baseline = baseline_for_curve(result, curve.id)
        np.testing.assert_array_equal(baseline.covariance, reference[np.ix_([i], [i])])

def test_refinement_can_leave_differential_evolution_search_bounds():
    curve = Curve("constant", np.arange(25.), np.full(25, 10.), sigma_y=np.ones(25))
    model = constant(1.)
    result = Fitter().fit_single(curve, model, FitSettings(solver="differential_evolution", de_maxiter=20))
    assert result.success
    assert model.components[0].parameters["offset"].value == pytest.approx(10.)
    assert result.statistics["chi_square"] == pytest.approx(0.)
    execution = result.provenance["executions"][0]
    assert execution["search_bounds"] == [[.5], [1.5]]
    assert execution["solver_bounds"] == [[None], [None]]

def test_known_inverse_variance_matches_standard_deviation_and_relative_scale_is_explicit():
    x = np.arange(7.)
    y = 4 + .01 * np.sin(x)
    results = [
        Fitter().fit_single(Curve("errors", x, y, **errors), constant())
        for errors in ({"sigma_y": np.ones_like(x)}, {"weights": np.ones_like(x)})
    ]
    for result in results:
        assert next(iter(result.parameters.values())).standard_error == pytest.approx(1 / np.sqrt(len(x)))
    assert results[0].statistics == pytest.approx(results[1].statistics)
    relative = Fitter().fit_single(Curve("relative", x, y, weights=np.ones_like(x)), constant(),
                                  FitSettings(absolute_sigma=False))
    assert relative.statistics["reduced_chi_square"] is None
    estimate = next(iter(relative.parameters.values()))
    assert (estimate.ci_high - estimate.value) / estimate.standard_error == pytest.approx(t.ppf(.975, 6))

def test_inference_is_disabled_for_arbitrary_weights_and_failed_fits():
    x = np.arange(21.)
    curve = Curve("arbitrary", x, np.sin(x), weights=np.full_like(x, 3), weights_are_inverse_variance=False)
    result = Fitter().fit_single(curve, constant(), FitSettings(absolute_sigma=True))
    assert result.success
    assert result.statistics["weighted_residual_sum_squares"] > 0
    assert all(result.statistics[key] is None for key in ("chi_square", "reduced_chi_square", "AIC", "BIC"))
    assert result.covariance is None
    curve = Curve("gaussian", x, np.exp(-((x - 12) / 3)**2))
    model = Model(components=[Component.create("gaussian", initial={"area": 50, "sigma": 4, "center": 3})])
    result = Fitter().fit_single(curve, model, FitSettings(max_nfev=1))
    assert not result.success and result.statistics["AIC"] is None
    assert all(item.standard_error is None for item in result.parameters.values())

def test_underdetermined_auto_fit_and_within_spectrum_r_squared():
    curve = Curve("short", [0, 1], [1, 1])
    model = Model(components=[Component.create("constant") for _ in range(3)])
    result = Fitter().fit_single(curve, model)
    assert result.success and result.covariance is None
    assert any("underdetermined" in warning for warning in result.warnings)
    x = np.arange(6.)
    curves = [Curve("low", x, x), Curve("high", x, 1000 + x)]
    models = {curve.id: constant() for curve in curves}
    result = Fitter().fit(FitPlan(list(models), FitMode.GLOBAL), curves, models)
    assert result.statistics["R_squared"] > .99
    assert result.statistics["within_spectrum_R_squared"] == pytest.approx(0.)

def test_formula_propagates_cross_axis_errors_and_retains_covariance_for_the_next_formula():
    x = np.arange(7.)
    curve = Curve("formula", x, x, sigma_x=np.full_like(x, .3), sigma_y=np.full_like(x, .4))
    apply_column_formula(curve, "y", "x+y")
    assert curve.current_sigma_y == pytest.approx(np.full_like(x, .5))
    apply_column_formula(curve, "x", "y")
    assert curve.current_sigma_x == pytest.approx(np.full_like(x, .5))
    apply_column_formula(curve, "y", "x+y")
    assert curve.current_sigma_y == pytest.approx(np.ones_like(x))

def test_interpolated_self_operation_and_fitted_background_preserve_error_semantics():
    x = np.arange(10.)
    curve = Curve("masked row", x, x + 2, sigma_y=np.ones_like(x))
    curve.mask_interval(4, 4)
    apply_curve_operation(curve, curve, "curve_subtract")
    assert curve.current_sigma_y[4] == pytest.approx(np.sqrt(1.5))
    assert curve.current_sigma_y[3] == 0
    original = Curve("background", x, x + 100, sigma_y=np.ones_like(x))
    parameter = np.full_like(x, original.y.mean())
    apply_background_subtraction(original, parameter, method="mean", description="Estimated mean")
    result = Fitter().fit_single(original, constant())
    assert original.has_correlated_y_errors
    assert result.covariance is None and result.statistics["AIC"] is None
    original.undo_transformation()
    apply_background_subtraction(original, parameter, method="external", description="Exact reference",
                                 estimated=False)
    assert not original.has_correlated_y_errors

def test_replay_detects_mutated_python_evaluator_state():
    def definition(gain):
        def evaluate(x, parameters, metadata):
            return gain * parameters["offset"] + 0 * x

        return FunctionDefinition("audit_closure", "Closure", "background", evaluate,
                                  (ParameterSpec("offset", 1.),))

    registry = default_registry().copy()
    registry.register(definition(1))
    fitter = Fitter(registry)
    curve = Curve("closure", np.arange(8.), np.full(8, 4.))
    model = Model(components=[Component.create("audit_closure", registry=registry)])
    baseline = fitter.fit_single(curve, model)
    assert fitter.replay(baseline, [curve]).success
    registry.register(definition(2), replace=True)
    with pytest.raises(FitError, match="definitions changed"):
        fitter.replay(baseline, [curve])

def test_huber_sandwich_matches_location_reference_and_is_solver_independent():
    results = [
        constant_fit(
            [0, 0, 0, 0, 10], settings=FitSettings(solver=solver, loss="huber", f_scale=1)
        )[2]
        for solver in ("local", "powell")
    ]
    for r in results:
        assert r.success
        assert next(iter(r.parameters.values())).value == pytest.approx(0.25)
        assert r.covariance[0, 0] == pytest.approx(0.09765625, rel=1e-5)

@pytest.mark.parametrize("loss", ["soft_l1", "cauchy"])
def test_other_robust_covariances_are_solver_independent(loss):
    results = [
        constant_fit(
            [0, 0.1, -0.1, 0.2, 10],
            settings=FitSettings(solver=solver, loss=loss, f_scale=1, powell_xtol=1e-10),
        )[2]
        for solver in ("local", "powell")
    ]
    assert results[0].covariance == pytest.approx(results[1].covariance, rel=1e-4)

def test_gaussian_information_criteria_follow_weighted_likelihood():
    c, m, r = constant_fit([10, 1, -1, 2], sigma_y=[100, 0.1, 0.1, 0.1])
    assert r.statistics["negative_twice_log_likelihood"] == pytest.approx(
        r.statistics["chi_square"] + len(c) * np.log(2 * np.pi) + 2 * np.log(c.sigma_y).sum()
    )
    assert r.statistics["likelihood_parameters"] == 1
    assert r.statistics["AIC"] == pytest.approx(r.statistics["negative_twice_log_likelihood"] + 2)
    # Relative weights and sigma with an estimated common scale are equivalent.
    _, _, w = constant_fit(
        c.y, weights=1 / c.sigma_y**2, settings=FitSettings(absolute_sigma=False)
    )
    _, _, e = constant_fit(c.y, sigma_y=c.sigma_y, settings=FitSettings(absolute_sigma=False))
    assert w.statistics["AIC"] == pytest.approx(e.statistics["AIC"])
    assert w.statistics["likelihood_parameters"] == 2

def test_disabled_formula_has_same_serial_and_parallel_behavior():
    registry = default_registry().copy()
    registry.register(formula_definition("disabled_audit_custom", "disabled", "scale*x"))
    curves = [Curve(str(i), np.arange(5.0), np.arange(5.0) * 0.1 + 2) for i in range(2)]
    models = {}
    for c in curves:
        disabled = Component.create("disabled_audit_custom", registry=registry)
        disabled.enabled = False
        models[c.id] = Model(components=[Component.create("constant"), disabled])
    results = [
        Fitter(registry).fit(
            FitPlan([c.id for c in curves], settings=FitSettings(workers=n)),
            curves,
            copy.deepcopy(models),
        )
        for n in (1, 2)
    ]
    assert all(r.success for r in results)
    assert [p.value for p in results[0].parameters.values()] == pytest.approx(
        [p.value for p in results[1].parameters.values()]
    )

def test_cancellation_before_covariance_restores_model_and_curve_state():
    from curvemole.core.errors import FitCancelled
    from curvemole.core.fitting import CancellationToken

    c = Curve("cancel", np.arange(5.0), [0, 0, 0, 0, 10])
    comp = Component.create("constant", initial={"offset": 7})
    model = Model(components=[comp])
    token = CancellationToken()
    original_state = c.state

    def progress(fraction, text):
        if text.startswith("Evaluation "):
            token.cancel()

    with pytest.raises(FitCancelled):
        Fitter().fit(
            FitPlan([c.id], settings=FitSettings(loss="huber")),
            [c],
            {c.id: model},
            cancellation=token,
            progress=progress,
        )
    assert c.state == original_state
    assert comp.parameters["offset"].value == 7

def test_prepared_link_order_invalidates_on_expression_changes():
    from curvemole.core.parameters import EqualityParameterResolver
    source = Parameter('source', 2.)
    linked = Parameter('linked', 0., link='${source} * 2')
    resolver = EqualityParameterResolver({'linked': linked, 'source': source})
    assert resolver.resolve()['linked'] == 4.
    source.value = 3.
    assert resolver.resolve()['linked'] == 6.
    linked.link = '${source} * 3'
    assert resolver.resolve()['linked'] == 9.

@pytest.mark.parametrize('scale', [1., 1e-9, 1e-18])
@pytest.mark.parametrize('solver', ['local', 'differential_evolution'])
def test_gaussian_fit_is_invariant_to_x_units(scale, solver):
    x = np.linspace(-5, 5, 101)*scale
    y = np.exp(-.5*((x/scale-.4)/.8)**2)
    curve = Curve('units', x, y, sigma_y=np.full(len(x), .01))
    peak = Component.create('gaussian', initial={'area': np.sqrt(2*np.pi)*scale,
                                                 'center': 0, 'sigma': scale})
    result = Fitter().fit_single(curve, Model(components=[peak]),
                                FitSettings(solver=solver, seed=1729, de_maxiter=60))
    assert result.success
    assert peak.parameters['center'].value/scale == pytest.approx(.4, abs=1e-8)
    assert peak.parameters['sigma'].value/scale == pytest.approx(.8, abs=1e-8)
    assert not any(estimate.at_bound for estimate in result.parameters.values())
    assert result.statistics['chi_square'] < 1e-14

@pytest.mark.parametrize('scale', [1., 1e-9, 1e-18])
def test_formula_and_nonlinear_link_derivatives(scale):
    y = np.arange(1., 4.)*scale
    curve = Curve('cubic', np.arange(3.), y, sigma_y=y*.01)
    curve.apply_transformation(Transformation('custom_formula', {'axis': 'y', 'formula': 'y**3'}))
    np.testing.assert_allclose(curve.current_sigma_y, 3*y**2*(y*.01), rtol=1e-8, atol=0)
    curve = Curve('linked', np.arange(8.), np.full(8, scale+scale**3), sigma_y=np.full(8, scale/10))
    first, second = Component.create('constant', initial={'offset': scale}), Component.create('constant')
    second.parameters['offset'].link = f'${{{curve.id}.{first.id}.offset}}**3'
    result = Fitter().fit_single(curve, Model(components=[first, second]))
    source = result.parameters[f'{curve.id}.{first.id}.offset']
    linked = result.parameters[f'{curve.id}.{second.id}.offset']
    assert linked.standard_error == pytest.approx(3*source.value**2*source.standard_error, rel=1e-8, abs=0)

@pytest.mark.parametrize('count', [100, 101])
@pytest.mark.parametrize('reverse', [False, True])
def test_convolution_center_against_analytic_gaussian(count, reverse):
    x = np.linspace(-5, 5, count)[::(-1 if reverse else 1)]
    peak = Component.create('gaussian', initial={'area': 2, 'center': .25, 'sigma': .5})
    kernel = Component.create('gaussian', initial={'area': 1, 'center': 0, 'sigma': .3}, operator='convolve')
    model = Model(components=[peak, kernel])
    width = np.sqrt(.5**2+.3**2)
    expected = 2*np.exp(-.5*((x-.25)/width)**2)/(width*np.sqrt(2*np.pi))
    np.testing.assert_allclose(model.evaluate(x), expected, atol=2e-12)
    for component in model.components:
        for name, parameter in component.parameters.items():
            parameter.fixed = component is not peak or name != 'center'
    curve = Curve('convolution', x, expected, sigma_y=np.full(count, .001))
    result = Fitter().fit_single(curve, model)
    assert result.success
    assert peak.parameters['center'].value == pytest.approx(.25, abs=1e-10)

def test_compensated_sum_ignores_fresh_ids_and_cancellation():
    for terms in itertools.permutations([1e16, 1., -1e16]):
        model = Model(components=[Component.create('constant', initial={'offset': value}) for value in terms])
        np.testing.assert_array_equal(model.evaluate(np.arange(8.)), np.ones(8))
    components = [Component.create('constant', initial={'offset': value}) for value in [1e16, 0., -1e16]]
    for index, component in enumerate(components):
        component.parameters['offset'].fixed = index != 1
    result = Fitter().fit_single(Curve('sum', np.arange(8.), np.ones(8), sigma_y=np.ones(8)), Model(components=components))
    assert result.success
    assert components[1].parameters['offset'].value == pytest.approx(1)

def test_per_curve_callback_and_sequential_baseline_preserve_replay_inputs():
    from curvemole.core.fit_records import baseline_for_curve
    from curvemole.core.fitting import FitMode
    from curvemole.core.sequential_fit import SequentialFitPlan
    curves = [Curve('constant', np.arange(8.), np.ones(8)),
              Curve('line', np.arange(8.), np.arange(8.)+1)]
    models = {curves[0].id: Model(components=[Component.create('constant')]),
              curves[1].id: Model(components=[Component.create('linear')])}
    recorded = {}
    Fitter().fit(FitPlan([curve.id for curve in curves]), curves, models,
                 on_curve_result=lambda cid, result: recorded.update({cid: copy.deepcopy(result)}))
    for curve in curves:
        replay = Fitter().replay(recorded[curve.id], curves)
        assert replay.success
        assert list(replay.parameters) == list(recorded[curve.id].parameters)
    models = {curves[0].id: Model(components=[Component.create('constant')])}
    plan = SequentialFitPlan([curve.id for curve in curves], FitMode.SEQUENTIAL,
                             monitor_residuals=False, monitor_parameters=False)
    result = Fitter().fit(plan, curves, models)
    assert result.success
    assert Fitter().replay(result, curves).success
    individual = baseline_for_curve(result, curves[1].id)
    assert Fitter().replay(individual, curves).success

def test_individual_baselines_retain_complete_statistics_without_batch_aggregation():
    curves = [Curve(str(i), np.arange(5.), np.array([0, 1, 1, 2, 3]) + i) for i in range(2)]
    models = {c.id: Model(components=[Component.create('constant')]) for c in curves}
    batch = Fitter().fit(FitPlan([c.id for c in curves]), curves, models)
    for c in curves:
        baseline = baseline_for_curve(batch, c.id)
        single = Fitter().fit_single(c, models[c.id])
        for key in ('N', 'k', 'degrees_of_freedom', 'chi_square', 'reduced_chi_square', 'AIC', 'AICc', 'BIC'):
            assert baseline.statistics[key] == pytest.approx(single.statistics[key])
        assert baseline_for_curve(single, c.id).statistics == single.statistics

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
