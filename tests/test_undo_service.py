import numpy as np
import pytest

from curvemole import Component, Curve, Project
from curvemole.core.transactions import ModelEdit, model_state, restore_model_state


@pytest.fixture
def window():
    from PySide6.QtWidgets import QApplication

    from curvemole.gui.app import CurveMoleMainWindow

    app = QApplication.instance() or QApplication([])
    project = Project("undo")
    curve = Curve("c", np.arange(5.), np.arange(5.))
    project.add_curve(curve)
    win = CurveMoleMainWindow(project)
    win.active_curve_id = curve.id
    yield win
    win.project.dirty = False
    win.close()
    app.processEvents()


def _add_constant(win):
    model = win.project.model_for(win.active_curve_id)
    before = model_state(model)
    model.add(Component.create("constant"))
    after = model_state(model)
    restore_model_state(win.project, win.active_curve_id, before)
    win._push_model_state(win.active_curve_id, before, after, "Add constant")


def test_undo_back_to_the_saved_state_clears_the_modified_flag(window):
    window.undo_service.mark_saved()
    window.project.dirty = False
    _add_constant(window)
    assert window.project.dirty
    window.undo_stack.undo()
    assert not window.project.dirty
    window.undo_stack.redo()
    assert window.project.dirty


def test_changes_outside_undo_keep_the_project_modified(window):
    window.undo_service.mark_saved()
    window.project.dirty = False
    _add_constant(window)
    window.project.ui_state["mask_transfer_tolerance"] = 0.5
    window.project.touch()  # not undoable
    window.undo_stack.undo()
    assert window.project.dirty


def test_model_undo_keeps_surviving_component_objects(window):
    model = window.project.model_for(window.active_curve_id)
    first = Component.create("constant")
    model.add(first)
    before = model_state(model)
    model.add(Component.create("linear"))
    after = model_state(model)
    restore_model_state(window.project, window.active_curve_id, before)
    window.undo_service.push_model_edit(ModelEdit.single(window.active_curve_id, before, after), "Add linear")
    assert len(model.components) == 2
    window.undo_stack.undo()
    assert window.project.model_for(window.active_curve_id) is model
    assert model.components == [first] and model.components[0] is first


def test_replacing_the_project_is_announced(window):
    seen = []
    window.projectReplaced.connect(seen.append)
    replacement = Project("other")
    window.project = replacement
    assert seen == [replacement]
    window.project = replacement  # same object: no signal
    assert seen == [replacement]
