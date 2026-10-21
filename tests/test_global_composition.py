from itertools import permutations

import numpy as np
import pytest
from scipy.signal import fftconvolve

from curvemole import Component, Curve, Fitter, Project
from curvemole.core.errors import DataValidationError
from curvemole.core.models import Model
from curvemole.core.serialization import load_project, save_project


def constant(value, operator="add"):
    return Component.create("constant", initial={"offset": value}, operator=operator)


def test_global_roles_ignore_insertion_and_display_order():
    functions = [constant(2), constant(3), constant(4, "multiply"), constant(2, "divide")]
    for order in permutations(functions):
        model = Model(components=list(order), display_order=[c.id for c in reversed(order)])
        np.testing.assert_allclose(model.evaluate(np.arange(5.)), 10.)
        model.validate_composition()


def test_subtraction_applies_to_global_sum_even_when_factor_was_added_first():
    model = Model(components=[constant(3, "multiply"), constant(5), constant(2, "subtract")])
    np.testing.assert_allclose(model.evaluate(np.arange(5.)), 9.)
    model.components.reverse()
    np.testing.assert_allclose(model.evaluate(np.arange(5.)), 9.)


def model_with_kernel():
    peak = Component.create("gaussian", name="Peak", initial={"center": 1, "sigma": .5})
    factor = Component.create("linear", name="Factor", initial={"slope": .4, "intercept": 3}, operator="multiply")
    kernel = Component.create("gaussian", name="Kernel", initial={"sigma": .8}, operator="convolve")
    return Model(components=[kernel, factor, peak]), peak, factor, kernel


def test_user_operation_order_changes_noncommuting_calculation():
    x = np.linspace(-5, 5, 501)
    model, peak, factor, kernel = model_with_kernel()
    arrays = {c.id: Model(components=[Component.create(c.function_id, initial={n: p.value for n, p in c.parameters.items()})]).evaluate(x)
              for c in model.components}
    model.operation_order = [factor.id, kernel.id]
    first = model.evaluate(x)
    np.testing.assert_allclose(first, fftconvolve(arrays[peak.id] * arrays[factor.id], arrays[kernel.id], mode="same") * .02,
                               atol=1e-13)
    model.operation_order = [kernel.id, factor.id]
    second = model.evaluate(x)
    np.testing.assert_allclose(second, fftconvolve(arrays[peak.id], arrays[kernel.id], mode="same") * .02 * arrays[factor.id],
                               atol=1e-13)
    assert not np.allclose(first, second)
    model.components.reverse()
    np.testing.assert_allclose(model.evaluate(x), second)
    assert model.calculation_expression() == "(convolve(Peak, Kernel)) × Factor"


def test_consecutive_convolutions_do_not_depend_on_intermediate_cropping():
    x = np.linspace(-1, 1, 100)
    functions = [Component.create("gaussian", initial={"center": center, "sigma": .5}, operator="convolve")
                 for center in (-.3, .2, .6)]
    reference = None
    for order in permutations(functions):
        model = Model(components=list(order))
        actual = model.evaluate(x)
        if reference is None:
            reference = actual
        np.testing.assert_allclose(actual, reference, atol=1e-13)


@pytest.mark.parametrize("operator,expected", [("add", 2.), ("subtract", -2.), ("multiply", 2.), ("divide", .5), ("convolve", 2.)])
def test_a_single_function_does_not_need_an_insertion_predecessor(operator, expected):
    model = Model(components=[constant(2, operator)])
    np.testing.assert_allclose(model.evaluate(np.arange(5.)), expected)
    model.validate_composition()


def test_old_models_preserve_ordered_evaluation_and_can_explicitly_switch():
    original = Model(components=[constant(2), constant(4, "multiply"), constant(3)])
    old = original.to_dict()
    old.pop("composition_mode")
    old.pop("operation_order")
    legacy = Model.from_dict(old)
    assert legacy.composition_mode == "ordered"
    np.testing.assert_allclose(legacy.evaluate(np.arange(3.)), 11.)
    legacy.composition_mode = "global"
    np.testing.assert_allclose(legacy.evaluate(np.arange(3.)), 20.)
    legacy.composition_mode = "ordered"
    with pytest.raises(DataValidationError):
        legacy.set_component_operator(legacy.components[0].id, "multiply")
    assert legacy.components[0].operator == "add"


