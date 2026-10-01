from __future__ import annotations

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Model
from curvemole.core.errors import FitError
from curvemole.core.fitting import FitMode, FitPlan
from curvemole.core.parameters import resolve_parameter_values
from curvemole.core.uncertainty import UncertaintyAnalyzer
from curvemole.core.uncertainty_summary import summarize


@pytest.mark.parametrize("relation,source_value,tolerance,mode,limits,failed", [
    ("lower", 1, 0, "absolute", (0, 4), 1),
    ("upper", 3, 0, "absolute", (0, 4), 1),
    ("similar", 2, .5, "absolute", (1, 3), 2),
    ("similar", 2, 25, "percent", (1, 3), 2),
])
def test_profile_dynamic_target_keeps_relation_and_marks_infeasible_points(
    relation, source_value, tolerance, mode, limits, failed, monkeypatch,
):
    curve = Curve("Profile", np.arange(10.), np.full(10, source_value + 2))
    source = Component.create("constant", initial={"offset": source_value})
    source.parameters["offset"].fixed = True
    target = Component.create("constant", initial={"offset": 2})
    parameter = target.parameters["offset"]
    parameter.link = f"${{{curve.id}.{source.id}.offset}}"
    parameter.link_relation = relation
    parameter.link_tolerance = tolerance
    parameter.link_tolerance_mode = mode
    model = Model(components=[source, target])
    fitter = Fitter()
    baseline = fitter.fit_single(curve, model)
    assert baseline.success
    before = model.to_dict()
    observed_values = []
    definition = fitter.registry.get("constant")
    original = definition.evaluator

    def evaluate(x, values, metadata):
        value = values["offset"]
        low, high = parameter.link_bounds(source_value)
        assert low <= value <= high
        observed_values.append(value)
        return original(x, values, metadata)

    monkeypatch.setattr(definition, "evaluator", evaluate)
    result = UncertaintyAnalyzer(fitter).profile_parameter(
        baseline, curve, model, f"{curve.id}.{target.id}.offset",
        lower=limits[0], upper=limits[1], points=5,
    )
    assert result.failed_points == failed
    assert np.count_nonzero(np.isnan(result.delta_chi_square)) == failed
    assert observed_values
    assert model.to_dict() == before


def test_profile_source_with_no_remaining_free_parameters_reports_infeasible_points(monkeypatch):
    curve = Curve("Profile source", np.arange(10.), np.full(10, 1.5))
    source = Component.create("constant", initial={"offset": .5})
    source.parameters["offset"].minimum = 0
    source.parameters["offset"].maximum = 2
    target = Component.create("constant", initial={"offset": 1})
    target.parameters["offset"].fixed = True
    target.parameters["offset"].link = f"${{{curve.id}.{source.id}.offset}}"
    target.parameters["offset"].link_relation = "lower"
    model = Model(components=[source, target])
    fitter = Fitter()
    baseline = fitter.fit_single(curve, model)
    assert baseline.success
    before = model.to_dict()
    evaluated = []
    definition = fitter.registry.get("constant")
    original = definition.evaluator

    def evaluate(x, values, metadata):
        assert 0 <= values["offset"] <= 1
        evaluated.append(values["offset"])
        return original(x, values, metadata)

    monkeypatch.setattr(definition, "evaluator", evaluate)
    result = UncertaintyAnalyzer(fitter).profile_parameter(
        baseline, curve, model, f"{curve.id}.{source.id}.offset",
        lower=0, upper=2, points=5,
    )
    assert result.failed_points == 2
    np.testing.assert_array_equal(np.isnan(result.delta_chi_square), [False, False, False, True, True])
    assert evaluated
    assert model.to_dict() == before


def test_profile_dynamic_target_refits_source_inside_relation_on_every_iteration(monkeypatch):
    curve = Curve("Changing source", np.arange(10.), np.full(10, 3.))
    source = Component.create("constant", initial={"offset": 1})
    source.parameters["offset"].minimum = 0
    source.parameters["offset"].maximum = 10
    target = Component.create("constant", initial={"offset": 2})
    target.parameters["offset"].link = f"${{{curve.id}.{source.id}.offset}}"
    target.parameters["offset"].link_relation = "lower"
    model = Model(components=[source, target])
    fitter = Fitter()
    baseline = fitter.fit_single(curve, model)
    assert baseline.success
    source_path = f"{curve.id}.{source.id}.offset"
    target_path = f"{curve.id}.{target.id}.offset"
    original = Model.evaluate
    source_values = []

    def evaluate(self, x, *, curve_id=None, values=None, registry=None):
        resolved = values or resolve_parameter_values(self.parameter_map(curve_id))
        assert resolved[target_path] >= resolved[source_path]
        source_values.append(resolved[source_path])
        return original(self, x, curve_id=curve_id, values=resolved, registry=registry)

    monkeypatch.setattr(Model, "evaluate", evaluate)
    result = UncertaintyAnalyzer(fitter).profile_parameter(
        baseline, curve, model, target_path, lower=.5, upper=4, points=8,
    )
    assert result.failed_points == 0
    assert np.isfinite(result.delta_chi_square).all()
    assert max(source_values) - min(source_values) > .5


def test_equality_link_remains_unavailable_for_profile_likelihood():
    curve = Curve("Equality", np.arange(10.), np.full(10, 2.))
    source = Component.create("constant", initial={"offset": 1})
    target = Component.create("constant", initial={"offset": 1})
    target.parameters["offset"].link = f"${{{curve.id}.{source.id}.offset}}"
    model = Model(components=[source, target])
    baseline = Fitter().fit_single(curve, model)
    with pytest.raises(FitError, match="equality-linked"):
        UncertaintyAnalyzer().profile_parameter(
            baseline, curve, model, f"{curve.id}.{target.id}.offset", points=5,
        )


