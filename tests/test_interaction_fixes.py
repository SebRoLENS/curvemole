import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication, QInputDialog

from curvemole import Component, Curve, Project
from curvemole.core.fitting import FitMode, FitPlan
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.main_window import CallbackCommand


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    project = Project()
    x = np.linspace(0, 10, 101)
    for index in range(2):
        curve = Curve(str(index), x, 1 + 2*x)
        project.add_curve(curve)
        project.model_for(curve.id).add(Component.create("linear", initial={"intercept": 0., "slope": 0.}))
    instance = CurveMoleMainWindow(project)
    yield instance
    instance.project.dirty = False
    instance.close()
    app.processEvents()


@pytest.mark.parametrize("scope", ["Active spectrum only", "All visible spectra"])
@pytest.mark.parametrize("mode", [1, 2])
def test_mask_scope_and_mouse_buttons(window, monkeypatch, scope, mode):
    workspace = window.plot_workspace
    workspace.display_mode.setCurrentIndex(mode)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (scope, True))
    workspace.mask_action.trigger()
    assert workspace.view_box.mask_mode
    monkeypatch.setattr(workspace.view_box, "mapSceneToView", lambda point: point)

    class Drag:
        def __init__(self, button):
            self._button = button
        def button(self):
            return self._button
        def isFinish(self):
            return True
        def buttonDownScenePos(self):
            return QPointF(2, 0)
        def scenePos(self):
            return QPointF(4, 0)
        def accept(self):
            pass

    workspace.view_box.mouseDragEvent(Drag(Qt.MouseButton.RightButton))
    for curve in window.project.curves:
        expected = scope.startswith("All") or curve.id == window.active_curve_id
        assert bool(curve.effective_mask.any()) == expected
    workspace.view_box.mouseDragEvent(Drag(Qt.MouseButton.LeftButton))
    assert not any(curve.effective_mask.any() for curve in window.project.curves)
    window.undo_action.trigger()
    assert window.project.dataset.curve(window.active_curve_id).effective_mask.any()


def test_cancel_mask_scope_leaves_button_off(window, monkeypatch):
    workspace = window.plot_workspace
    workspace.display_mode.setCurrentIndex(1)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: ("", False))
    workspace.mask_action.trigger()
    assert not workspace.mask_action.isChecked()
    assert not workspace.view_box.mask_mode


def test_real_application_selector_controls_all_function_types(window, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: pytest.fail("Obsolete function chooser opened"))
    selector = window.quick_function_selector
    assert {selector.itemData(i) for i in range(selector.count())} == {d.identifier for d in window.registry.values()}
    selector.setCurrentIndex(selector.findData("lorentzian"))
    window.quick_peak_action.trigger()
    assert window._pending_component.function_id == "lorentzian"
    assert window.plot_workspace._continuous_peak_placement
    selector.setCurrentIndex(selector.findData("gaussian"))
    assert window._pending_component.function_id == "gaussian"
    selector.setCurrentIndex(selector.findData("cubic_spline"))
    assert window._pending_component.function_id == "cubic_spline"
    assert window.plot_workspace._placement_mode == "spline"
    selector.setCurrentIndex(selector.findData("constant"))
    count = len(window.project.model_for(window.active_curve_id).components)
    window.quick_peak_action.trigger()
    assert len(window.project.model_for(window.active_curve_id).components) == count + 1
    assert window.project.model_for(window.active_curve_id).components[-1].function_id == "constant"


def test_fit_undo_redo_preserves_prior_edit_references(window, monkeypatch):
    curve_id = window.active_curve_id
    model = window.project.model_for(curve_id)
    parameter = model.components[0].parameters["intercept"]
    window.undo_stack.push(CallbackCommand("edit", lambda: setattr(parameter, "value", 0.5), lambda: setattr(parameter, "value", 0.)))
    original_x = window.project.dataset.curve(curve_id).x
    def synchronous(operation, finished, status):
        finished(operation(lambda *_: None))
        window._task_done()
    monkeypatch.setattr(window, "_run_background", synchronous)
    window._run_fit(FitPlan([curve_id], FitMode.INDEPENDENT))
    fitted = parameter.value
    assert fitted == pytest.approx(1.)
    assert "last_fit" in window.project.results
    window.undo_action.trigger()
    assert parameter.value == 0.5
    assert "last_fit" not in window.project.results
    assert window.project.dataset.curve(curve_id).x is original_x
    window.undo_action.trigger()
    assert parameter.value == 0.
    window.redo_action.trigger()
    window.redo_action.trigger()
    assert parameter.value == fitted
    assert "last_fit" in window.project.results
    assert window.undo_stack.undoLimit() == 20


def test_cancelled_fit_restores_pre_worker_model(window, monkeypatch):
    parameter = window.project.model_for(window.active_curve_id).components[0].parameters["intercept"]
    before = parameter.value
    def cancelled(operation, finished, status):
        parameter.value = 999.
        window._task_failed("cancelled", "test cancellation")
        window._task_done()
    monkeypatch.setattr(window, "_run_background", cancelled)
    window._run_fit(FitPlan([window.active_curve_id]))
    assert parameter.value == before
    assert not window.undo_stack.canUndo()
