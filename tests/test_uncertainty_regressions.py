"""Regression tests for uncertainty (formerly grouped by audit)."""
from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import f, norm

from curvemole import Component, Curve, Fitter, Model
from curvemole.core.data import Transformation
from curvemole.core.errors import (
    FitError,
)
from curvemole.core.fitting import (
    FitMode,
    FitPlan,
    FitSettings,
)
from curvemole.core.folder_import import merge_acquisition_results
from curvemole.core.functions import formula_definition
from curvemole.core.registry import default_registry
from curvemole.core.state import copy_result_maps
from curvemole.core.uncertainty import UncertaintyAnalyzer


def line():
    x = np.linspace(0, 1, 20)
    return Curve("line", x, 1 + 2*x + .01*np.sin(15*x), sigma_y=np.full(20, .1))

def constant(value=0.):
    return Model(components=[Component.create("constant", initial={"offset": value})])

def constant_fit(y, *, settings=None, **kwargs):
    c = Curve("c", np.arange(len(y), dtype=float), y, **kwargs)
    m = Model(components=[Component.create("constant")])
    return c, m, Fitter().fit_single(c, m, settings)


def test_masked_block_bootstrap_and_current_sigma_are_preserved():
    c = line()
    c.apply_transformation(Transformation("y_multiply", {"value": 10}))
    c.mask_interval(.4, .5)
    m = Model(components=[Component.create("linear")])
    plan = FitPlan([c.id])
    baseline = Fitter().fit(plan, [c], {c.id: m})

    class CheckedFitter(Fitter):
        def fit(self, plan, curves, models, **kwargs):
            trial = curves[c.id]
            np.testing.assert_array_equal(trial.current_sigma_y, c.current_sigma_y)
            np.testing.assert_array_equal(trial.effective_mask, c.effective_mask)
            assert not trial.transformations
            return super().fit(plan, curves, models, **kwargs)

    analyzer = UncertaintyAnalyzer(CheckedFitter())
    for method in (analyzer.block_bootstrap, analyzer.parametric_monte_carlo, analyzer.residual_bootstrap):
        result = method(baseline, plan, [c], {c.id: m}, replicates=3, seed=42)
        assert result.completed == 3
    assert len(c.transformations) == 1

def test_linked_uncertainty_at_exact_upper_bound():
    c = line()
    m = Model(components=[Component.create("linear")])
    q = m.components[0]
    q.parameters["slope"].value = .5
    q.parameters["slope"].maximum = 1
    q.parameters["intercept"].link = "${" + m.parameter_path(c.id, q.id, "slope") + "}"
    result = Fitter().fit_single(c, m, FitSettings(solver="nelder_mead"))
    assert result.success
    assert q.parameters["slope"].value == 1
    assert q.parameters["slope"].standard_error > 0
    assert q.parameters["intercept"].standard_error == pytest.approx(q.parameters["slope"].standard_error)

def test_one_parameter_profile_matches_direct_chi_square_and_preserves_state():
    c = line()
    m = Model(components=[Component.create("constant")])
    baseline = Fitter().fit_single(c, m)
    state = c.state
    path = next(iter(baseline.parameters))
    result = UncertaintyAnalyzer().profile_parameter(baseline, c, m, path, points=5)
    assert result.failed_points == 0
    expected = [np.sum(((c.y - v)/c.current_sigma_y)**2) - baseline.statistics["chi_square"] for v in result.values]
    np.testing.assert_allclose(result.delta_chi_square, np.maximum(expected, 0), atol=1e-10)
    assert c.state == state

def test_result_snapshot_detaches_method_maps_but_shares_finished_arrays():
    array = np.arange(100.)
    record = {"analysis": array}
    original = {"uncertainty_reports_by_curve": {"curve": {"covariance": record}}}
    saved = copy_result_maps(original)
    original["uncertainty_reports_by_curve"]["curve"]["new_method"] = {"analysis": np.ones(100)}
    assert set(saved["uncertainty_reports_by_curve"]["curve"]) == {"covariance"}
    assert saved["uncertainty_reports_by_curve"]["curve"]["covariance"]["analysis"] is array

