from __future__ import annotations

import copy

import numpy as np
import pytest
from scipy.special import ndtri

from curvemole import Component, Curve, Fitter, Model, Project
from curvemole.core.data import Transformation
from curvemole.core.errors import DataValidationError
from curvemole.core.export import wide_dataframe
from curvemole.core.fitting import CancellationToken, FitMode, FitPlan, FitSettings
from curvemole.core.functions import builtin_definitions, formula_definition
from curvemole.core.importers import ColumnMapping, import_file
from curvemole.core.registry import FunctionRegistry
from curvemole.core.sequential_fit import SequentialFitPlan
from curvemole.core.serialization import load_project, save_project
from curvemole.core.spectrum_export import spectrum_export_dataframe
from curvemole.core.uncertainty import UncertaintyAnalyzer, _resample_trial


def constant_problem(count=20, *, confidence=.95):
    curve = Curve("CI data", np.arange(count), np.tile([0., 10.], count // 2),
                  error_y_minus=np.ones(count), error_y_plus=np.full(count, 4.),
                  error_confidence_level=confidence)
    model = Model(components=[Component.create("constant", initial={"offset": 5.})])
    return curve, model


def test_import_keeps_confidence_widths_and_export(tmp_path):
    path = tmp_path / "intervals.csv"
    path.write_text("x,y,upper,lower\n0,4,2,1\n1,6,4,2\n")
    curve = import_file(path, ColumnMapping(x="x", y=["y"], error_y_plus="upper",
                                          error_y_minus="lower", error_confidence_level=.9))[0]
    np.testing.assert_array_equal(curve.current_error_y_minus, [1, 2])
    np.testing.assert_allclose(curve.y_error_scales()[1], np.array([2, 4]) / ndtri(.95))
    frame = wide_dataframe(curve, Model())
    np.testing.assert_array_equal(frame["error_y_plus"], [2, 4])
    np.testing.assert_array_equal(frame["error_confidence_percent"], [90, 90])
    assert curve.metadata["import"]["error_y_plus_column"] == "upper"
    with pytest.raises(ValueError):
        curve.current_error_y_minus[0] = 99


@pytest.mark.parametrize("kwargs", [
    {"error_y_minus": "minus"},
    {"error_y_plus": "plus"},
    {"error_y_minus": "minus", "error_y_plus": "plus", "sigma_y": "sigma"},
    {"error_confidence_level": 1}, {"error_confidence_level": float("nan")},
])
def test_invalid_error_mapping_rejected(kwargs):
    with pytest.raises(DataValidationError):
        ColumnMapping(x="x", y=["y"], **kwargs).validate()


@pytest.mark.parametrize("operation,parameters", [
    ("y_multiply", {"value": -2}), ("y_divide", {"value": -.5}),
    ("custom_formula", {"axis": "y", "formula": "-2*y + 3"}),
    ("column_formula", {"target": "y", "formula": "-2*y + 3"}),
])
def test_transformations_swap_sides_and_undo(operation, parameters):
    curve, _ = constant_problem()
    original_hash = curve.content_hash
    curve.apply_transformation(Transformation(operation, parameters))
    np.testing.assert_allclose(curve.current_error_y_minus, 8, rtol=1e-9)
    np.testing.assert_allclose(curve.current_error_y_plus, 2, rtol=1e-9)
    assert curve.content_hash != original_hash
    assert curve.undo_transformation()
    assert curve.content_hash == original_hash
    np.testing.assert_array_equal(curve.current_error_y_minus, 1)


def test_asymmetric_fit_uses_correct_side_at_each_evaluation():
    curve, model = constant_problem()
    weighted = Fitter().fit_single(curve, model)
    assert weighted.success
    value = next(iter(weighted.parameters.values())).value
    assert value == pytest.approx(160 / 17, rel=1e-6)
    output = weighted.curve_outputs[curve.id]
    scales = np.where(output.fitted >= output.observed, 4., 1.) / ndtri(.975)
    np.testing.assert_allclose(output.weighted_residual, output.residual / scales)
    unweighted = Fitter().fit_single(curve, model, FitSettings(use_data_errors=False))
    assert next(iter(unweighted.parameters.values())).value == pytest.approx(5.)
    np.testing.assert_allclose(unweighted.curve_outputs[curve.id].weighted_residual,
                               unweighted.curve_outputs[curve.id].residual)


@pytest.mark.parametrize("kind", ["sigma", "weight", "inverse_variance"])
def test_ignore_errors_also_ignores_existing_symmetric_weighting(kind):
    kwargs = ({"sigma_y": np.tile([4., 1.], 10)} if kind == "sigma" else
              {"weights": np.tile([.25, 1.], 10),
               "weights_are_inverse_variance": kind == "inverse_variance"})
    curve = Curve("weighted", np.arange(20), np.tile([0., 10.], 10), **kwargs)
    model = Model(components=[Component.create("constant", initial={"offset": 4.})])
    result = Fitter().fit_single(curve, model, FitSettings(use_data_errors=False))
    assert next(iter(result.parameters.values())).value == pytest.approx(5.)


@pytest.mark.parametrize("mode", list(FitMode))
@pytest.mark.parametrize("use_errors", [True, False])
def test_fit_modes_and_workers_keep_weighting_choice(mode, use_errors):
    problems = [constant_problem(), constant_problem()]
    curves = [item[0] for item in problems]
    models = {curve.id: model for curve, model in problems}
    plan = FitPlan([curve.id for curve in curves], mode,
                   FitSettings(workers=2, use_data_errors=use_errors))
    if mode == FitMode.SEQUENTIAL:
        plan = SequentialFitPlan(plan.curve_ids, settings=plan.settings,
                                 monitor_residuals=False, monitor_parameters=False)
    result = Fitter().fit(plan, curves, models)
    assert result.success
    assert len(result.curve_outputs) == 2
    for output in result.curve_outputs.values():
        np.testing.assert_allclose(output.fitted, 160 / 17 if use_errors else 5., rtol=1e-6)


def test_save_load_keeps_errors_confidence_transformations_and_fit_choice(tmp_path):
    curve, model = constant_problem(confidence=.8)
    curve.apply_transformation(Transformation("y_multiply", {"value": -3}))
    project = Project()
    project.add_curve(curve)
    project.models[curve.id] = model
    project.results["last_fit"] = Fitter().fit_single(curve, model, FitSettings(use_data_errors=False))
    path = tmp_path / "errors.fitproj"
    save_project(project, path)
    restored = load_project(path)
    actual = restored.dataset.curve(curve.id)
    assert actual.error_confidence_level == .8
    np.testing.assert_array_equal(actual.error_y_plus, curve.error_y_plus)
    np.testing.assert_array_equal(actual.current_error_y_minus, curve.current_error_y_minus)
    assert not restored.results["last_fit"].settings.use_data_errors
    frame = spectrum_export_dataframe(restored, curve.id)
    np.testing.assert_array_equal(frame["error_y_minus"], actual.current_error_y_minus)
    np.testing.assert_array_equal(frame["error_confidence_percent"], 80.)


@pytest.mark.parametrize("confidence", [.68, .95])
def test_monte_carlo_noise_has_the_declared_asymmetric_central_interval(confidence):
    curve = Curve("many observations", np.arange(100_000), np.ones(100_000),
                  error_y_minus=np.full(100_000, 2.), error_y_plus=np.full(100_000, 5.),
                  error_confidence_level=confidence)
    model = Model(components=[Component.create("constant", initial={"offset": 1.})])
    plan = FitPlan([curve.id])
    fitter = Fitter()
    baseline = fitter.fit(plan, [curve], {curve.id: model})
    captured = {}

    class CapturingFitter:
        registry = fitter.registry

        def fit(self, plan, curves, models, **kwargs):
            captured["noise"] = curves[curve.id].y - 1
            captured["curve"] = curves[curve.id]
            return baseline

    _resample_trial(123, "parametric_monte_carlo", baseline, plan,
                        {curve.id: curve}, {curve.id: model}, {}, CapturingFitter(), CancellationToken())
    lower, upper = np.quantile(captured["noise"], [(1-confidence)/2, (1+confidence)/2])
    assert lower == pytest.approx(-2, rel=.035)
    assert upper == pytest.approx(5, rel=.035)
    assert np.median(captured["noise"]) == pytest.approx(0, abs=.04)
    assert captured["curve"].error_confidence_level == confidence


@pytest.mark.parametrize("method", ["parametric_monte_carlo", "residual_bootstrap", "block_bootstrap"])
def test_asymmetric_resampling_matches_across_workers_and_records_model(method):
    curve, model = constant_problem()
    plan = FitPlan([curve.id], settings=FitSettings(use_data_errors=False))
    analyzer = UncertaintyAnalyzer()
    baseline = analyzer.fitter.fit(plan, [curve], {curve.id: model})
    run = getattr(analyzer, method)
    serial = run(baseline, plan, [curve], {curve.id: model}, replicates=4, seed=42, workers=1)
    parallel = run(baseline, plan, [curve], {curve.id: model}, replicates=4, seed=42, workers=2)
    assert serial.completed == parallel.completed == 4
    np.testing.assert_allclose(serial.samples, parallel.samples, rtol=0, atol=0)
    assert serial.configuration["data_errors"][curve.id]["input_confidence_level"] == .95


def test_error_change_invalidates_content_identity():
    curve, _ = constant_problem()
    other = copy.deepcopy(curve)
    other.error_confidence_level = .9
    assert other.content_hash != curve.content_hash


@pytest.mark.parametrize("method", ["residual_bootstrap", "block_bootstrap"])
def test_bootstrap_preserves_noise_scale_and_excludes_masked_outlier(method):
    widths = np.tile([2., 4., 2., 4.], 5)
    observed = np.tile([-2., 4., 2., -4.], 5)
    curve = Curve("heteroscedastic", np.arange(21), np.r_[observed, 999.],
                  error_y_minus=np.r_[widths, 1.], error_y_plus=np.r_[widths, 1.])
    curve.masks[curve.active_mask].excluded[-1] = True
    model = Model(components=[Component.create("constant")])
    plan = FitPlan([curve.id], settings=FitSettings(use_data_errors=False))
    fitter = Fitter()
    baseline = fitter.fit(plan, [curve], {curve.id: model})
    captured = {}

    class CapturingFitter:
        registry = fitter.registry

        def fit(self, plan, curves, models, **kwargs):
            captured["curve"] = curves[curve.id]
            return baseline

    _resample_trial(123, method, baseline, plan, {curve.id: curve},
                        {curve.id: model}, {curve.id: 3}, CapturingFitter(), CancellationToken())
    actual = captured["curve"]
    np.testing.assert_allclose(np.abs(actual.y[:-1] / widths), 1, atol=1e-9)
    assert actual.y[-1] == pytest.approx(0., abs=1e-9)
    assert actual.effective_mask[-1]


def test_ignore_invalid_error_rows_keeps_explicit_masks_and_ranges():
    curve = Curve("partially missing errors", np.arange(6), np.arange(6),
                  error_y_minus=[1, 0, np.nan, 1, 1, 1], error_y_plus=np.ones(6))
    curve.masks[curve.active_mask].excluded[3] = True
    curve.fit_ranges = [(0, 4)]
    np.testing.assert_array_equal(curve.fit_arrays()[3], [0, 4])
    np.testing.assert_array_equal(curve.fit_arrays(use_data_errors=False)[3], [0, 1, 2, 4])


@pytest.mark.parametrize("use_errors", [True, False])
def test_custom_formula_parallel_fit_keeps_ci_weighting(monkeypatch, use_errors):
    from curvemole.core import fitting
    registry = FunctionRegistry()
    registry.extend(builtin_definitions())
    registry.register(formula_definition("ci_formula", "CI custom formula", "offset + 0*x",
                                         defaults={"offset": 5.}))
    curves = [constant_problem()[0] for _ in range(2)]
    models = {curve.id: Model(components=[Component.create("ci_formula", registry=registry)])
              for curve in curves}
    pools = []
    original = fitting.ProcessPoolExecutor

    def capture_pool(*args, **kwargs):
        pools.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(fitting, "ProcessPoolExecutor", capture_pool)
    result = Fitter(registry).fit(FitPlan([curve.id for curve in curves],
                                         settings=FitSettings(workers=2, use_data_errors=use_errors)),
                                 curves, models)
    assert result.success and len(pools) == 1
    for output in result.curve_outputs.values():
        np.testing.assert_allclose(output.fitted, 160 / 17 if use_errors else 5., rtol=1e-6)
