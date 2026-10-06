import copy

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Model, Project
from curvemole.core.background_status import (
    background_component_ids,
    background_component_status,
    background_component_subtracted,
)
from curvemole.core.calculator import apply_background_subtraction
from curvemole.core.serialization import load_project, save_project
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.background_controls_fix import RevertBackgroundDialog, _eligible_revert_curves


def legacy_project(name="Linear1", *, replacements=1, typed=False):
    project = Project("Old background history")
    x = np.linspace(0., 2., 11)
    original = 4. + 2. * x
    curve = Curve("Subtracted spectrum", x, original)
    project.add_curve(curve)
    old = Component.create("linear", name=name, initial={"intercept": 3., "slope": 2.})
    old.is_background = True
    parameters = {"component_ids": [old.id], "component_names": [name],
                  "component_states_before": {old.id: {"is_background": True, "enabled": True}}}
    if typed:
        parameters["component_functions"] = {old.id: old.function_id}
    apply_background_subtraction(curve, 3. + 2. * x, method="model_components",
                                 description="Old subtraction", parameters=parameters)
    components = [Component.create("linear", name="Linear1", initial={"intercept": 7., "slope": 1.})
                  for _ in range(replacements)]
    for component in components:
        component.is_background = True
        component.enabled = False
    project.models[curve.id] = Model(components=components)
    return project, curve, old.id, original


@pytest.mark.parametrize("old_name", ["Linear", "Linear1", "Linear 1", "Linear2"])
def test_old_project_reconnects_the_linear_background_without_changing_saved_data(tmp_path, old_name):
    project, curve, old_id, original = legacy_project(old_name)
    before_y = curve.y.copy()
    before_transformation = copy.deepcopy(curve.transformations[0].to_dict())
    path = save_project(project, tmp_path / "old.fitproj")
    restored = load_project(path)
    current = restored.model_for(curve.id).components[0]
    assert current.id != old_id
    assert old_id in background_component_ids(current)
    assert background_component_subtracted(restored.curves[0], current)
    assert not current.enabled
    assert current.parameters["intercept"].value == 7.
    assert not restored.dirty
    np.testing.assert_array_equal(restored.curves[0].y, before_y)
    assert restored.curves[0].transformations[0].to_dict() == before_transformation
    np.testing.assert_array_equal(restored.curves[0].original_y, original)
    again = load_project(save_project(restored, tmp_path / "repaired.fitproj"))
    assert background_component_subtracted(again.curves[0], again.model_for(curve.id).components[0])


def test_revert_list_and_model_label_agree_for_reopened_legacy_project(tmp_path):
    app = QApplication.instance() or QApplication([])
    project, curve, _old_id, original = legacy_project()
    restored = load_project(save_project(project, tmp_path / "old.fitproj"))
    window = CurveMoleMainWindow(restored)
    try:
        candidates = _eligible_revert_curves(window)
        assert [item.id for item in candidates] == [curve.id]
        dialog = RevertBackgroundDialog(candidates, curve.id, window)
        assert dialog.spectra.count() == 1
        dialog.reject()  # Inspecting the list does not revert any data.
        np.testing.assert_array_equal(restored.curves[0].y, curve.y)
        assert "Subtracted" in window.model_panel.components.item(0).text()
        assert "Not subtracted" not in window.model_panel.components.item(0).text()
        current = restored.model_for(curve.id).components[0]
        window.revert_backgrounds([curve.id])
        np.testing.assert_array_equal(restored.curves[0].y, original)
        assert current.enabled
        assert "Not subtracted" in window.model_panel.components.item(0).text()
        window.undo_stack.undo()
        np.testing.assert_array_equal(restored.curves[0].y, curve.y)
        assert not current.enabled
        assert "Subtracted" in window.model_panel.components.item(0).text()
        window.undo_stack.redo()
        assert "Not subtracted" in window.model_panel.components.item(0).text()
    finally:
        restored.dirty = False
        window.close()
        window.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("replacements,name", [(2, "Linear1"), (1, "Experimental baseline")])
def test_ambiguous_legacy_history_is_explicit_instead_of_a_false_not_subtracted(tmp_path, replacements, name):
    app = QApplication.instance() or QApplication([])
    project, curve, old_id, _original = legacy_project(name, replacements=replacements)
    restored = load_project(save_project(project, tmp_path / "ambiguous.fitproj"))
    model = restored.model_for(curve.id)
    assert all(old_id not in background_component_ids(c) for c in model.components)
    assert all(background_component_status(restored.curves[0], c, model) == "unresolved" for c in model.components)
    window = CurveMoleMainWindow(restored)
    try:
        assert len(_eligible_revert_curves(window)) == 1
        labels = [window.model_panel.components.item(i).text() for i in range(len(model.components))]
        assert all("function uncertain" in label for label in labels)
        assert all("Not subtracted" not in label for label in labels)
        again = load_project(save_project(restored, tmp_path / "still-ambiguous.fitproj"))
        saved_model = again.model_for(curve.id)
        assert all(old_id not in background_component_ids(c) for c in saved_model.components)
        assert all(background_component_status(again.curves[0], c, saved_model) == "unresolved"
                   for c in saved_model.components)
    finally:
        restored.dirty = False
        window.close()
        window.deleteLater()
        app.processEvents()


def test_new_typed_record_does_not_attach_itself_to_a_replacement_with_the_same_name(tmp_path):
    project, curve, old_id, _original = legacy_project(typed=True)
    restored = load_project(save_project(project, tmp_path / "replacement.fitproj"))
    current = restored.model_for(curve.id).components[0]
    assert old_id not in background_component_ids(current)
    assert not background_component_subtracted(restored.curves[0], current)


def test_duplicate_does_not_inherit_old_background_after_original_is_removed(tmp_path):
    project, curve, _old_id, _original = legacy_project()
    restored = load_project(save_project(project, tmp_path / "restored.fitproj"))
    model = restored.model_for(curve.id)
    source = model.components[0]
    duplicate = model.duplicate(source.id)
    duplicate.name = source.name
    model.remove(source.id)
    again = load_project(save_project(restored, tmp_path / "duplicate.fitproj"))
    current = again.model_for(curve.id).components[0]
    assert not background_component_subtracted(again.curves[0], current)
    assert background_component_status(again.curves[0], current, again.model_for(curve.id)) == "not_subtracted"


def test_new_subtraction_records_function_type(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from curvemole.gui.dialogs import BackgroundComponentsDialog

    app = QApplication.instance() or QApplication([])
    project = Project()
    curve = Curve("New spectrum", [0., 1., 2.], [3., 4., 5.])
    project.add_curve(curve)
    background = Component.create("linear", initial={"intercept": 2., "slope": 1.})
    background.is_background = True
    project.model_for(curve.id).add(background)
    window = CurveMoleMainWindow(project)
    monkeypatch.setattr(BackgroundComponentsDialog, "exec", lambda _dialog: QDialog.DialogCode.Accepted)
    try:
        window.subtract_background()
        assert curve.transformations[-1].parameters["component_functions"] == {background.id: "linear"}
    finally:
        project.dirty = False
        window.close()
        window.deleteLater()
        app.processEvents()
