from __future__ import annotations

import math

import pytest

from curvemole import Component, Curve, Project
from curvemole.core.errors import ConstraintError
from curvemole.core.parameters import Parameter, resolve_parameter_values
from curvemole.core.sequential_fit import _clone_model_for_target
from curvemole.core.serialization import load_project, save_project
from curvemole.core.workflow import dump_workflow, load_workflow, run_workflow


def _bound(relation, value=10, **kwargs):
    return Parameter("center", value, link="${source.peak.center}", link_relation=relation, **kwargs)


@pytest.mark.parametrize("relation,status", [
    ("equal", "linked"), ("lower", "lower-linked"), ("upper", "upper-linked"),
    ("similar", "similar-linked"),
])
def test_relation_controls_free_state_without_replacing_fixed_state(relation, status):
    parameter = _bound(relation, link_tolerance=1)
    assert parameter.status == status
    assert parameter.is_free is (relation != "equal")
    parameter.fixed = True
    assert not parameter.is_free
    assert parameter.status == status


@pytest.mark.parametrize("relation,kwargs,expected", [
    ("lower", {}, (10, 12)),
    ("upper", {}, (8, 10)),
    ("similar", {"link_tolerance": 1}, (9, 11)),
    ("similar", {"link_tolerance": 15, "link_tolerance_mode": "percent"}, (8.5, 11.5)),
    ("equal", {}, (10, 10)),
])
def test_link_bounds_intersect_current_source_and_static_limits(relation, kwargs, expected):
    parameter = _bound(relation, minimum=8, maximum=12, **kwargs)
    assert parameter.link_bounds(10) == expected
    assert parameter.link_bounds(9) != expected


def test_percentage_neighborhood_uses_source_magnitude_including_negative_and_zero():
    negative = _bound("similar", -10, link_tolerance=10, link_tolerance_mode="percent")
    assert negative.link_bounds(-10) == (-11, -9)
    zero = _bound("similar", 0, link_tolerance=10, link_tolerance_mode="percent")
    assert zero.link_bounds(0) == (0, 0)


@pytest.mark.parametrize("relation,source", [("lower", 13), ("upper", 7), ("similar", 15)])
def test_empty_static_and_dynamic_intersection_is_reported(relation, source):
    parameter = _bound(relation, minimum=8, maximum=12, link_tolerance=1)
    with pytest.raises(ConstraintError, match="empty intersection"):
        parameter.link_bounds(source)


@pytest.mark.parametrize("source", [math.inf, -math.inf, math.nan])
def test_bound_link_source_must_be_finite(source):
    with pytest.raises(ConstraintError, match="source must be finite"):
        _bound("lower").link_bounds(source)


@pytest.mark.parametrize("kwargs,message", [
    ({"link_relation": "other"}, "Unknown parameter link relation"),
    ({"link_tolerance_mode": "other"}, "Unknown parameter link tolerance mode"),
    ({"link_tolerance": -1}, "finite and nonnegative"),
    ({"link_tolerance": math.inf}, "finite and nonnegative"),
    ({"link_tolerance": math.nan}, "finite and nonnegative"),
    ({"link_relation": "similar", "link_tolerance": 0}, "positive tolerance"),
    ({"link_relation": "similar", "link_tolerance": 100, "link_tolerance_mode": "percent"}, "less than 100"),
])
def test_invalid_relation_metadata_is_rejected(kwargs, message):
    with pytest.raises(ConstraintError, match=message):
        Parameter("center", 1, link="${source.peak.center}", **kwargs)


@pytest.mark.parametrize("expression", [
    "2 * ${source.peak.center}", "${source.peak.center} + ${source.peak.center}", "1", "(${source.peak.center})",
])
def test_dynamic_relations_require_one_direct_source_reference(expression):
    with pytest.raises(ConstraintError, match="reference one source parameter directly"):
        Parameter("center", 1, link=expression, link_relation="lower")
    assert Parameter("center", 1, link=expression).link == expression


@pytest.mark.parametrize("relation,value,tolerance", [
    ("lower", 12, 0), ("upper", 8, 0), ("similar", 10.5, 1),
])
@pytest.mark.parametrize("fixed", [False, True])
def test_resolve_retains_dynamic_target_value_and_tracks_moving_source(relation, value, tolerance, fixed):
    source = Parameter("center", 10)
    target = _bound(relation, value, link_tolerance=tolerance, fixed=fixed)
    parameters = {"source.peak.center": source, "target.peak.center": target}
    assert resolve_parameter_values(parameters)["target.peak.center"] == value
    source.value = {"lower": 13, "upper": 7, "similar": 12}[relation]
    with pytest.raises(ConstraintError, match="dynamic source bounds"):
        resolve_parameter_values(parameters)


def test_dynamic_sources_resolve_equality_dependencies_and_detect_cycles():
    parameters = {
        "a.peak.center": Parameter("center", 5),
        "b.peak.center": Parameter("center", 10, link="2 * ${a.peak.center}"),
        "c.peak.center": Parameter("center", 11, link="${b.peak.center}", link_relation="lower"),
    }
    assert resolve_parameter_values(parameters) == {
        "a.peak.center": 5, "b.peak.center": 10, "c.peak.center": 11,
    }
    parameters["a.peak.center"].link = "${c.peak.center}"
    with pytest.raises(ConstraintError, match="cycle"):
        resolve_parameter_values(parameters)


