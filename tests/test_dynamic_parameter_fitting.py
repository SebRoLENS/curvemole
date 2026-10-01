from __future__ import annotations

import math

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Model
from curvemole.core.dynamic_bounds import DynamicParameterCoordinates
from curvemole.core.errors import ConstraintError
from curvemole.core.fitting import FitMode, FitPlan, FitResult, FitSettings
from curvemole.core.functions import FunctionDefinition, ParameterSpec
from curvemole.core.parameters import Parameter
from curvemole.core.registry import FunctionRegistry


def _line_problem(relation, *, tolerance=0.5, tolerance_mode="absolute", truth=(1.0, 2.0)):
    evaluated = []

    def evaluate(x, values, metadata):
        source, target = values["a"], values["b"]
        delta = tolerance if tolerance_mode == "absolute" else abs(source) * tolerance / 100
        if relation == "lower":
            assert target >= source
        elif relation == "upper":
            assert target <= source
        else:
            assert source - delta <= target <= source + delta
        evaluated.append((source, target))
        return source + target * x

    registry = FunctionRegistry()
    registry.register(FunctionDefinition(
        "test_line", "Test line", "generic", evaluate,
        (ParameterSpec("a", 1.3, -5., 5.), ParameterSpec("b", 0.9, -5., 5.)),
    ))
    component = Component.create("test_line", registry=registry)
    model = Model(components=[component])
    x = np.linspace(-1, 1, 81)
    curve = Curve("line", x, truth[0] + truth[1] * x)
    source_path = model.parameter_path(curve.id, component.id, "a")
    target = component.parameters["b"]
    target.link = f"${{{source_path}}}"
    target.link_relation = relation
    target.link_tolerance = tolerance
    target.link_tolerance_mode = tolerance_mode
    return registry, model, curve, component, evaluated


@pytest.mark.parametrize("solver", ["local", "trf", "dogbox", "lbfgsb", "powell", "nelder_mead", "differential_evolution"])
@pytest.mark.parametrize("relation,truth", [("lower", (1., 2.)), ("upper", (2., 1.))])
def test_bound_relation_is_feasible_during_every_model_evaluation(solver, relation, truth):
    registry, model, curve, component, evaluated = _line_problem(relation, truth=truth)
    result = Fitter(registry).fit_single(curve, model, FitSettings(
        solver=solver, max_nfev=2500, de_maxiter=15, de_popsize=6,
    ))
    assert result.success, result.message
    assert evaluated
    assert component.parameters["a"].value == pytest.approx(truth[0], abs=2e-3)
    assert component.parameters["b"].value == pytest.approx(truth[1], abs=2e-3)
    assert len(result.free_parameter_paths) == 2


@pytest.mark.parametrize("tolerance_mode,tolerance,truth", [
    ("absolute", 2., (3., 4.)),
    ("percent", 20., (3., 3.4)),
    ("percent", 20., (-3., -3.4)),
])
def test_similar_relation_follows_a_changing_source(tolerance_mode, tolerance, truth):
    registry, model, curve, component, evaluated = _line_problem(
        "similar", tolerance=tolerance, tolerance_mode=tolerance_mode, truth=truth,
    )
    result = Fitter(registry).fit_single(curve, model)
    assert result.success, result.message
    assert evaluated
    assert len({round(source, 5) for source, _ in evaluated}) > 1
    assert component.parameters["a"].value == pytest.approx(truth[0], abs=1e-5)
    assert component.parameters["b"].value == pytest.approx(truth[1], abs=1e-5)


@pytest.mark.parametrize("relation", ["lower", "upper", "similar"])
def test_dynamic_and_static_bounds_intersect_at_every_trial(relation):
    truth = (1., 1.2) if relation != "upper" else (1.2, 1.)
    registry, model, curve, component, evaluated = _line_problem(relation, truth=truth)
    source, target = component.parameters["a"], component.parameters["b"]
    source.minimum, source.maximum = -10., 10.
    target.minimum, target.maximum = 0.5, 1.5
    source.value = 8. if relation != "upper" else -8.
    target.value = 1.
    result = Fitter(registry).fit_single(curve, model)
    assert result.success, result.message
    assert evaluated
    assert all(target.minimum <= value <= target.maximum for _, value in evaluated)
    assert source.minimum == -10. and source.maximum == 10.
    assert target.minimum == 0.5 and target.maximum == 1.5
    assert source.value == pytest.approx(truth[0], abs=1e-5)
    assert target.value == pytest.approx(truth[1], abs=1e-5)


