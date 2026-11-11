"""Numerical counterexamples from the November scientific audit."""

from __future__ import annotations

import csv

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Model, Project
from curvemole.core.calculator import apply_curve_operation, apply_scalar
from curvemole.core.errors import DataValidationError, FitError
from curvemole.core.export import export_function_parameters, parameter_dataframe
from curvemole.core.fitting import FitMode, FitPlan, FitSettings
from curvemole.core.importers import ColumnMapping, ImportConfig, import_file
from curvemole.core.initialization import find_peak_suggestions
from curvemole.core.serialization import load_project, save_project
from curvemole.core.uncertainty import UncertaintyAnalyzer


def constant(value=0.):
    return Model(components=[Component.create("constant", initial={"offset": value})])


def fit_constant(curve, model=None, **plan_options):
    model = model or constant()
    fitter = Fitter()
    plan = FitPlan([curve.id], **plan_options)
    result = fitter.fit(plan, [curve], {curve.id: model})
    assert result.success, result.message
    return fitter, plan, model, result


@pytest.mark.parametrize("balance,weight", [(False, 9), (True, 1), (True, 9)])
def test_absolute_error_is_invariant_to_a_common_objective_multiplier(balance, weight):
    curve = Curve("Known noise", np.arange(25.), np.arange(25.), sigma_y=np.full(25, 0.5))
    *_, result = fit_constant(curve, equal_contribution=balance, spectrum_weights={curve.id: weight})
    assert next(iter(result.parameters.values())).standard_error == pytest.approx(0.1)


def test_global_absolute_error_uses_observation_noise_not_balancing_weights():
    curves = [Curve(str(i), np.arange(10.), np.arange(10.) + i, sigma_y=np.full(10, sigma))
              for i, sigma in enumerate((1., 2.))]
    models = {c.id: constant() for c in curves}
    first, second = [next(iter(models[c.id].parameter_map(c.id))) for c in curves]
    models[curves[1].id].parameter_map(curves[1].id)[second].link = "${" + first + "}"
    plan = FitPlan([c.id for c in curves], FitMode.GLOBAL, spectrum_weights={curves[1].id: 2.})
    result = Fitter().fit(plan, curves, models)
    expected = np.sqrt((10 + 10 * .25 * 4) / (10 + 10 * .25 * 2)**2)
    assert result.parameters[first].standard_error == pytest.approx(expected)
    assert result.parameters[second].standard_error == pytest.approx(expected)


@pytest.mark.parametrize("unit", [1., 1e-6, 1e-9, 1e-12])
def test_bounded_unweighted_fit_respects_y_units(unit):
    x = np.arange(25.)
    y = 2 + 0.2 * np.sin(x)
    curve = Curve("Unweighted", x, y * unit)
    model = constant(unit)
    model.components[0].parameters["offset"].set_bounds(0, 10 * unit)
    *_, result = fit_constant(curve, model)
    estimate = next(iter(result.parameters.values()))
    assert estimate.value / unit == pytest.approx(y.mean(), rel=1e-7)
    assert estimate.standard_error / unit == pytest.approx(y.std(ddof=1) / np.sqrt(len(y)))


def test_rank_deficiency_withholds_individual_errors_but_retains_identifiable_link():
    curve = Curve("Offsets", np.arange(25.), np.arange(25.), sigma_y=np.full(25, 0.5))
    a, b, linked = [constant().components[0] for _ in range(3)]
    linked.enabled = False
    model = Model(components=[a, b, linked])
    first, second, total = list(model.parameter_map(curve.id))
    linked.parameters["offset"].link = "${" + first + "}+${" + second + "}"
    # Include the derived sum in the fitted dependency graph, while keeping
    # its zero-signed contribution independent of the objective.
    from curvemole.core.functions import formula_definition
    from curvemole.core.registry import default_registry

    registry = default_registry().copy()
    registry.register(formula_definition("zero_linked", "Zero linked", "0*offset + 0*x"))
    linked.enabled = True
    linked.function_id = "zero_linked"
    result = Fitter(registry).fit_single(curve, model)
    assert result.success
    assert result.covariance is None
    assert result.parameters[first].standard_error is None
    assert result.parameters[second].standard_error is None
    assert result.parameters[total].standard_error == pytest.approx(0.1)


@pytest.mark.parametrize("legacy", [False, True])
def test_replay_rejects_changed_mask_on_rows_with_disabled_errors(legacy):
    curve = Curve("Replay", [0., 1., 2., 3.], [0., 100., 0., 0.], sigma_y=[1., 0., 1., 1.])
    fitter, _, _, baseline = fit_constant(curve, settings=FitSettings(use_data_errors=False))
    if legacy:
        baseline.provenance["schema_version"] = 1
        baseline.provenance["input_hashes"][curve.id] = curve.fit_input_hash(1)
        assert fitter.replay(baseline, [curve]).success
    curve.mask_point(1.)
    with pytest.raises(FitError, match="input data changed"):
        fitter.replay(baseline, [curve])


