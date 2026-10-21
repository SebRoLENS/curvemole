import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton

from curvemole import Component, Curve, Project
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.function_composition import (
    OPERATORS,
    selected_operator,
    set_operator,
    sync_composition,
)


@pytest.fixture
def composition_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "composition.ini"), QSettings.Format.IniFormat)
    settings.setValue("last_quick_function", "gaussian")
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    project = Project("Composition")
    x = np.linspace(-6, 6, 1201)
    project.add_curve(Curve("Measured", x, 2 + 5*np.exp(-.5*((x-1)/.5)**2)))
    window = CurveMoleMainWindow(project)
    window.show()
    app.processEvents()
    yield app, window, project.curves[0]
    window.plot_workspace.cancel_placement()
    project.dirty = False
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def add_baseline(window, curve):
    baseline = Component.create("constant", initial={"offset": 2})
    window.project.model_for(curve.id).add(baseline)
    window.refresh_all()
    return baseline


@pytest.mark.parametrize("operator", ["add", "subtract", "multiply", "divide"])
def test_auto_peak_uses_composition_signal_and_selected_operator(composition_window, operator):
    app, window, old = composition_window
    x = old.x
    peak = 5*np.exp(-.5*((x-1)/.5)**2)
    y = {"add": 2+peak, "subtract": 2-peak, "multiply": 2*peak, "divide": 2/peak}[operator]
    curve = Curve(operator, x, y)
    window.project.add_curve(curve)
    window.active_curve_id = curve.id
    add_baseline(window, curve)
    set_operator(window, operator)
    QTest.mouseClick(window.add_function_button, Qt.MouseButton.LeftButton)
    model = window.project.model_for(curve.id)
    component = model.components[-1]
    assert len(model.components) == 2
    assert component.operator == operator
    assert component.parameters["center"].value == pytest.approx(1, abs=.02)
    assert component.parameters["sigma"].value == pytest.approx(.5, rel=.01)
    assert model.evaluate(np.array([1.]), curve_id=curve.id, registry=window.registry)[0] == pytest.approx(
        {"add": 7, "subtract": -3, "multiply": 10, "divide": .4}[operator], rel=.01
    )
    window.undo_action.trigger()
    assert len(window.project.model_for(curve.id).components) == 1
    window.redo_action.trigger()
    assert window.project.model_for(curve.id).components[-1].operator == operator


def test_convolution_auto_kernel_is_centred_and_has_unit_area(composition_window):
    _, window, curve = composition_window
    add_baseline(window, curve)
    set_operator(window, "convolve")
    window.quick_peak()
    component = window.project.model_for(curve.id).components[-1]
    assert component.operator == "convolve"
    assert component.parameters["area"].value == 1
    assert component.parameters["center"].value == 0
    assert np.all(np.isfinite(window.project.model_for(curve.id).evaluate(curve.x, registry=window.registry)))


@pytest.mark.parametrize("operator,_,label", OPERATORS)
def test_composition_applies_to_free_generic_functions(composition_window, operator, _, label):
    app, window, curve = composition_window
    add_baseline(window, curve)
    window.quick_function_selector.setCurrentIndex(window.quick_function_selector.findData("linear"))
    window.function_composition_actions[operator].trigger()
    assert selected_operator(window) == operator
    assert label in window.quick_peak_action.toolTip()
    assert window.add_function_button.popupMode() == QToolButton.ToolButtonPopupMode.MenuButtonPopup
    QTest.mouseClick(window.add_function_button, Qt.MouseButton.LeftButton)
    assert window.project.model_for(curve.id).components[-1].operator == operator


def test_empty_model_allows_every_insertion_role(composition_window):
    _, window, curve = composition_window
    sync_composition(window)
    for operator, _, _ in OPERATORS:
        assert window.function_composition_actions[operator].isEnabled()
    set_operator(window, "multiply")
    window.quick_peak()
    assert window.project.model_for(curve.id).components[-1].operator == "multiply"


def test_graphical_peaks_and_pending_next_peak_keep_the_chosen_operator(composition_window):
    _, window, curve = composition_window
    add_baseline(window, curve)
    window.quick_add_manual_points.setChecked(True)
    set_operator(window, "multiply")
    window.quick_peak()
    assert window._pending_component.operator == "multiply"
    window.plot_workspace._finish_peak_placement(1, 5, 1)
    assert window.project.model_for(curve.id).components[-1].operator == "multiply"
    set_operator(window, "divide")
    assert window._pending_component.operator == "divide"
    window.plot_workspace._finish_peak_placement(-1, 1, 1)
    window.plot_workspace.finish_placement()
    assert [c.operator for c in window.project.model_for(curve.id).components] == ["add", "multiply", "divide"]


def test_details_and_advanced_add_share_composition_and_show_selected_symbol(composition_window, monkeypatch):
    app, window, curve = composition_window
    add_baseline(window, curve)
    original_icon = window.quick_peak_action.icon().pixmap(64, 64).toImage()
    set_operator(window, "multiply")
    assert window.quick_peak_action.icon().pixmap(64, 64).toImage() != original_icon
    window.function_info_button.click()
    dialog = window._function_info_dialog
    assert dialog.composition_selector.currentData() == "multiply"
    dialog.composition_selector.setCurrentIndex(dialog.composition_selector.findData("divide"))
    assert selected_operator(window) == "divide"
    assert window.function_composition_actions["divide"].isChecked()
    from curvemole.gui.dialogs import AddComponentDialog
    selected = []
    def accept(advanced):
        selected.append(advanced.operator.currentText())
        advanced.operator.setCurrentText("subtract")
        advanced.function.setCurrentIndex(advanced.function.findData("constant"))
        advanced.manual_points.setChecked(False)
        return advanced.DialogCode.Accepted
    monkeypatch.setattr(AddComponentDialog, "exec", accept)
    QTest.mouseClick(dialog.add_button, Qt.MouseButton.LeftButton)
    assert selected == ["divide"]
    assert selected_operator(window) == "subtract"
    assert window.project.model_for(curve.id).components[-1].operator == "subtract"


def test_background_preference_is_preserved_but_only_used_for_additive_terms(composition_window):
    _, window, curve = composition_window
    add_baseline(window, curve)
    window.quick_add_background.setChecked(True)
    set_operator(window, "multiply")
    assert not window.quick_add_background.isEnabled()
    assert not window.quick_add_background.isChecked()
    window.quick_peak()
    assert not window.project.model_for(curve.id).components[-1].is_background
    set_operator(window, "add")
    assert window.quick_add_background.isEnabled()
    assert window.quick_add_background.isChecked()