def test_backward_bounds_propagate_through_a_dependency_chain():
    parameters = {
        "c.f.a": Parameter("a", 2., minimum=0., maximum=10.),
        "c.f.b": Parameter("b", 3., link="${c.f.a}", link_relation="lower"),
        "c.f.c": Parameter("c", 4., maximum=5., link="${c.f.b}", link_relation="lower"),
    }
    coordinates = DynamicParameterCoordinates(parameters, list(parameters))
    assert coordinates.domains["c.f.a"] == (0., 5.)
    assert coordinates.domains["c.f.b"] == (0., 5.)
    rng = np.random.default_rng(13)
    for vector in rng.uniform(0., 1., size=(100, 3)):
        vector[0] *= 5.
        values = coordinates.decode(vector)
        assert 0. <= values["c.f.a"] <= values["c.f.b"] <= values["c.f.c"] <= 5.


@pytest.mark.parametrize("source_bounds,target_bounds,expected", [
    ((-10., 10.), (4., 6.), (4. / 1.2, 6. / 0.8)),
    ((-10., 10.), (-6., -4.), (-6. / 0.8, -4. / 1.2)),
    ((-10., 10.), (-2., 2.), (-2. / 0.8, 2. / 0.8)),
])
def test_percent_backward_domain_handles_both_signs(source_bounds, target_bounds, expected):
    source = Parameter("source", 0., minimum=source_bounds[0], maximum=source_bounds[1])
    target = Parameter("target", sum(target_bounds) / 2, minimum=target_bounds[0], maximum=target_bounds[1],
                       link="${c.f.source}", link_relation="similar", link_tolerance=20.,
                       link_tolerance_mode="percent")
    coordinates = DynamicParameterCoordinates({"c.f.source": source, "c.f.target": target},
                                              ["c.f.source", "c.f.target"])
    assert coordinates.domains["c.f.source"] == pytest.approx(expected)
    for s in np.linspace(*expected, 7):
        for fraction in (0., .25, .75, 1.):
            values = coordinates.decode(np.asarray([s, fraction]))
            delta = abs(s) * .2
            assert target.minimum <= values["c.f.target"] <= target.maximum
            assert s - delta <= values["c.f.target"] <= s + delta


def test_impossible_bounds_fail_before_model_evaluation_and_restore_values():
    registry, model, curve, component, evaluated = _line_problem("lower")
    source, target = component.parameters["a"], component.parameters["b"]
    source.minimum, source.maximum, source.value = 2., 3., 2.5
    target.minimum, target.maximum, target.value = 0., 1., .5
    result = Fitter(registry).fit_single(curve, model)
    assert not result.success
    assert not evaluated
    assert source.value == 2.5 and target.value == .5
    assert any("no feasible intersection" in warning for warning in result.warnings)


def test_cycles_including_dynamic_bounds_are_rejected():
    parameters = {
        "c.f.a": Parameter("a", 1., link="${c.f.b}", link_relation="lower"),
        "c.f.b": Parameter("b", 1., link="${c.f.a}", link_relation="upper"),
    }
    with pytest.raises(ConstraintError, match="cycle"):
        DynamicParameterCoordinates(parameters, list(parameters))


def test_latent_covariance_is_converted_to_physical_parameters():
    registry, model, curve, component, _ = _line_problem(
        "similar", tolerance=2., truth=(3., 4.),
    )
    x = curve.original_x
    curve = Curve(curve.name, x, curve.original_y + .02 * np.sin(13 * x), id=curve.id)
    result = Fitter(registry).fit_single(curve, model)
    assert result.success, result.message
    design = np.column_stack([np.ones_like(x), x])
    residual = result.curve_outputs[curve.id].residual
    expected = np.linalg.inv(design.T @ design) * np.dot(residual, residual) / (len(x) - 2)
    assert result.covariance == pytest.approx(expected, rel=2e-5, abs=1e-12)
    for index, path in enumerate(result.free_parameter_paths):
        assert result.parameters[path].standard_error ** 2 == pytest.approx(expected[index, index], rel=2e-5)
    source, target = component.parameters["a"], component.parameters["b"]
    target_path = model.parameter_path(curve.id, component.id, "b")
    assert result.parameters[target_path].minimum == pytest.approx(source.value - 2.)
    assert result.parameters[target_path].maximum == pytest.approx(source.value + 2.)
    assert target.minimum == -5. and target.maximum == 5.


def test_global_dynamic_relation_keeps_source_and_target_free():
    x = np.linspace(-1., 1., 61)
    curves = [Curve("first", x, 1. + .7 * x), Curve("second", x, 3. + 2. * x)]
    registry = FunctionRegistry()
    registry.register(FunctionDefinition(
        "line", "Line", "generic", lambda x, p, _: p["a"] + p["b"] * x,
        (ParameterSpec("a", .5), ParameterSpec("b", .5)),
    ))
    models = {curve.id: Model(components=[Component.create("line", registry=registry)]) for curve in curves}
    source = models[curves[0].id].components[0]
    target = models[curves[1].id].components[0]
    source_path = models[curves[0].id].parameter_path(curves[0].id, source.id, "a")
    target.parameters["b"].link = f"${{{source_path}}}"
    target.parameters["b"].link_relation = "lower"
    result = Fitter(registry).fit(FitPlan([curve.id for curve in curves], FitMode.GLOBAL), curves, models)
    assert result.success, result.message
    assert len(result.free_parameter_paths) == 4
    assert source.parameters["a"].value == pytest.approx(1.)
    assert target.parameters["b"].value == pytest.approx(2.)


