from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.core.models import Model
from curvemole.core.parameters import Parameter
from curvemole.core.sequential_fit import _clone_model_for_target
from curvemole.core.serialization import load_project, save_project
from curvemole.gui.dialogs import ParameterLinkDialog
from curvemole.gui.main_window import MainWindow
from curvemole.gui.parameter_copy import copy_parameter_to_refs


def _project():
    project = Project()
    curves = [Curve(name, [0., 1., 2.], [0., 1., 0.]) for name in ("Spectrum 1", "Spectrum 2", "Spectrum 3")]
    for index, curve in enumerate(curves):
        project.add_curve(curve)
        for number in (1, 2):
            project.model_for(curve.id).add(Component.create(
                "gaussian", name=f"Gaussian{number}", initial={"center": index + number}))
    return project, curves


@pytest.mark.parametrize("scope", ["relative", "absolute"])
@pytest.mark.parametrize("structure", [True, False])
def test_copy_functions_keeps_local_or_fixed_source_through_repeated_copies(scope, structure, tmp_path):
    project, (first, second, third) = _project()
    anchor, dependent = project.model_for(first.id).components
    source = dependent.parameters["center"]
    source.link = f"${{{first.id}.{anchor.id}.center}}"
    source.link_scope = scope
    project.copy_fit(first.id, [second.id], structure=structure)
    project.copy_fit(second.id, [third.id], structure=structure)
    for curve in (second, third):
        copied_anchor, copied_dependent = project.model_for(curve.id).components
        copied = copied_dependent.parameters["center"]
        expected = (f"${{{curve.id}.{copied_anchor.id}.center}}" if scope == "relative" else source.link)
        assert copied.link == expected
        assert copied.link_scope == scope
    restored = load_project(save_project(project, tmp_path / "links.fitproj"))
    assert restored.model_for(third.id).components[1].parameters["center"].link_scope == scope
    assert restored.resolved_parameter_values() == project.resolved_parameter_values()


@pytest.mark.parametrize("scope", ["relative", "absolute"])
def test_sequential_propagation_respects_scope(scope):
    project, (first, second, _) = _project()
    anchor, dependent = project.model_for(first.id).components
    source = dependent.parameters["center"]
    source.link = f"2 * ${{{first.id}.{anchor.id}.center}} + 1"
    source.link_scope = scope
    clone = _clone_model_for_target(project.model_for(first.id), first.id, second)
    expected = source.link.replace(first.id, second.id) if scope == "relative" else source.link
    assert clone.components[1].parameters["center"].link == expected
    assert clone.components[1].parameters["center"].link_scope == scope


def test_old_parameter_defaults_to_relative_and_external_references_stay_fixed():
    parameter = Parameter.from_dict({"name": "center", "value": 1, "link": "${a.peak.center} + ${b.peak.center}"})
    assert parameter.link_scope == "relative"
    assert parameter.copied_link("a", "c") == "${c.peak.center} + ${b.peak.center}"
    parameter.link_scope = "absolute"
    assert parameter.copied_link("a", "c") == parameter.link


def test_dialog_defaults_to_own_spectrum_and_reopens_fixed_same_spectrum():
    app = QApplication.instance() or QApplication([])
    project, (_, second, _) = _project()
    anchor, dependent = project.model_for(second.id).components
    dialog = ParameterLinkDialog(project, second.id, dependent.id, "center")
    dialog.source_parameter.setCurrentIndex(dialog.source_parameter.findData("center"))
    expected = f"${{{second.id}.{anchor.id}.center}}"
    assert dialog.selected_link_scope() == "relative"
    assert dialog.link_expression() == expected
    assert "destination spectrum" in dialog.copy_help.text()
    dialog.source_curve.setCurrentIndex(dialog.source_curve.findData(second.id))
    assert dialog.selected_link_scope() == "absolute"
    assert dialog.link_expression() == expected
    assert "Spectrum 2" in dialog.copy_help.text()
    dialog.close()
    reopened = ParameterLinkDialog(project, second.id, dependent.id, "center", expected, current_scope="absolute")
    assert reopened.selected_link_scope() == "absolute"
    assert reopened.link_expression() == expected
    reopened.close()
    app.processEvents()


def test_link_scope_edit_is_undoable_and_parameter_copy_uses_destination_functions():
    app = QApplication.instance() or QApplication([])
    project, (first, second, _) = _project()
    anchor, dependent = project.model_for(first.id).components
    target_anchor, target_dependent = project.model_for(second.id).components
    window = MainWindow(project)
    expression = f"${{{first.id}.{anchor.id}.center}}"
    window.apply_parameter_link(first.id, dependent.id, "center", expression, "absolute")
    window.apply_parameter_link(first.id, dependent.id, "center", expression, "relative")
    assert dependent.parameters["center"].link_scope == "relative"
    window.undo_stack.undo()
    assert dependent.parameters["center"].link_scope == "absolute"
    window.undo_stack.redo()
    assert dependent.parameters["center"].link_scope == "relative"
    copy_parameter_to_refs(window, (first.id, dependent.id), [(second.id, target_dependent.id)],
                           "center", copy_link=True)
    copied = project.model_for(second.id).component(target_dependent.id).parameters["center"]
    assert copied.link == f"${{{second.id}.{target_anchor.id}.center}}"
    assert copied.link_scope == "relative"
    window.undo_stack.undo()
    assert project.model_for(second.id).component(target_dependent.id).parameters["center"].link is None
    project.dirty = False
    window.close()
    app.processEvents()


def test_disabled_link_copy_preserves_existing_scope():
    project, (first, second, _) = _project()
    project.copy_fit(first.id, [second.id])
    anchor, dependent = project.model_for(second.id).components
    existing = dependent.parameters["center"]
    existing.link = f"${{{second.id}.{anchor.id}.center}}"
    existing.link_scope = "absolute"
    before = Model.from_dict(project.model_for(second.id).to_dict())
    project.copy_fit(first.id, [second.id], links=False)
    copied = project.model_for(second.id).components[1].parameters["center"]
    assert copied.link == before.components[1].parameters["center"].link
    assert copied.link_scope == "absolute"
