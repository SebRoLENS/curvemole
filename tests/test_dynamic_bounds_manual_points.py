from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Model, Project
from curvemole.core.parameters import resolve_parameter_values
from curvemole.core.registry import default_registry
from curvemole.gui.main_window import MainWindow
from curvemole.gui.manual_points_live import (
    _apply_manual_point_drag,
    _fit_after_generic_point_drag,
    _fit_after_spline_point_drag,
    _set_stored_points,
    _stored_points,
)


@pytest.mark.parametrize("relation,source_value,tolerance,mode,requested,expected", [
    ("lower", 1, 0, "absolute", -2, 1),
    ("upper", 1, 0, "absolute", 4, 1),
    ("similar", 1, .5, "absolute", 4, 1.5),
    ("similar", 2, 25, "percent", -2, 1.5),
])
def test_generic_drag_fits_within_dynamic_source_bounds_on_every_trial(
    relation, source_value, tolerance, mode, requested, expected, monkeypatch,
):
    registry = default_registry()
    curve = Curve("Manual", [0., 1., 2.], [0., 0., 0.])
    source = Component.create("constant", initial={"offset": source_value})
    target = Component.create("constant", initial={"offset": source_value})
    parameter = target.parameters["offset"]
    parameter.link = f"${{{curve.id}.{source.id}.offset}}"
    parameter.link_relation = relation
    parameter.link_tolerance = tolerance
    parameter.link_tolerance_mode = mode
    model = Model(components=[source, target])
    before = model.to_dict()
    definition = registry.get("constant")
    original = definition.evaluator
    trials = []

    def evaluate(x, values, metadata):
        low, high = parameter.link_bounds(source_value)
        assert low <= values["offset"] <= high
        trials.append(values["offset"])
        return original(x, values, metadata)

    monkeypatch.setattr(definition, "evaluator", evaluate)
    fitted = _fit_after_generic_point_drag(
        target, [(0., requested), (1., requested)], registry=registry,
        parameter_context=model.parameter_map(curve.id), curve_id=curve.id,
    )
    assert trials
    assert np.isclose(fitted.parameters["offset"].value, expected, atol=1e-6)
    assert model.to_dict() == before
    resolve_parameter_values(Model(components=[source, fitted]).parameter_map(curve.id))


def test_generic_drag_updates_same_function_source_and_equality_reference_per_trial(monkeypatch):
    registry = default_registry()
    curve = Curve("Same function", [0., 1., 2.], [0., 0., 0.])
    component = Component.create("linear", initial={"slope": 1, "intercept": 2})
    component.parameters["intercept"].link = f"2 * ${{{curve.id}.{component.id}.slope}}"
    definition = registry.get("linear")
    original = definition.evaluator
    trials = []

    def evaluate(x, values, metadata):
        assert values["intercept"] == 2 * values["slope"]
        trials.append(values["slope"])
        return original(x, values, metadata)

    monkeypatch.setattr(definition, "evaluator", evaluate)
    fitted = _fit_after_generic_point_drag(
        component, [(0., 4.), (1., 6.)], registry=registry,
        parameter_context=Model(components=[component]).parameter_map(curve.id), curve_id=curve.id,
    )
    assert trials
    assert np.isclose(fitted.parameters["slope"].value, 2)
    assert np.isclose(fitted.parameters["intercept"].value, 4)


def test_generic_drag_restricts_active_source_against_other_fixed_bound_targets():
    registry = default_registry()
    curve = Curve("Moving source", [0., 1., 2.], [0., 0., 0.])
    source = Component.create("constant", initial={"offset": 1})
    target = Component.create("constant", initial={"offset": 2})
    target.parameters["offset"].link = f"${{{curve.id}.{source.id}.offset}}"
    target.parameters["offset"].link_relation = "lower"
    model = Model(components=[source, target])
    fitted = _fit_after_generic_point_drag(
        source, [(0., 5.), (1., 5.)], registry=registry,
        parameter_context=model.parameter_map(curve.id), curve_id=curve.id,
    )
    assert np.isclose(fitted.parameters["offset"].value, 2, atol=1e-6)
    assert target.parameters["offset"].value == 2
    assert not target.parameters["offset"].fixed
    resolve_parameter_values(Model(components=[fitted, target]).parameter_map(curve.id))