@pytest.mark.parametrize("relation,kind", [("lower", "lower_gap"), ("upper", "upper_gap")])
def test_one_sided_unbounded_relation_uses_nonnegative_gap(relation, kind):
    parameters = {
        "c.f.a": Parameter("a", 1.),
        "c.f.b": Parameter("b", 1., link="${c.f.a}", link_relation=relation),
    }
    coordinates = DynamicParameterCoordinates(parameters, list(parameters))
    assert coordinates.coordinate_kinds["c.f.b"] == kind
    for source in (-100., 0., 100.):
        for gap in (0., .3, 1000.):
            physical = coordinates.decode(np.asarray([source, gap]))
            expected = source + gap if relation == "lower" else source - gap
            assert physical["c.f.b"] == expected
            assert coordinates.encode(np.asarray([source, expected])) == pytest.approx([source, gap])


def test_percent_relation_at_zero_is_feasible_for_every_fraction():
    parameters = {
        "c.f.a": Parameter("a", 0., minimum=-1., maximum=1.),
        "c.f.b": Parameter("b", .5, link="${c.f.a}", link_relation="similar",
                           link_tolerance=25., link_tolerance_mode="percent"),
    }
    coordinates = DynamicParameterCoordinates(parameters, list(parameters))
    assert coordinates.initial() == pytest.approx([0., .5])
    for fraction in (0., .2, .8, 1.):
        values = coordinates.decode(np.asarray([0., fraction]))
        assert values == {"c.f.a": 0., "c.f.b": 0.}


def test_fixed_target_restricts_source_without_adding_a_fitting_coordinate():
    parameters = {
        "c.f.a": Parameter("a", 2., minimum=-5., maximum=5.),
        "c.f.b": Parameter("b", 1., fixed=True, link="${c.f.a}", link_relation="lower"),
    }
    coordinates = DynamicParameterCoordinates(parameters, ["c.f.a"])
    assert coordinates.bounds[1] == pytest.approx([1.])
    assert coordinates.initial() == pytest.approx([1.])
    assert coordinates.decode(np.asarray([.5])) == {"c.f.a": .5, "c.f.b": 1.}


def test_equal_expression_source_is_resolved_before_the_bound_target():
    parameters = {
        "c.f.a": Parameter("a", 1.),
        "c.f.b": Parameter("b", 2., link="2 * ${c.f.a}"),
        "c.f.c": Parameter("c", 3., link="${c.f.b}", link_relation="lower"),
    }
    coordinates = DynamicParameterCoordinates(parameters, ["c.f.a", "c.f.c"])
    assert coordinates.decode(np.asarray([4., 1.])) == {"c.f.a": 4., "c.f.b": 8., "c.f.c": 9.}
    parameters["c.f.c"].maximum = 5.
    coordinates = DynamicParameterCoordinates(parameters, ["c.f.a", "c.f.c"])
    with pytest.raises(ConstraintError, match="advanced equality expression"):
        coordinates.decode(np.asarray([4., .5]))


def test_nelder_mead_explicit_simplex_keeps_physical_parameter_meaning():
    registry, model, curve, component, _ = _line_problem("lower")
    result = Fitter(registry).fit_single(curve, model, FitSettings(
        solver="nelder_mead", nm_initial_simplex=[[1., 1.5], [1.2, 1.5], [1., 1.8]],
    ))
    assert result.success, result.message
    assert component.parameters["a"].value == pytest.approx(1., abs=1e-3)
    assert component.parameters["b"].value == pytest.approx(2., abs=1e-3)


def test_percent_inverse_endpoints_stay_feasible_despite_float_roundoff():
    rng = np.random.default_rng(17)
    for _ in range(100):
        a, b = sorted(rng.uniform(-100., 100., size=2))
        tolerance = rng.uniform(.1, 95.)
        parameters = {
            "c.f.a": Parameter("a", 0.),
            "c.f.b": Parameter("b", (a + b) / 2, minimum=a, maximum=b,
                               link="${c.f.a}", link_relation="similar",
                               link_tolerance=tolerance, link_tolerance_mode="percent"),
        }
        coordinates = DynamicParameterCoordinates(parameters, list(parameters))
        for source in coordinates.domains["c.f.a"]:
            for fraction in (0., .23, .72, 1.):
                values = coordinates.decode(np.asarray([source, fraction]))
                delta = tolerance * (abs(source) / 100)
                assert a <= values["c.f.b"] <= b
                assert source - delta <= values["c.f.b"] <= source + delta


