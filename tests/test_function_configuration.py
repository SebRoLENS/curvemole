from __future__ import annotations

import copy

import numpy as np
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.core.data import Mask
from curvemole.core.errors import DataValidationError
from curvemole.core.functions import FunctionDefinition, FunctionOptionSpec, ParameterSpec
from curvemole.core.registry import FunctionRegistry, default_registry
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.dialogs import AddComponentDialog
from curvemole.gui.function_configuration import (
    FunctionOptionsDialog,
    FunctionOptionsWidget,
    estimate_initial_parameters,
)


@pytest.fixture
def configured_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "options.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    monkeypatch.setattr("curvemole.gui.function_configuration.QSettings", lambda *args: settings)
    x = np.linspace(-3, 3, 101)
    project = Project("configuration")
    project.add_curve(Curve("data", x, 2 + 3*x + 4*x*x))
    window = CurveMoleMainWindow(project)
    yield app, window
    window.plot_workspace.cancel_placement()
    project.dirty = False
    window.close()
    app.processEvents()


def test_quick_polynomial_options_cancel_and_confirm(configured_window, monkeypatch):
    _, window = configured_window
    window.quick_function_selector.setCurrentIndex(window.quick_function_selector.findData("polynomial"))
    window.quick_add_background.setChecked(True)
    model = window.project.model_for(window.active_curve_id)
    undo = window.undo_stack.count()
    monkeypatch.setattr(FunctionOptionsDialog, "exec", lambda d: d.DialogCode.Rejected)
    window.quick_peak()
    assert not model.components
    assert window.undo_stack.count() == undo

    def choose(dialog):
        dialog.options.controls["order"].setValue(4)
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(FunctionOptionsDialog, "exec", choose)
    window.quick_peak()
    component = window.project.model_for(window.active_curve_id).components[-1]
    assert component.metadata["order"] == 4
    assert list(component.parameters) == [f"c{i}" for i in range(5)]
    assert component.is_background
    remembered = FunctionOptionsWidget(window.registry.get("polynomial"), settings=window.settings)
    assert remembered.metadata()["order"] == 4
    window.quick_add_manual_points.setChecked(True)
    window.quick_peak()
    assert window._pending_component.metadata["order"] == 4
    assert window.plot_workspace._manual_points_minimum == 5


def test_advanced_polynomial_preserves_common_edits_and_rejects_invalid(configured_window):
    _, window = configured_window
    dialog = AddComponentDialog(window.registry, window.project.dataset.curve(window.active_curve_id), window)
    dialog.function.setCurrentIndex(dialog.function.findData("polynomial"))
    dialog.polynomial_order.setValue(2)
    table = dialog.parameter_table
    table.item(0, 1).setText("7")
    table.item(0, 2).setText("0")
    table.item(0, 3).setText("10")
    table.item(0, 4).setCheckState(Qt.CheckState.Checked)
    dialog.polynomial_order.setValue(4)
    assert table.rowCount() == 5
    component = dialog.component()
    assert component.parameters["c0"].value == 7
    assert component.parameters["c0"].fixed
    table.item(0, 3).setText("6")
    dialog.accept()
    assert dialog.result() != dialog.DialogCode.Accepted
    assert "c0" in dialog.validation_error.text()
    table.item(0, 3).setText("nan")
    with pytest.raises(ValueError):
        dialog.component()
    dialog.close()


def test_advanced_values_committed_without_peak_placement(configured_window, monkeypatch):
    _, window = configured_window

    def choose(dialog):
        dialog.function.setCurrentIndex(dialog.function.findData("gaussian"))
        dialog.manual_points.setChecked(False)
        table = dialog.parameter_table
        row = next(i for i in range(table.rowCount()) if table.item(i, 0).text() == "center")
        for col, text in ((1, "1.5"), (2, "1"), (3, "2")):
            table.item(row, col).setText(text)
        table.item(row, 4).setCheckState(Qt.CheckState.Checked)
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(AddComponentDialog, "exec", choose)
    window.add_component()
    assert window._pending_component is None
    parameter = window.project.model_for(window.active_curve_id).components[-1].parameters["center"]
    assert (parameter.value, parameter.minimum, parameter.maximum, parameter.fixed) == (1.5, 1, 2, True)


def test_estimate_respects_bounds_fixed_values_masks_and_does_not_mutate_input():
    x = np.linspace(-2, 2, 51)
    y = 2 + 3*x
    y[-1] = 1e9
    curve = Curve("data", x, y)
    excluded = np.zeros(len(x), dtype=bool)
    excluded[-1] = True
    mask = Mask("outlier", excluded)
    curve.masks[mask.id] = mask
    component = Component.create("linear")
    component.parameters["intercept"].value = 2
    component.parameters["intercept"].fixed = True
    component.parameters["slope"].maximum = 1
    before = copy.deepcopy(component.to_dict())
    estimated = estimate_initial_parameters(component, curve, default_registry())
    assert estimated.parameters["intercept"].value == 2
    assert estimated.parameters["intercept"].fixed
    assert estimated.parameters["slope"].value == pytest.approx(1)
    assert component.to_dict() == before
    component.parameters["slope"].maximum = float("inf")
    estimated = estimate_initial_parameters(component, curve, default_registry())
    assert estimated.parameters["slope"].value == pytest.approx(3)


def test_future_function_options_are_shared_and_validated(configured_window):
    _, window = configured_window
    registry = FunctionRegistry()
    definition = FunctionDefinition("future", "Future", "generic", lambda x, p, m: p["a"]*x,
                                    (ParameterSpec("a", 1),),
                                    configuration_specs=(
                                        FunctionOptionSpec("count", "Count", 3, minimum=1, maximum=9),
                                        FunctionOptionSpec("mode", "Mode", "a", kind="choice", choices=("a", "b")),
                                        FunctionOptionSpec("enabled", "Enabled", False, kind="boolean"),
                                        FunctionOptionSpec("label", "Label", "x", kind="text"),
                                        FunctionOptionSpec("scale", "Scale", 0.5, kind="number", minimum=0, maximum=1),
                                    ))
    registry.register(definition)
    assert Component.create("future", registry=registry).metadata["count"] == 3
    dialog = AddComponentDialog(registry, None, window)
    dialog.options_widget.controls["count"].setValue(7)
    dialog.options_widget.controls["mode"].setCurrentText("b")
    component = dialog.component()
    assert component.metadata["count"] == 7
    assert component.metadata["mode"] == "b"
    with pytest.raises(DataValidationError):
        Component.create("future", registry=registry, metadata={"count": 0})
    dialog.close()


def test_estimate_and_restore_buttons(configured_window):
    _, window = configured_window
    dialog = AddComponentDialog(window.registry, window.project.dataset.curve(window.active_curve_id), window)
    dialog.function.setCurrentIndex(dialog.function.findData("polynomial"))
    dialog.polynomial_order.setValue(2)
    dialog._estimate_parameters()
    assert not dialog.validation_error.text()
    assert [p.value for p in dialog.component().parameters.values()] == pytest.approx([2, 3, 4])
    dialog.reset_parameters.click()
    assert all(p.value == 0 for p in dialog.component().parameters.values())
    dialog.close()
