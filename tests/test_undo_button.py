from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QDialog

from curvemole import Component, Curve, Project
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.dialogs import BackgroundComponentsDialog


def _background_project() -> tuple[Project, np.ndarray, Component]:
    project = Project("undo button")
    x = np.linspace(0.0, 4.0, 21)
    curve = Curve("spectrum", x, 2.0 + np.linspace(1.0, 2.0, len(x)))
    project.add_curve(curve)
    background = Component.create("constant", initial={"offset": 2.0})
    background.is_background = True
    project.model_for(curve.id).add(background)
    project.dirty = False
    return project, curve.y.copy(), background


def test_toolbar_undo_action_triggers_stack_for_generic_change() -> None:
    app = QApplication.instance() or QApplication([])
    project, _, _ = _background_project()
    window = CurveMoleMainWindow(project)
    marker = {"value": 0}

    window._push_change(
        "test change",
        lambda: marker.__setitem__("value", 1),
        lambda: marker.__setitem__("value", 0),
    )
    app.processEvents()

    assert marker["value"] == 1
    assert window.undo_stack.canUndo()
    assert window.undo_action.isEnabled()

    window.undo_action.trigger()
    app.processEvents()

    assert marker["value"] == 0
    assert window.undo_stack.canRedo()

    project.dirty = False
    window.close()
    app.processEvents()


def test_toolbar_undo_action_restores_background_subtraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    project, original, background = _background_project()
    window = CurveMoleMainWindow(project)

    monkeypatch.setattr(
        BackgroundComponentsDialog,
        "exec",
        lambda _dialog: QDialog.DialogCode.Accepted,
    )
    window.subtract_background()
    app.processEvents()

    np.testing.assert_allclose(project.curves[0].y, original - 2.0)
    assert background.enabled is False
    assert window.undo_action.isEnabled()

    window.undo_action.trigger()
    app.processEvents()

    np.testing.assert_allclose(project.curves[0].y, original)
    assert background.enabled is True

    project.dirty = False
    window.close()
    app.processEvents()


def test_toolbar_undo_action_restores_global_background_subtraction() -> None:
    app = QApplication.instance() or QApplication([])
    project, original, background = _background_project()
    window = CurveMoleMainWindow(project)

    window.subtract_all_backgrounds()
    app.processEvents()

    np.testing.assert_allclose(project.curves[0].y, original - 2.0)
    assert background.enabled is False
    assert window.undo_action.isEnabled()

    window.undo_action.trigger()
    app.processEvents()

    np.testing.assert_allclose(project.curves[0].y, original)
    assert background.enabled is True

    project.dirty = False
    window.close()
    app.processEvents()