class CapturingFitter(Fitter):
    def fit(self, plan, curves, models, **kwargs):
        self.rows = next(iter(curves.values())).fit_arrays(use_data_errors=plan.settings.use_data_errors)[3]
        return super().fit(plan, curves, models, **kwargs)


@pytest.mark.parametrize("method", ["parametric_monte_carlo", "residual_bootstrap", "block_bootstrap"])
def test_replicas_reuse_exact_baseline_rows(method):
    curve = Curve("Missing Y", np.arange(6.), [1., 1., np.nan, 1., 1., 1.], sigma_y=np.ones(6))
    curve.mask_point(4.)
    _, plan, model, baseline = fit_constant(curve)
    fitter = CapturingFitter()
    result = getattr(UncertaintyAnalyzer(fitter), method)(baseline, plan, [curve], {curve.id: model}, replicates=2)
    assert result.completed == 2
    np.testing.assert_array_equal(fitter.rows, [0, 1, 3, 5])


def test_stale_model_cannot_be_used_to_resample_or_supply_export_errors():
    curve = Curve("Baseline", np.arange(10.), np.arange(10.), sigma_y=np.ones(10))
    _, plan, model, baseline = fit_constant(curve)
    model.components[0].parameters["offset"].value = 10
    with pytest.raises(FitError, match="model parameters or definition have changed"):
        UncertaintyAnalyzer().residual_bootstrap(baseline, plan, [curve], {curve.id: model}, replicates=2)
    project = Project()
    project.add_curve(curve)
    project.models[curve.id] = model
    row = parameter_dataframe(project, baseline).iloc[0]
    assert row["value"] == 10
    assert row["standard_error"] is None


def test_curve_arithmetic_excludes_masked_operand_and_propagates_interpolation(tmp_path):
    source = Curve("Reference", [0., 1., 2.], [0., 100., 0.], sigma_y=[3., 3., 3.])
    source.mask_point(1.)
    target = Curve("Target", [0., 1., 2.], [5., 5., 5.], sigma_y=[2., 2., 2.])
    apply_curve_operation(target, source, "curve_subtract")
    np.testing.assert_allclose(target.y, [5., 5., 5.])
    np.testing.assert_allclose(target.current_sigma_y, np.sqrt([13., 8.5, 13.]))
    assert target.has_correlated_y_errors
    *_, fitted = fit_constant(target)
    assert fitted.covariance is None and fitted.statistics["AIC"] is None
    project = Project()
    project.add_curve(target)
    restored = load_project(save_project(project, tmp_path / "arithmetic.fitproj")).curves[0]
    np.testing.assert_array_equal(restored.current_sigma_y, target.current_sigma_y)
    assert restored.undo_transformation() and restored.redo_transformation()
    np.testing.assert_array_equal(restored.current_sigma_y, target.current_sigma_y)


def test_linear_extrapolation_extends_the_boundary_segment():
    source = Curve("Reference", [0., 1., 2.], [0., 2., 4.])
    target = Curve("Target", [-1., 0., 3.], [0., 0., 0.])
    apply_curve_operation(target, source, "curve_add", extrapolate=True)
    np.testing.assert_array_equal(target.y, [-2., 0., 6.])


@pytest.mark.parametrize("operation", ["normalize_max", "normalize_area"])
def test_normalization_propagates_denominator_uncertainty(operation):
    x, y = np.arange(3.), np.array([1., 2., 4.])
    errors = np.full(3, 0.2)
    curve = Curve("Normalise", x, y, sigma_y=errors)
    weights = np.array([0., 0., 1.]) if operation == "normalize_max" else np.array([.5, 1., .5])
    scale = y @ weights
    jacobian = np.eye(3) / scale - np.outer(y, weights) / scale**2
    apply_scalar(curve, operation)
    np.testing.assert_allclose(curve.current_sigma_y, np.linalg.norm(jacobian * errors, axis=1))
    assert curve.has_correlated_y_errors


def test_lorentzian_survives_square_underflow():
    width = 1e-170
    model = Model(components=[Component.create("lorentzian", initial={"area": width, "gamma": width})])
    np.testing.assert_allclose(model.evaluate(np.array([-width, 0., width])), np.array([.5, 1., .5]) / np.pi)


def test_malformed_csv_cannot_silently_shift_x_and_y(tmp_path):
    path = tmp_path / "shift.csv"
    path.write_text("x,y\n0,10,100\n1,11,101\n2,12,102\n")
    with pytest.raises(DataValidationError, match="more fields"):
        import_file(path, ColumnMapping(x="x", y=["y"]), ImportConfig(delimiter=",", header=True))