def test_mode_and_explicit_order_survive_project_round_trip(tmp_path):
    project = Project()
    x = np.linspace(-5, 5, 501)
    curve = Curve("Measured", x, np.ones_like(x))
    project.add_curve(curve)
    model, _, factor, kernel = model_with_kernel()
    model.operation_order = [kernel.id, factor.id]
    project.models[curve.id] = model
    expected = model.evaluate(x)
    loaded = load_project(save_project(project, tmp_path / "global.fitproj"))
    restored = loaded.model_for(curve.id)
    assert restored.composition_mode == "global"
    assert restored.operation_order == [kernel.id, factor.id]
    np.testing.assert_allclose(restored.evaluate(x), expected)


def test_fitting_uses_global_roles_when_multiplier_precedes_peak():
    x = np.linspace(-4, 4, 201)
    factor = constant(2, "multiply")
    factor.parameters["offset"].fixed = True
    peak = Component.create("gaussian", initial={"area": 3, "center": .4, "sigma": .7})
    model = Model(components=[factor, peak])
    curve = Curve("Fit", x, model.evaluate(x))
    peak.parameters["area"].value = 1.
    result = Fitter().fit_single(curve, model)
    assert result.success
    assert model.component(peak.id).parameters["area"].value == pytest.approx(3., rel=1e-5)


def test_global_background_includes_the_same_factors_as_the_full_model():
    background = constant(2.)
    background.is_background = True
    signal = constant(3.)
    multiplier = constant(4., 'multiply')
    model = Model(components=[multiplier, background, signal])
    x = np.arange(5.)
    np.testing.assert_allclose(model.evaluate(x), 20.)
    np.testing.assert_allclose(model.background(x), 8.)
    background.enabled = False
    np.testing.assert_allclose(model.evaluate(x), 12.)


def test_fitmodel_preserves_global_mode_and_order(tmp_path):
    from curvemole.core.serialization import load_fitmodel, save_fitmodel
    model, _, factor, kernel = model_with_kernel()
    model.operation_order = [kernel.id, factor.id]
    restored, _ = load_fitmodel(save_fitmodel(model, tmp_path / 'global.fitmodel'))
    assert restored.to_dict() == model.to_dict()
    x = np.linspace(-4, 4, 201)
    np.testing.assert_allclose(restored.evaluate(x), model.evaluate(x))


def test_workflow_preserves_global_mode_and_explicit_operation_order(tmp_path):
    from curvemole.core.workflow import dump_workflow, run_workflow
    project = Project()
    path = tmp_path / 'spectrum.csv'
    x = np.linspace(-4, 4, 201)
    np.savetxt(path, np.column_stack([x, np.ones_like(x)]))
    curve = Curve('Measured', x, np.ones_like(x), source=str(path))
    project.add_curve(curve)
    model, _, factor, kernel = model_with_kernel()
    model.operation_order = [kernel.id, factor.id]
    project.models[curve.id] = model
    outcome = run_workflow(dump_workflow(project, tmp_path / 'global.yaml'))
    restored = outcome.project.model_for(outcome.project.curves[0].id)
    assert restored.composition_mode == 'global'
    assert restored.operation_order == model.operation_order
    np.testing.assert_allclose(restored.evaluate(x), model.evaluate(x))


def test_moving_display_rows_does_not_remove_explicit_calculation_order():
    model, _, factor, kernel = model_with_kernel()
    model.operation_order = [kernel.id, factor.id]
    x = np.linspace(-4, 4, 201)
    before = model.evaluate(x)
    model.move(kernel.id, 2)
    assert model.operation_order == [kernel.id, factor.id]
    np.testing.assert_allclose(model.evaluate(x), before)
    model.delete_components({kernel.id})
    assert model.operation_order == [factor.id]
