"""Synthetic references for regressions identified in the local beta audit."""

import numpy as np
import pytest
from scipy.stats import f, t

from curvemole import Component, Curve, Fitter, Model, Project, Series
from curvemole.core.calculator import (
    apply_background_subtraction,
    apply_column_formula,
    apply_curve_operation,
)
from curvemole.core.diagnostics import contiguous_residual_segments, residual_diagnostics
from curvemole.core.errors import DataValidationError, FitError
from curvemole.core.export import BundleExportSelection, export_bundle
from curvemole.core.fitting import FitMode, FitPlan, FitSettings
from curvemole.core.functions import FunctionDefinition, ParameterSpec, formula_definition
from curvemole.core.registry import default_registry
from curvemole.core.uncertainty import UncertaintyAnalyzer


def constant(value=0.):
    return Model(components=[Component.create("constant", initial={"offset": value})])


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


def test_autocorrelation_threshold_is_calibrated_across_lags_and_excludes_discontinuities():
    samples = np.random.default_rng(24).normal(size=(150, 1000))
    false_alarms = sum(any("95%" in warning for warning in residual_diagnostics(row).warnings) for row in samples)
    assert false_alarms < 16
    rows = np.array([0, 1, 2, 7, 8, 9])
    x = np.array([0., 1., 2., 7., 8., 12.])
    assert contiguous_residual_segments(rows, x) == (slice(0, 3), slice(3, 5), slice(5, 6))
    residual = np.array([1., 1., 1., -1., -1., 1.])
    diagnostic = residual_diagnostics(residual, indices=rows, x=x)
    assert diagnostic.durbin_watson == 0
    assert any("skip gaps" in warning for warning in diagnostic.warnings)


def test_convolution_rejects_nonuniform_grid_even_at_a_large_origin():
    origin = float(2**40)
    x = origin + np.spacing(origin) * np.array([0, 4, 16, 20, 32])
    model = constant(1.)
    model.components.append(Component.create("constant", initial={"offset": 1}, operator="convolve"))
    with pytest.raises(DataValidationError, match="uniformly spaced"):
        model.evaluate(x)


def test_failed_bundle_regeneration_leaves_all_preexisting_files_untouched(tmp_path, monkeypatch):
    project = Project()
    curve = Curve("data", [0, 1], [0, 1])
    project.add_series(Series("series", [curve]))
    selection = BundleExportSelection.none(wide_tables=True, html_summary=True)
    export_bundle(project, tmp_path, selection=selection)
    before = {file.relative_to(tmp_path): file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()}
    config = dict(project.export_config)
    curve.move_points([1], y=[9])

    def fail(*args, **kwargs):
        raise OSError("Synthetic write failure")

    monkeypatch.setattr("curvemole.core.export.bundle.generate_html_report", fail)
    with pytest.raises(OSError, match="Synthetic write failure"):
        export_bundle(project, tmp_path, selection=selection, overwrite=True)
    assert {file.relative_to(tmp_path): file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()} == before
    assert project.export_config == config


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


def test_automatic_colours_skip_a_colour_chosen_by_the_processor():
    from curvemole.gui.colours import SERIES_PALETTES
    from curvemole.gui.folder_import import _colour_imports

    palette = SERIES_PALETTES["Neon"]
    custom = Curve("explicit", [0, 1], [1, 2], colour=palette[1])
    automatic = Curve("automatic", [0, 1], [1, 2])
    _colour_imports([custom, automatic], palette)
    assert custom.colour == palette[1]
    assert automatic.colour == palette[0]
