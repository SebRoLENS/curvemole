"""Selection-aware background roles and readable positive-width bounds."""
from __future__ import annotations

import sys

import numpy as np
import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.gui.main_window import MainWindow


@pytest.fixture
def model_window():
    app = QApplication.instance() or QApplication([])
    project = Project()
    curve = Curve("Example", np.linspace(-5, 5, 51), np.ones(51))
    project.add_curve(curve)
    model = project.model_for(curve.id)
    model.add(Component.create("pseudo_voigt"))
    model.add(Component.create("linear"))
    window = MainWindow(project)
    yield app, window, curve
    project.dirty = False
    window.close()
    app.processEvents()


def select_rows(panel, rows):
    selection = panel.components.selectionModel()
    selection.clearSelection()
    for row in rows:
        selection.select(panel.components.model().index(row, 0),
                         QItemSelectionModel.SelectionFlag.Select)
    if rows:
        selection.setCurrentIndex(panel.components.model().index(rows[0], 0),
                                  QItemSelectionModel.SelectionFlag.NoUpdate)
    panel.refresh_parameters()


def bound_cell(window, name):
    table = window.model_panel.parameters
    row = next(row for row in range(table.rowCount()) if table.item(row, 0).text() == name)
    return table.item(row, 5)


def test_switch_targets_actual_selection_and_supports_mixed_undo(model_window):
    app, window, curve = model_window
    panel = window.model_panel
    model = window.project.model_for(curve.id)
    model.components[0].is_background = True
    panel.refresh()
    select_rows(panel, [0, 1])
    toggle = panel.background_toggle
    assert panel.background_group.title() == "Selected functions: 2"
    assert toggle.checkState() == Qt.CheckState.PartiallyChecked
    toggle.click()
    assert all(c.is_background for c in window.project.model_for(curve.id).components)
    assert toggle.checkState() == Qt.CheckState.Checked
    assert window.undo_stack.count() == 1
    window.undo_stack.undo()
    assert [c.is_background for c in window.project.model_for(curve.id).components] == [True, False]
    assert toggle.checkState() == Qt.CheckState.PartiallyChecked
    window.undo_stack.redo()
    toggle.click()
    assert not any(c.is_background for c in window.project.model_for(curve.id).components)
    assert toggle.checkState() == Qt.CheckState.Unchecked
    assert not curve.transformations
    assert all(c.enabled for c in window.project.model_for(curve.id).components)
    app.processEvents()


def test_switch_disabled_without_selection_and_for_read_only_project(model_window):
    _, window, _ = model_window
    panel = window.model_panel
    select_rows(panel, [])
    assert not panel.background_toggle.isEnabled()
    assert panel.background_group.title() == "No functions selected"
    select_rows(panel, [0])
    assert panel.background_toggle.isEnabled()
    window.project.read_only = True
    panel.refresh_parameters()
    assert not panel.background_toggle.isEnabled()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_switch_paints_on_off_and_mixed_and_supports_keyboard(model_window, theme):
    app, window, _ = model_window
    window.apply_theme(theme)
    window.show()
    panel = window.model_panel
    select_rows(panel, [0])
    switch = panel.background_toggle
    for state in (Qt.CheckState.Unchecked, Qt.CheckState.Checked, Qt.CheckState.PartiallyChecked):
        previous = switch.blockSignals(True)
        switch.setTristate(True)
        switch.setCheckState(state)
        switch.blockSignals(previous)
        app.processEvents()
        assert not switch.grab().isNull()
    panel.refresh_parameters()
    switch.setFocus()
    QTest.keyClick(switch, Qt.Key.Key_Space)
    assert switch.isChecked()
    assert panel.background_group.geometry().bottom() <= panel.parameters.geometry().top()


@pytest.mark.parametrize("floor", [sys.float_info.min, sys.float_info.epsilon])
def test_automatic_width_bounds_display_zero_and_preserve_numerical_limit(model_window, floor):
    _, window, curve = model_window
    panel = window.model_panel
    parameter = window.project.model_for(curve.id).components[0].parameters["fwhm"]
    parameter.minimum = floor
    panel.refresh_parameters()
    lower = bound_cell(window, "fwhm")
    assert lower.text() == "0"
    assert "greater than zero" in lower.toolTip()
    assert parameter.value == 1 and not parameter.fixed
    lower.setText("0.0")
    assert parameter.minimum == floor
    lower = bound_cell(window, "fwhm")
    lower.setText("")
    assert parameter.minimum == floor
    assert parameter.value == 1 and not parameter.fixed


def test_explicit_small_bound_is_not_rounded_and_can_return_to_automatic(model_window):
    _, window, curve = model_window
    parameter = window.project.model_for(curve.id).components[0].parameters["fwhm"]
    parameter.minimum = 1e-12
    window.model_panel.refresh_parameters()
    lower = bound_cell(window, "fwhm")
    assert lower.text() == "1e-12"
    lower.setText("0")
    assert parameter.minimum == Component.create("pseudo_voigt").parameters["fwhm"].minimum
    window.undo_stack.undo()
    assert parameter.minimum == 1e-12


def test_generic_small_values_and_limits_are_not_rounded(model_window):
    _, window, curve = model_window
    parameter = window.project.model_for(curve.id).components[1].parameters["slope"]
    parameter.value = parameter.minimum = sys.float_info.min
    select_rows(window.model_panel, [1])
    table = window.model_panel.parameters
    row = next(i for i in range(table.rowCount()) if table.item(i, 0).text() == "slope")
    assert table.item(row, 1).text() == f"{sys.float_info.min:.12g}"
    assert table.item(row, 5).text() == f"{sys.float_info.min:.12g}"