def test_profile_rejects_a_reference_fit_when_a_better_minimum_appears():
    registry = default_registry().copy()
    registry.register(formula_definition("audit_square", "Square", "a*a + 0*x", defaults={"a": 0.}))
    curve = Curve("square", np.arange(10.), np.ones(10), sigma_y=np.full(10, .1))
    model = Model(components=[Component.create("audit_square", registry=registry)])
    fitter = Fitter(registry)
    result = fitter.fit_single(curve, model)
    assert result.success and result.statistics["chi_square"] == pytest.approx(1000.)
    with pytest.raises(FitError, match="better fit than its baseline"):
        UncertaintyAnalyzer(fitter).profile_parameter(
            result, curve, model, result.free_parameter_paths[0], lower=-1.5, upper=1.5, points=31,
        )

def test_unknown_noise_profile_matches_exact_linear_f_interval():
    x = np.arange(7.)
    y = np.array([3.0, 3.2, 3.6, 4.0, 3.4, 3.7, 4.1])
    curve = Curve("location", x, y)
    model = constant()
    baseline = Fitter().fit_single(curve, model)
    result = UncertaintyAnalyzer().profile_parameter(baseline, curve, model, baseline.free_parameter_paths[0])
    half = np.sqrt(f.ppf(.95, 1, len(y) - 1)) * np.std(y, ddof=1) / np.sqrt(len(y))
    assert result.interval == pytest.approx((y.mean() - half, y.mean() + half))

def test_bound_profile_keeps_regions_without_claiming_calibrated_endpoints():
    curve = Curve("bounded location", np.arange(10.), np.full(10, -.2), sigma_y=np.ones(10))
    model = constant(.1)
    model.components[0].parameters["offset"].set_bounds(0., 2.)
    baseline = Fitter().fit_single(curve, model)
    assert next(iter(baseline.parameters.values())).at_bound
    profile = UncertaintyAnalyzer().profile_parameter(
        baseline, curve, model, baseline.free_parameter_paths[0], lower=0., upper=1.,
    )
    assert profile.confidence_regions[0][0] == 0.
    assert profile.interval == (None, None)
    assert any("without calibrated" in warning for warning in profile.warnings)

def test_replicas_can_search_both_minima_without_recalculating_covariance(monkeypatch):
    registry = default_registry().copy()
    registry.register(formula_definition("audit_modes", "Square", "a*a+0*x", defaults={"a": 1.},
                                         bounds={"a": (-2., 2.)}))
    curve = Curve("two minima", np.arange(8.), np.ones(8), sigma_y=np.full(8, .1))
    model = Model(components=[Component.create("audit_modes", registry=registry)])
    fitter = Fitter(registry)
    baseline = fitter.fit_single(curve, model)

    def unexpected_covariance(*args, **kwargs):
        pytest.fail("A replica attempted to calculate a covariance matrix.")

    monkeypatch.setattr("curvemole.core.uncertainty._parallel_safe", lambda *args: False)
    monkeypatch.setattr("curvemole.core.fitting._covariance", unexpected_covariance)
    plan = FitPlan([curve.id], settings=FitSettings(solver="differential_evolution", de_maxiter=15, de_popsize=5))
    outcome = UncertaintyAnalyzer(fitter).parametric_monte_carlo(
        baseline, plan, [curve], {curve.id: model}, replicates=16, seed=173,
    )
    assert outcome.completed == 16
    assert np.any(outcome.samples[:, 0] > 0)
    assert np.any(outcome.samples[:, 0] < 0)

def test_acquisition_merge_preserves_previous_results_and_rejects_cross_curve_records():
    old = {"uncertainty_by_curve": {"old": {"bootstrap": 1}}, "last_fit": "old fit"}
    new = {"uncertainty_by_curve": {"new": {"profile": 2}}, "last_fit": "new fit"}
    merged = merge_acquisition_results(old, new, {"new"})
    assert set(merged["uncertainty_by_curve"]) == {"old", "new"}
    assert merged["import_result_history"] == [{"key": "last_fit", "value": "old fit"}]
    assert old == {"uncertainty_by_curve": {"old": {"bootstrap": 1}}, "last_fit": "old fit"}
    with pytest.raises(ValueError, match="unrelated"):
        merge_acquisition_results(old, new, {"other"})