@pytest.mark.parametrize("relation,source_value,tolerance,mode,requested,expected", [
    ("lower", 1, 0, "absolute", -2, 1),
    ("upper", 1, 0, "absolute", 4, 1),
    ("similar", 1, .5, "absolute", 4, 1.5),
    ("similar", 2, 25, "percent", -2, 1.5),
])
def test_spline_drag_clamps_relational_target_and_records_actual_node_height(
    relation, source_value, tolerance, mode, requested, expected,
):
    registry = default_registry()
    curve = Curve("Spline", [0., 1., 2.], [0., 0., 0.])
    source = Component.create("constant", initial={"offset": source_value})
    spline = Component.create("cubic_spline", metadata={"x_nodes": [0., 1., 2.]},
                              initial={"y0": source_value, "y1": source_value, "y2": source_value})
    parameter = spline.parameters["y1"]
    parameter.link = f"${{{curve.id}.{source.id}.offset}}"
    parameter.link_relation = relation
    parameter.link_tolerance = tolerance
    parameter.link_tolerance_mode = mode
    model = Model(components=[source, spline])
    before = model.to_dict()
    fitted, points = _fit_after_spline_point_drag(
        spline, _stored_points(spline), 1, (1.5, requested), registry=registry,
        parameter_context=model.parameter_map(curve.id), curve_id=curve.id,
    )
    assert fitted.parameters["y1"].value == expected
    assert points[1] == (1.5, expected)
    assert _stored_points(fitted)[1] == (1.5, expected)
    assert model.to_dict() == before
    resolve_parameter_values(Model(components=[source, fitted]).parameter_map(curve.id))


def test_manual_drag_is_validated_before_commit_and_undo_preserves_link_metadata():
    app = QApplication.instance() or QApplication([])
    project = Project()
    curve = Curve("GUI drag", [0., 1., 2.], [3., 3., 3.])
    project.add_curve(curve)
    source = Component.create("constant", initial={"offset": 1})
    target = Component.create("constant", initial={"offset": 2})
    target.parameters["offset"].link = f"${{{curve.id}.{source.id}.offset}}"
    target.parameters["offset"].link_relation = "lower"
    target.parameters["offset"].link_reference_scopes = ["relative"]
    _set_stored_points(target, [(0., 2.), (1., 2.)])
    project.models[curve.id] = Model(components=[source, target])
    window = MainWindow(project)
    before = target.to_dict()
    _apply_manual_point_drag(window, target.id, 0, 0, -20)
    assert target.parameters["offset"].value >= source.parameters["offset"].value
    assert np.isclose(target.parameters["offset"].value, 1, atol=1e-6)
    project.resolved_parameter_values()
    window.undo_stack.undo()
    assert target.to_dict() == before
    window.undo_stack.redo()
    assert target.parameters["offset"].link_relation == "lower"
    assert target.parameters["offset"].link_reference_scopes == ["relative"]
    project.resolved_parameter_values()
    project.dirty = False
    window.close()
    app.processEvents()


def test_infeasible_manual_drag_restores_project_without_adding_an_undo_command(monkeypatch):
    from curvemole.gui import manual_points_live

    app = QApplication.instance() or QApplication([])
    project = Project()
    curve = Curve("Rejected drag", [0., 1., 2.], [3., 3., 3.])
    project.add_curve(curve)
    source = Component.create("constant", initial={"offset": 1})
    target = Component.create("constant", initial={"offset": 2})
    target.parameters["offset"].link = f"${{{curve.id}.{source.id}.offset}}"
    target.parameters["offset"].link_relation = "lower"
    _set_stored_points(target, [(0., 2.), (1., 2.)])
    project.models[curve.id] = Model(components=[source, target])
    window = MainWindow(project)
    before = project.models[curve.id].to_dict()
    errors = []
    monkeypatch.setattr(window, "_show_error", lambda title, error: errors.append(str(error)))

    def invalid_fit(component, *args, **kwargs):
        fitted = Component.from_dict(component.to_dict())
        fitted.parameters["offset"].value = -20
        return fitted

    monkeypatch.setattr(manual_points_live, "_fit_after_generic_point_drag", invalid_fit)
    _apply_manual_point_drag(window, target.id, 0, 0, -20)
    assert errors and "dynamic source bounds" in errors[0]
    assert project.models[curve.id].to_dict() == before
    assert window.undo_stack.count() == 0
    project.resolved_parameter_values()
    project.dirty = False
    window.close()
    app.processEvents()
