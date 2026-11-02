"""Independent numerical references for the seven November scientific findings."""
import copy
import itertools

import numpy as np
import pytest
from scipy.stats import norm

from curvemole import Component, Curve, Fitter, Model, Project
from curvemole.core.data import Transformation
from curvemole.core.errors import DataValidationError, FitError
from curvemole.core.fitting import FitPlan, FitSettings
from curvemole.core.functions import formula_definition
from curvemole.core.registry import default_registry
from curvemole.core.serialization import load_project, save_project
from curvemole.core.uncertainty import UncertaintyAnalyzer


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


@pytest.mark.parametrize('scale', [1., 1e-18])
def test_fft_rejects_irregular_grid_at_any_units(scale):
    model = Model(components=[Component.create('constant'), Component.create('constant', operator='convolve')])
    with pytest.raises(DataValidationError, match='uniformly spaced'):
        model.evaluate(np.array([0, 1, 2, 4, 8.])*scale)


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


def test_profile_endpoints_are_refined_and_disconnected_regions_are_preserved():
    curve = Curve('location', np.arange(25.), np.zeros(25), sigma_y=np.ones(25))
    model = Model(components=[Component.create('constant')])
    baseline = Fitter().fit_single(curve, model)
    result = UncertaintyAnalyzer().profile_parameter(baseline, curve, model, baseline.free_parameter_paths[0])
    np.testing.assert_allclose(result.interval, [-norm.ppf(.975)/5, norm.ppf(.975)/5], rtol=1e-9)
    registry = default_registry().copy()
    registry.register(formula_definition('audit_square', 'square', 'a*a+0*x', defaults={'a': 1}))
    curve = Curve('two modes', np.arange(8.), np.ones(8), sigma_y=np.full(8, .2))
    model = Model(components=[Component.create('audit_square', registry=registry)])
    fitter = Fitter(registry)
    baseline = fitter.fit_single(curve, model)
    result = UncertaintyAnalyzer(fitter).profile_parameter(baseline, curve, model, baseline.free_parameter_paths[0], lower=-1.5, upper=1.5, points=61)
    assert len(result.confidence_regions) == 2
    assert result.confidence_regions[0][1] < 0 < result.confidence_regions[1][0]
    assert result.interval == result.confidence_regions[1]
    assert 'disconnected' in ' '.join(result.warnings)


def test_checked_replay_restores_initial_de_state_after_archive(tmp_path):
    x = np.linspace(-5, 5, 51)
    curve = Curve('replay', x, np.exp(-.5*((x-.4)/.8)**2), sigma_y=np.full(len(x), .01))
    model = Model(components=[Component.create('gaussian', initial={'area': 2.5, 'center': 0, 'sigma': 1})])
    plan = FitPlan([curve.id], settings=FitSettings(solver='differential_evolution', seed=1729, de_maxiter=20))
    baseline = Fitter().fit(plan, [curve], {curve.id: model})
    project = Project()
    project.add_curve(curve)
    project.models[curve.id] = model
    project.results['last_fit'] = baseline
    loaded = load_project(save_project(project, tmp_path/'replay.fitproj'))
    saved = loaded.results['last_fit']
    replay = Fitter().replay(saved, loaded.curves)
    assert replay.provenance['executions'] == saved.provenance['executions']
    assert [p.value for p in replay.parameters.values()] == [p.value for p in saved.parameters.values()]
    changed = copy.deepcopy(saved)
    changed.provenance['environment']['numpy'] = 'different'
    with pytest.raises(FitError, match='environment changed'):
        Fitter().replay(changed, loaded.curves)
    changed = copy.deepcopy(saved)
    changed.provenance['functions']['gaussian']['sha256'] = 'different'
    with pytest.raises(FitError, match='definitions changed'):
        Fitter().replay(changed, loaded.curves)
    loaded.curves[0].apply_transformation(Transformation('y_multiply', {'value': 2}))
    with pytest.raises(FitError, match='input data changed'):
        Fitter().replay(saved, loaded.curves)


def test_background_uses_compensated_sum():
    components = [Component.create('constant', initial={'offset': value}) for value in [1e16, 1., -1e16]]
    for component in components:
        component.is_background = True
    model = Model(components=components)
    np.testing.assert_array_equal(model.background(np.arange(3.)), np.ones(3))


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