def test_legacy_serialization_defaults_to_exact_equality():
    parameter = Parameter.from_dict({"name": "center", "value": 1, "link": "${source.peak.center}"})
    assert parameter.link_relation == "equal"
    assert parameter.link_tolerance == 0
    assert parameter.link_tolerance_mode == "absolute"
    assert not parameter.is_free


def _project():
    project = Project()
    curves = [Curve(name, [0., 1., 2.], [0., 1., 0.]) for name in ("First", "Second", "Third")]
    for curve in curves:
        project.add_curve(curve)
        for number in (1, 2):
            project.model_for(curve.id).add(Component.create(
                "gaussian", name=f"Gaussian{number}", initial={"center": 10}))
    return project, curves


def _set_relation(project, curve, relation, scope="relative"):
    anchor, dependent = project.model_for(curve.id).components
    parameter = dependent.parameters["center"]
    parameter.link = f"${{{curve.id}.{anchor.id}.center}}"
    parameter.link_scope = "absolute"
    parameter.link_reference_scopes = [scope]
    parameter.link_relation = relation
    parameter.link_tolerance = 5 if relation == "similar" else 0
    parameter.link_tolerance_mode = "percent"
    parameter.validate()
    return anchor, parameter


@pytest.mark.parametrize("relation", ["lower", "upper", "similar"])
@pytest.mark.parametrize("scope", ["relative", "absolute"])
@pytest.mark.parametrize("structure", [True, False])
def test_bound_relation_copies_and_round_trips_with_its_source_scope(relation, scope, structure, tmp_path):
    project, (first, second, third) = _project()
    anchor, source = _set_relation(project, first, relation, scope)
    project.copy_fit(first.id, [second.id], structure=structure)
    project.copy_fit(second.id, [third.id], structure=structure)
    copied_anchor, copied_dependent = project.model_for(third.id).components
    parameter = copied_dependent.parameters["center"]
    expected = (
        f"${{{third.id}.{copied_anchor.id}.center}}" if scope == "relative" else
        f"${{{first.id}.{anchor.id}.center}}"
    )
    assert parameter.link == expected
    for key in ("link_relation", "link_tolerance", "link_tolerance_mode", "link_reference_scopes"):
        assert getattr(parameter, key) == getattr(source, key)
    restored = load_project(save_project(project, tmp_path / "dynamic.fitproj"))
    assert restored.model_for(third.id).components[1].parameters["center"].to_dict() == parameter.to_dict()
    assert restored.resolved_parameter_values() == project.resolved_parameter_values()


@pytest.mark.parametrize("structure", [True, False])
def test_disabling_function_link_copy_preserves_existing_relation(structure):
    project, (first, second, _) = _project()
    _, target = _set_relation(project, second, "similar", "absolute")
    before = target.to_dict()
    project.copy_fit(first.id, [second.id], structure=structure, links=False)
    parameter = project.model_for(second.id).components[1].parameters["center"]
    for key in ("link", "link_scope", "link_reference_scopes", "link_relation", "link_tolerance", "link_tolerance_mode"):
        assert parameter.to_dict()[key] == before[key]


def test_sequential_propagation_preserves_dynamic_relation_and_clears_disabled_metadata():
    project, (first, second, third) = _project()
    anchor, source = _set_relation(project, first, "similar")
    copied = _clone_model_for_target(project.model_for(first.id), first.id, second)
    parameter = copied.components[1].parameters["center"]
    assert parameter.link == f"${{{second.id}.{anchor.id}.center}}"
    for key in ("link_relation", "link_tolerance", "link_tolerance_mode", "link_reference_scopes"):
        assert getattr(parameter, key) == getattr(source, key)
    unlinked = _clone_model_for_target(copied, second.id, third, propagate_links=False)
    parameter = unlinked.components[1].parameters["center"]
    assert parameter.link is None
    assert parameter.link_relation == "equal"
    assert parameter.link_tolerance == 0
    assert parameter.link_tolerance_mode == "absolute"
    assert parameter.link_reference_scopes == []


def test_workflow_dump_and_import_preserve_relation_and_reference_metadata(tmp_path):
    project, (first, _, _) = _project()
    _, source = _set_relation(project, first, "similar", "absolute")
    data_path = tmp_path / "spectrum.txt"
    data_path.write_text("0 0\n1 1\n2 0\n")
    for curve in project.curves:
        curve.source = str(data_path)
    workflow_path = dump_workflow(project, tmp_path / "workflow.yml")
    workflow = load_workflow(workflow_path)
    rules = workflow["models"][0]["components"][1]["constraints"]["center"]
    keys = ("link", "link_scope", "link_reference_scopes", "link_relation", "link_tolerance", "link_tolerance_mode")
    for key in keys:
        assert rules[key] == source.to_dict()[key]
    imported = run_workflow(workflow_path).project
    copied = imported.model_for(imported.curves[0].id).components[1].parameters["center"]
    for key in keys:
        assert copied.to_dict()[key] == source.to_dict()[key]