def test_acquisition_merge_preserves_display_choices_and_incoming_history():
    old = {
        "uncertainty_display_method_by_curve": {"old": "bootstrap"},
        "import_result_history": [{"key": "old", "value": 1}],
    }
    new = {
        "uncertainty_display_method_by_curve": {"new": "profile"},
        "import_result_history": [{"key": "new", "value": 2}],
    }
    merged = merge_acquisition_results(old, new, {"new"})
    assert merged["uncertainty_display_method_by_curve"] == {"old": "bootstrap", "new": "profile"}
    assert (
        merged["import_result_history"]
        == old["import_result_history"] + new["import_result_history"]
    )

def test_profile_is_invariant_to_measurement_units_when_noise_scale_is_unknown():
    profiles = []
    for factor in (1, 100):
        c, m, result = constant_fit(np.arange(5.0) * factor)
        profile = UncertaintyAnalyzer().profile_parameter(
            result, c, m, next(iter(result.parameters)), lower=0, upper=4 * factor, points=41
        )
        profiles.append(profile)
    assert profiles[0].delta_chi_square == pytest.approx(profiles[1].delta_chi_square)
    assert profiles[0].interval == pytest.approx(np.asarray(profiles[1].interval) / 100)

def test_profile_known_sigma_uses_chi_square_and_robust_profile_is_rejected():
    c, m, r = constant_fit(np.arange(5.0), sigma_y=np.ones(5))
    p = UncertaintyAnalyzer().profile_parameter(
        r, c, m, next(iter(r.parameters)), lower=1, upper=3, points=3
    )
    assert p.delta_chi_square == pytest.approx([5, 0, 5])
    r.settings.loss = "huber"
    with pytest.raises(FitError, match="robust"):
        UncertaintyAnalyzer().profile_parameter(r, c, m, next(iter(r.parameters)))

def test_profile_convolution_preserves_regular_grid_before_masking():
    x = np.linspace(-5, 5, 101)
    signal = Component.create("gaussian", initial={"area": 2, "center": 0, "sigma": 0.5})
    kernel = Component.create(
        "gaussian", operator="convolve", initial={"area": 1, "center": 0, "sigma": 0.3}
    )
    for comp in (signal, kernel):
        for name, parameter in comp.parameters.items():
            parameter.fixed = not (comp is signal and name == "area")
    model = Model(components=[signal, kernel])
    curve = Curve("conv", x, model.evaluate(x), sigma_y=np.ones(len(x)))
    curve.add_mask("interior").excluded[30] = True
    baseline = Fitter().fit_single(curve, model)
    profile = UncertaintyAnalyzer().profile_parameter(
        baseline,
        curve,
        model,
        next(iter(baseline.free_parameter_paths)),
        lower=1.9,
        upper=2.1,
        points=5,
    )
    assert profile.failed_points == 0
    assert np.isfinite(profile.delta_chi_square).all()

def test_zero_weight_rows_do_not_change_uncertainty_or_sample_count():
    _, _, a = constant_fit([1, 2, 4], weights=[1, 1, 1])
    _, _, b = constant_fit([1, 2, 4, 9999, -9999], weights=[1, 1, 1, 0, 0])
    assert b.covariance == pytest.approx(a.covariance)
    assert b.statistics["N"] == 3
    assert b.statistics["degrees_of_freedom"] == 2

def test_zero_residual_profile_needs_an_explicit_known_noise_scale():
    c, m, r = constant_fit(np.ones(5))
    with pytest.raises(FitError, match="zero-residual"):
        UncertaintyAnalyzer().profile_parameter(r, c, m, next(iter(r.parameters)))

def test_unknown_scale_global_profile_uses_all_uncoupled_curves():

    curves = [Curve(str(i), np.arange(5.0), np.arange(5.0) + i) for i in range(2)]
    models = {c.id: Model(components=[Component.create("constant")]) for c in curves}
    r = Fitter().fit(FitPlan([c.id for c in curves], mode=FitMode.GLOBAL), curves, models)
    c = curves[0]
    path = next(iter(models[c.id].parameter_map(c.id)))
    prof = UncertaintyAnalyzer().profile_parameter(
        r, c, models[c.id], path, lower=1, upper=3, points=3
    )
    assert prof.delta_chi_square == pytest.approx([10 * np.log(25 / 20), 0, 10 * np.log(25 / 20)])

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