def test_peak_width_initialization_uses_physical_x_units():
    x = np.linspace(-5., 5., 251)
    y = np.exp(-.5 * ((x - .4) / .6)**2)
    normal = find_peak_suggestions(Curve("Normal", x, y), prominence=.1)[0]
    tiny = find_peak_suggestions(Curve("Tiny X", x * 1e-18, y), prominence=.1)[0]
    assert tiny.fwhm / 1e-18 == pytest.approx(normal.fwhm)


def test_asymmetric_monte_carlo_is_centered_at_the_fitted_parameter():
    n = 1200
    curve = Curve("Asymmetric", np.arange(n), np.zeros(n),
                  error_y_minus=np.ones(n), error_y_plus=np.full(n, 3.))
    _, plan, model, baseline = fit_constant(curve)
    result = UncertaintyAnalyzer(CapturingFitter()).parametric_monte_carlo(
        baseline, plan, [curve], {curve.id: model}, replicates=32, seed=6)
    assert result.completed == 32
    assert abs(np.median(result.samples)) < .06
    low, high = next(iter(result.intervals.values()))
    assert low < 0 < high


def test_profile_rejects_global_noise_with_another_arbitrarily_weighted_spectrum():
    curves = [Curve(str(i), np.arange(25.), np.sin(np.arange(25.)) + i) for i in range(2)]
    models = {c.id: constant() for c in curves}
    plan = FitPlan([c.id for c in curves], FitMode.GLOBAL, spectrum_weights={curves[1].id: 100.})
    result = Fitter().fit(plan, curves, models)
    c = curves[0]
    with pytest.raises(FitError, match="Gaussian errors"):
        UncertaintyAnalyzer().profile_parameter(result, c, models[c.id], result.free_parameter_paths[0])


def test_profile_does_not_export_scan_boundaries_as_confidence_limits():
    curve = Curve("Narrow scan", np.arange(25.), np.full(25, 2.), sigma_y=np.ones(25))
    _, _, model, result = fit_constant(curve)
    profile = UncertaintyAnalyzer().profile_parameter(
        result, curve, model, result.free_parameter_paths[0], lower=1.999, upper=2.001)
    assert profile.interval == (None, None)
    assert profile.confidence_regions == [(1.999, 2.001)]
    assert profile.warnings


@pytest.mark.parametrize("solver", ["local", "trf", "nelder_mead"])
def test_affine_equality_limits_restrict_the_solver_source(solver):
    curve = Curve("Constrained optimum", np.arange(25.), np.full(25, 9.))
    a, b = constant(1.).components[0], constant(2.).components[0]
    model = Model(components=[a, b])
    source, target = model.parameter_map(curve.id)
    b.parameters["offset"].link = "2*${" + source + "}"
    b.parameters["offset"].set_bounds(0, 4)
    *_, result = fit_constant(curve, model, settings=FitSettings(solver=solver))
    assert result.parameters[source].value == pytest.approx(2.)
    assert result.parameters[target].value == pytest.approx(4.)


def test_peak_model_rejects_bounds_allowing_nonphysical_widths():
    peak = Component.create("gaussian")
    peak.parameters["sigma"].set_bounds(-2, 2)
    with pytest.raises(DataValidationError, match="intrinsic domain"):
        Model(components=[peak]).validate()


def test_known_noise_yields_covariance_at_zero_residual_degrees_of_freedom():
    curve = Curve("Identified", [0., 1.], [1., 2.], sigma_y=[.2, .2])
    model = Model(components=[Component.create("linear")])
    result = Fitter().fit_single(curve, model)
    assert result.success and result.statistics["degrees_of_freedom"] == 0
    np.testing.assert_allclose(result.covariance, [[.04, -.04], [-.04, .08]])


def test_quick_export_keeps_literal_and_generated_component_names(tmp_path):
    curve = Curve("Fitted", np.arange(4.), np.arange(4.))
    project = Project()
    project.add_curve(curve)
    curve.state = type(curve.state).FITTED
    components = [constant(i).components[0] for i in (1, 2, 3)]
    for i, (component, label) in enumerate(zip(components, ("Peak", "Peak", "Peak (2)"), strict=True), 1):
        component.name = label
        component.parameters["offset"].standard_error = i / 10
    project.models[curve.id] = Model(components=components)
    path = export_function_parameters(project, tmp_path / "out.csv")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        labels, columns, data = list(csv.reader(stream))
    assert len(set(zip(labels, columns, strict=True))) == len(labels)
    assert list(map(float, data[1:])) == [1., .1, 2., .2, 3., .3]