def test_fixed_dynamic_fit_reports_no_false_uncertainty_and_persists_relation_metadata():
    registry, model, curve, component, evaluated = _line_problem("lower", truth=(.5, 1.))
    target = component.parameters["b"]
    target.value, target.fixed = 1., True
    result = Fitter(registry).fit_single(curve, model)
    assert result.success, result.message
    assert evaluated
    assert len(result.free_parameter_paths) == 1
    target_path = model.parameter_path(curve.id, component.id, "b")
    estimate = result.parameters[target_path]
    assert estimate.value == 1.
    assert estimate.standard_error is None
    assert estimate.ci_low is None and estimate.ci_high is None
    assert not estimate.at_bound
    assert estimate.fixed and estimate.link_relation == "lower"
    restored = FitResult.from_dict(result.to_dict(arrays=True))
    assert restored.parameters[target_path].fixed
    assert restored.parameters[target_path].link_relation == "lower"


def test_collapsed_static_range_requires_explicitly_fixing_the_parameter():
    parameters = {
        "c.f.a": Parameter("a", 0.),
        "c.f.b": Parameter("b", 1., minimum=1., maximum=1.,
                           link="${c.f.a}", link_relation="lower"),
    }
    with pytest.raises(ConstraintError, match="fix the parameter explicitly"):
        DynamicParameterCoordinates(parameters, list(parameters))


@pytest.mark.parametrize("relation,source,target_limits", [
    ("similar", 0., (-math.inf, math.inf)),
    ("lower", 1., (-math.inf, 1.)),
    ("upper", 1., (1., math.inf)),
])
def test_rigid_dynamic_interval_requires_explicit_fix_before_model_evaluation(relation, source, target_limits):
    registry, model, curve, component, evaluated = _line_problem(
        relation, tolerance_mode="percent", tolerance=20., truth=(source, source),
    )
    component.parameters["a"].value = source
    component.parameters["a"].fixed = True
    target = component.parameters["b"]
    target.value = source
    target.minimum, target.maximum = target_limits
    result = Fitter(registry).fit_single(curve, model)
    assert not result.success
    assert not evaluated
    assert any("fix the parameter explicitly" in warning for warning in result.warnings)


def test_fixed_dependency_of_equality_source_also_identifies_rigid_percent_interval():
    parameters = {
        "c.f.a": Parameter("a", 2., fixed=True),
        "c.f.b": Parameter("b", 0., link="${c.f.a} - 2"),
        "c.f.c": Parameter("c", 1., link="${c.f.b}", link_relation="similar",
                           link_tolerance=20., link_tolerance_mode="percent"),
    }
    with pytest.raises(ConstraintError, match="fix the parameter explicitly"):
        DynamicParameterCoordinates(parameters, ["c.f.c"])


def test_marginal_confidence_interval_follows_uncertain_source_beyond_its_current_bounds():
    tolerance = 1e-4
    registry, model, curve, component, _ = _line_problem(
        "similar", tolerance=tolerance, truth=(1., 1.),
    )
    x = curve.original_x
    # Even noise with zero mean is orthogonal to both linear coefficients,
    # so the optimum is inside the tight relationship instead of at a bound.
    noise = .05 * np.cos(13 * x)
    noise -= noise.mean()
    curve = Curve(curve.name, x, curve.original_y + noise, id=curve.id)
    result = Fitter(registry).fit_single(curve, model)
    assert result.success, result.message
    source_path = model.parameter_path(curve.id, component.id, "a")
    target_path = model.parameter_path(curve.id, component.id, "b")
    source, target = result.parameters[source_path], result.parameters[target_path]
    assert source.standard_error > 10 * tolerance
    assert target.standard_error > 10 * tolerance
    assert target.minimum == pytest.approx(source.value - tolerance)
    assert target.maximum == pytest.approx(source.value + tolerance)
    assert not target.at_bound
    assert target.ci_low < target.minimum
    assert target.ci_high > target.maximum
    assert target.ci_high - target.ci_low > 40 * tolerance
    assert target.global_minimum == -5. and target.global_maximum == 5.
    assert target.ci_low == pytest.approx(target.value - 1.959963984540054 * target.standard_error)
    assert target.ci_high == pytest.approx(target.value + 1.959963984540054 * target.standard_error)
    restored = FitResult.from_dict(result.to_dict(arrays=True)).parameters[target_path]
    assert restored.global_minimum == target.global_minimum
    assert restored.global_maximum == target.global_maximum
    assert restored.ci_low == target.ci_low and restored.ci_high == target.ci_high
