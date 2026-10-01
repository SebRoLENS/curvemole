from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.core.errors import ConstraintError
from curvemole.core.parameters import Parameter
from curvemole.core.sequential_fit import _clone_model_for_target
from curvemole.core.serialization import load_project, save_project
from curvemole.gui.main_window import MainWindow
from curvemole.gui.parameter_copy import copy_parameter_to_refs


def _project():
    project = Project()
    curves = [Curve(name, [0., 1., 2.], [0., 1., 0.]) for name in ("First", "Second", "Third")]
    for index, curve in enumerate(curves):
        project.add_curve(curve)
        for number in (1, 2):
            project.model_for(curve.id).add(Component.create(
                "gaussian", name=f"Gaussian{number}", initial={"center": index + number}))
    return project, curves


def _mixed_link(project, curve):
    anchor, dependent = project.model_for(curve.id).components
    reference = f"${{{curve.id}.{anchor.id}.center}}"
    parameter = dependent.parameters["center"]
    parameter.link = f"({reference} + {reference}) / 2"
    parameter.link_scope = "absolute"
    parameter.link_reference_scopes = ["relative", "absolute"]
    parameter.validate()
    return anchor, parameter


def test_identical_reference_occurrences_keep_individual_copy_behavior():
    parameter = Parameter(
        "center", 1, link="${a.peak.center} + ${a.peak.center} + ${b.peak.center}",
        link_scope="absolute", link_reference_scopes=["relative", "absolute", "relative"],
    )
    assert parameter.copied_link("a", "c", {"peak": "destination"}) == (
        "${c.destination.center} + ${a.peak.center} + ${b.peak.center}"
    )
    assert parameter.effective_link_reference_scopes() == ["relative", "absolute", "relative"]
    assert parameter.link == "${a.peak.center} + ${a.peak.center} + ${b.peak.center}"


@pytest.mark.parametrize("structure", [True, False])
def test_mixed_scopes_survive_repeated_function_copies_and_save_load(structure, tmp_path):
    project, (first, second, third) = _project()
    source_anchor, source = _mixed_link(project, first)
    project.copy_fit(first.id, [second.id], structure=structure)
    project.copy_fit(second.id, [third.id], structure=structure)
    for curve in (second, third):
        copied_anchor, dependent = project.model_for(curve.id).components
        parameter = dependent.parameters["center"]
        assert parameter.link == (
            f"(${{{curve.id}.{copied_anchor.id}.center}} + "
            f"${{{first.id}.{source_anchor.id}.center}}) / 2"
        )
        assert parameter.link_reference_scopes == ["relative", "absolute"]
        assert parameter.link_reference_scopes is not source.link_reference_scopes
    restored = load_project(save_project(project, tmp_path / "mixed.fitproj"))
    assert restored.model_for(third.id).components[1].parameters["center"].to_dict() == (
        project.model_for(third.id).components[1].parameters["center"].to_dict()
    )
    assert restored.resolved_parameter_values() == project.resolved_parameter_values()


def test_sequential_propagation_keeps_occurrence_scopes_and_clears_them_when_disabled():
    project, (first, second, third) = _project()
    anchor, source = _mixed_link(project, first)
    copied = _clone_model_for_target(project.model_for(first.id), first.id, second)
    parameter = copied.components[1].parameters["center"]
    assert parameter.link == (
        f"(${{{second.id}.{anchor.id}.center}} + ${{{first.id}.{anchor.id}.center}}) / 2"
    )
    assert parameter.link_reference_scopes == ["relative", "absolute"]
    assert parameter.link_reference_scopes is not source.link_reference_scopes
    repeated = _clone_model_for_target(copied, second.id, third)
    assert repeated.components[1].parameters["center"].link == (
        f"(${{{third.id}.{anchor.id}.center}} + ${{{first.id}.{anchor.id}.center}}) / 2"
    )
    unlinked = _clone_model_for_target(copied, second.id, third, propagate_links=False)
    parameter = unlinked.components[1].parameters["center"]
    assert parameter.link is None
    assert parameter.link_scope == "relative"
    assert parameter.link_reference_scopes == []


@pytest.mark.parametrize("scope", ["relative", "absolute"])
def test_legacy_scope_applies_to_every_repeated_reference(scope):
    parameter = Parameter.from_dict({
        "name": "center", "value": 1, "link": "${ a.peak.center } + ${a.peak.center}",
        "link_scope": scope,
    })
    assert parameter.link_reference_scopes == []
    assert parameter.effective_link_reference_scopes() == [scope, scope]
    expected = (
        "${c.destination.center} + ${c.destination.center}" if scope == "relative" else parameter.link
    )
    assert parameter.copied_link("a", "c", {"peak": "destination"}) == expected


@pytest.mark.parametrize("scopes", [["relative"], ["relative", "absolute", "relative"]])
def test_reference_scope_count_must_match_occurrences(scopes):
    with pytest.raises(ConstraintError, match="match the expression references"):
        Parameter("center", 1, link="${a.peak.center} + ${a.peak.center}",
                  link_reference_scopes=scopes)


def test_reference_scope_values_are_validated_and_explicit_absolute_needs_no_mapping():
    with pytest.raises(ConstraintError, match="relative or absolute"):
        Parameter("center", 1, link="${a.peak.center}", link_reference_scopes=["other"])
    parameter = Parameter("center", 1, link="${a.peak.center}",
                          link_reference_scopes=["absolute"])
    assert parameter.copied_link("a", "b", {}) == parameter.link
    parameter.link_reference_scopes = ["relative"]
    with pytest.raises(ConstraintError, match="source function is missing"):
        parameter.copied_link("a", "b", {})


@pytest.mark.parametrize("structure", [True, False])
def test_disabled_function_link_copy_preserves_existing_occurrence_metadata(structure):
    project, (first, second, _) = _project()
    _, existing = _mixed_link(project, second)
    before = existing.to_dict()
    project.copy_fit(first.id, [second.id], structure=structure, links=False)
    parameter = project.model_for(second.id).components[1].parameters["center"]
    assert parameter.link == before["link"]
    assert parameter.link_scope == before["link_scope"]
    assert parameter.link_reference_scopes == before["link_reference_scopes"]
    assert parameter.link_reference_scopes is not existing.link_reference_scopes or not structure


def test_parameter_copy_keeps_mixed_scopes_and_undo_restores_metadata():
    app = QApplication.instance() or QApplication([])
    project, (first, second, _) = _project()
    source_anchor, source = _mixed_link(project, first)
    source_dependent = project.model_for(first.id).components[1]
    target_anchor, target_dependent = project.model_for(second.id).components
    window = MainWindow(project)
    copy_parameter_to_refs(
        window, (first.id, source_dependent.id), [(second.id, target_dependent.id)],
        "center", copy_link=True,
    )
    parameter = project.model_for(second.id).component(target_dependent.id).parameters["center"]
    assert parameter.link == (
        f"(${{{second.id}.{target_anchor.id}.center}} + ${{{first.id}.{source_anchor.id}.center}}) / 2"
    )
    assert parameter.link_reference_scopes == source.link_reference_scopes
    assert parameter.link_reference_scopes is not source.link_reference_scopes
    window.undo_stack.undo()
    parameter = project.model_for(second.id).component(target_dependent.id).parameters["center"]
    assert parameter.link is None
    assert parameter.link_reference_scopes == []
    window.undo_stack.redo()
    parameter = project.model_for(second.id).component(target_dependent.id).parameters["center"]
    assert parameter.link_reference_scopes == ["relative", "absolute"]
    project.dirty = False
    window.close()
    app.processEvents()