@pytest.mark.parametrize("method", ["parametric_monte_carlo", "residual_bootstrap", "block_bootstrap"])
def test_global_resampling_resolves_cross_spectrum_sources_and_keeps_dynamic_bounds(method, monkeypatch):
    x = np.linspace(-5, 5, 101)
    rng = np.random.default_rng(5)
    fitter = Fitter()
    models = {}
    curves = []
    for center in (0, 1):
        component = Component.create("gaussian", initial={"area": 3, "center": center, "sigma": 1})
        for name in ("area", "sigma"):
            component.parameters[name].fixed = True
        y = fitter.registry.get("gaussian").evaluate(
            x, {name: parameter.value for name, parameter in component.parameters.items()}, {},
        ) + rng.normal(0, .01, len(x))
        curve = Curve(f"Spectrum {center}", x, y, sigma_y=np.full(len(x), .01))
        curves.append(curve)
        models[curve.id] = Model(components=[component])
    first, second = curves
    anchor = models[first.id].components[0]
    dependent = models[second.id].components[0]
    source_path = f"{first.id}.{anchor.id}.center"
    target_path = f"{second.id}.{dependent.id}.center"
    dependent.parameters["center"].link = f"${{{source_path}}}"
    dependent.parameters["center"].link_relation = "lower"
    dependent.parameters["center"].link_scope = "absolute"
    plan = FitPlan([curve.id for curve in curves], FitMode.GLOBAL)
    baseline = fitter.fit(plan, curves, models)
    assert baseline.success
    original = Model.evaluate

    def evaluate(self, values_x, *, curve_id=None, values=None, registry=None):
        assert values is not None
        assert values[target_path] >= values[source_path]
        return original(self, values_x, curve_id=curve_id, values=values, registry=registry)

    monkeypatch.setattr(Model, "evaluate", evaluate)
    before = {curve_id: model.to_dict() for curve_id, model in models.items()}
    result = getattr(UncertaintyAnalyzer(fitter), method)(
        baseline, plan, curves, models, replicates=5, seed=123,
    )
    assert result.completed == 5
    assert result.failed == 0
    source_index = result.parameter_paths.index(source_path)
    target_index = result.parameter_paths.index(target_path)
    assert np.all(result.samples[:, target_index] >= result.samples[:, source_index])
    assert {curve_id: model.to_dict() for curve_id, model in models.items()} == before


def test_uncertainty_summary_respects_fixed_dynamic_parameter_metadata():
    from curvemole import Project

    curve = Curve("Fixed bound", np.arange(10.), np.full(10, 1.5))
    source = Component.create("constant", initial={"offset": .5})
    target = Component.create("constant", initial={"offset": 1})
    target.parameters["offset"].fixed = True
    target.parameters["offset"].link = f"${{{curve.id}.{source.id}.offset}}"
    target.parameters["offset"].link_relation = "lower"
    model = Model(components=[source, target])
    project = Project()
    project.add_curve(curve)
    project.models[curve.id] = model
    baseline = Fitter().fit_single(curve, model)
    assert baseline.success
    target_path = f"{curve.id}.{target.id}.offset"
    estimate = baseline.parameters[target_path]
    assert estimate.fixed
    assert estimate.standard_error is None
    row = next(item for item in summarize(project, baseline, {}, "covariance") if item["path"] == target_path)
    assert row["status"] == "Fixed"
    assert "Fixed parameter" in row["reasons"]


@pytest.mark.parametrize("relation", ["equal", "lower", "upper", "similar"])
@pytest.mark.parametrize("curve_index", [0, 1])
def test_linked_global_profile_rejects_source_and_target_before_scanning(relation, curve_index, monkeypatch):
    curves = [Curve(name, np.arange(10.), np.full(10, 2.)) for name in ("First", "Second")]
    models = {curve.id: Model(components=[Component.create("constant", initial={"offset": 2})])
              for curve in curves}
    first, second = curves
    source = models[first.id].components[0]
    target = models[second.id].components[0]
    target.parameters["offset"].link = f"${{{first.id}.{source.id}.offset}}"
    target.parameters["offset"].link_relation = relation
    target.parameters["offset"].link_tolerance = .5 if relation == "similar" else 0
    baseline = Fitter().fit(FitPlan([curve.id for curve in curves], FitMode.GLOBAL), curves, models)
    assert baseline.success
    curve = curves[curve_index]
    model = models[curve.id]
    path = f"{curve.id}.{model.components[0].id}.offset"

    def forbidden(*args, **kwargs):
        pytest.fail("A linked global profile must be rejected before evaluating scan points.")

    monkeypatch.setattr(Model, "evaluate", forbidden)
    with pytest.raises(FitError, match="joint profile.*Monte Carlo or bootstrap"):
        UncertaintyAnalyzer().profile_parameter(baseline, curve, model, path, points=5)


def test_separable_global_profile_remains_available():
    curves = [Curve(name, np.arange(10.), np.full(10, value))
              for name, value in (("First", 1), ("Second", 2))]
    models = {curve.id: Model(components=[Component.create("constant", initial={"offset": 0})])
              for curve in curves}
    fitter = Fitter()
    baseline = fitter.fit(FitPlan([curve.id for curve in curves], FitMode.GLOBAL), curves, models)
    assert baseline.success
    curve = curves[0]
    model = models[curve.id]
    path = f"{curve.id}.{model.components[0].id}.offset"
    result = UncertaintyAnalyzer(fitter).profile_parameter(
        baseline, curve, model, path, lower=0, upper=2, points=5,
    )
    assert result.failed_points == 0
    assert np.isfinite(result.delta_chi_square).all()
