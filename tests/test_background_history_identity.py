import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QDialog

from curvemole import Component, Curve, Model, Project
from curvemole.core.background_status import background_component_subtracted
from curvemole.core.serialization import load_project, save_project
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.dialogs import BackgroundComponentsDialog, CopyFitDialog


@pytest.fixture
def background_window():
    app = QApplication.instance() or QApplication([])
    project = Project("Copied backgrounds")
    for number, offset in enumerate((2., 5., 9.)):
        curve = Curve(f"Spectrum {number}", np.linspace(0., 1., 11), np.full(11, offset + 1.))
        project.add_curve(curve)
        background = Component.create("constant", name="Baseline", initial={"offset": offset})
        background.is_background = True
        background.metadata["custom_name"] = True
        project.model_for(curve.id).add(background)
    window = CurveMoleMainWindow(project)
    yield app, window
    project.dirty = False
    window.close()
    window.deleteLater()
    app.processEvents()


def test_copy_fit_preserves_destination_subtraction_through_undo_reopen_and_revert(background_window, tmp_path, monkeypatch):
    app, window = background_window
    project = window.project
    source, target, _ = project.curves
    originals = {curve.id: curve.y.copy() for curve in project.curves}
    window.subtract_all_backgrounds()
    old_id = project.model_for(target.id).components[0].id
    monkeypatch.setattr(CopyFitDialog, "exec", lambda _dialog: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(CopyFitDialog, "choices", lambda _dialog: ([target.id], {}))
    window.copy_fit()
    copied = project.model_for(target.id).components[0]
    assert copied.id != old_id
    assert background_component_subtracted(target, copied)
    assert not copied.enabled
    np.testing.assert_allclose(target.y, originals[target.id] - 5.)
    window._set_active_curve(target.id)
    assert "Subtracted" in window.model_panel.components.item(0).text()
    window.undo_stack.undo()
    assert project.model_for(target.id).components[0].id == old_id
    assert background_component_subtracted(target, project.model_for(target.id).components[0])
    window.undo_stack.redo()
    restored = load_project(save_project(project, tmp_path / "backgrounds.fitproj"))
    other = CurveMoleMainWindow(restored)
    try:
        other._set_active_curve(target.id)
        assert "Subtracted" in other.model_panel.components.item(0).text()
        assert not restored.model_for(target.id).components[0].enabled
        other.revert_backgrounds([target.id])
        np.testing.assert_allclose(restored.dataset.curve(target.id).y, originals[target.id])
        assert restored.model_for(target.id).components[0].enabled
        assert "Not subtracted" in other.model_panel.components.item(0).text()
        # A model replacement between the action and its undo must not leave
        # the live function enabled while the data subtraction is restored.
        before = restored.model_for(target.id).to_dict()
        changed = Model.from_dict(before)
        changed.components[0].parameters["offset"].value = 7.
        other._push_model_state(target.id, before, changed.to_dict(), "Edit after revert")
        other.undo_stack.undo()
        other.undo_stack.undo()
        np.testing.assert_allclose(restored.dataset.curve(target.id).y, originals[target.id] - 5.)
        assert not restored.model_for(target.id).components[0].enabled
    finally:
        restored.dirty = False
        other.close()
        other.deleteLater()
        app.processEvents()


def test_subtracted_source_does_not_disable_raw_destination_or_mark_duplicate(background_window, monkeypatch):
    _app, window = background_window
    project = window.project
    source, target, third = project.curves
    monkeypatch.setattr(BackgroundComponentsDialog, "exec", lambda _dialog: QDialog.DialogCode.Accepted)
    window.subtract_background()
    assert not project.model_for(source.id).components[0].enabled
    raw = target.y.copy()
    project.copy_fit(source.id, [target.id])
    copied = project.model_for(target.id).components[0]
    assert copied.enabled
    assert not background_component_subtracted(target, copied)
    np.testing.assert_array_equal(target.y, raw)
    # Alias history is spectrum-specific and must not leak on a further copy.
    window._set_active_curve(third.id)
    window.subtract_background()
    project.copy_fit(target.id, [third.id])
    historic = project.model_for(third.id).components[0]
    assert historic.metadata["background_subtraction_ids"]
    duplicate = project.model_for(third.id).duplicate(historic.id)
    assert not background_component_subtracted(third, duplicate)
    assert background_component_subtracted(third, historic)


def test_same_name_of_different_function_does_not_inherit_subtraction(background_window, monkeypatch):
    _app, window = background_window
    project = window.project
    source, target, _ = project.curves
    window.subtract_all_backgrounds()
    replacement = Component.create("linear", name="Baseline")
    replacement.is_background = True
    project.models[source.id] = Model(components=[replacement])
    project.copy_fit(source.id, [target.id])
    assert not background_component_subtracted(target, project.model_for(target.id).components[0])
