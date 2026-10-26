"""Guided calculator scopes, the existing separate chooser, and real Undo."""

import numpy as np
import pytest
from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QToolBar, QToolButton

from curvemole import Curve, Project, Series
from curvemole.core.serialization import load_project, save_project
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.series_groups import SpectrumSelectionDialog


@pytest.fixture
def calculator_window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    project = Project('Calculator scopes')
    first = Curve('First', [0., 1., 2.], [1., 3., 2.])
    second = Curve('Second', first.x, [2., 4., 3.])
    third = Curve('Third', first.x, [3., 5., 4.])
    project.add_series(Series('One', [first, second]))
    project.add_series(Series('Two', [third]))
    project.dirty = False
    window = CurveMoleMainWindow(project)
    monkeypatch.setattr(window, '_show_error', lambda title, error: pytest.fail(f'{title}: {error}'))
    yield app, window
    window.project.dirty = False
    window.close()
    app.processEvents()


def select_rows(window, *curve_ids):
    with QSignalBlocker(window.curve_tree):
        window.curve_tree.clearSelection()
        for row in range(window.curve_tree.topLevelItemCount()):
            series = window.curve_tree.topLevelItem(row)
            for index in range(series.childCount()):
                child = series.child(index)
                child.setSelected(child.data(1, Qt.ItemDataRole.UserRole)[1] in curve_ids)
    window._selection_changed()


def test_new_project_autoscale_defaults_and_saved_choices(calculator_window, tmp_path):
    app, window = calculator_window
    assert window.plot_workspace.autoscale_toggle.isChecked()
    assert window.plot_workspace.autoscale_mode.isEnabled()
    window.plot_workspace.autoscale_toggle.setChecked(False)
    project = load_project(save_project(window.project, tmp_path / 'manual.fitproj'))
    assert project.ui_state['autoscale_enabled'] is False
    window.project = project
    window.active_curve_id = project.curves[0].id
    window.refresh_all()
    assert not window.plot_workspace.autoscale_toggle.isChecked()
    window.project.dirty = False
    window.new_project()
    assert window.plot_workspace.autoscale_toggle.isChecked()
    assert window.project.ui_state['autoscale_mode'] == 'all'
    # Old projects with no saved setting keep the legacy manual view.
    window.project = Project(ui_state={})
    window.active_curve_id = None
    window.refresh_all()
    assert not window.plot_workspace.autoscale_toggle.isChecked()
    app.processEvents()


def test_selected_spectra_are_highlighted_rows_across_series_and_never_fallback(calculator_window):
    _, window = calculator_window
    curves = window.project.curves
    curves[2].visible = False  # Visibility is separate from operation selection.
    select_rows(window, curves[0].id, curves[2].id)
    panel = window.calculator
    panel.scope.setCurrentIndex(panel.scope.findData('selected'))
    assert panel.scope.currentText() == 'Selected spectra (2)'
    assert panel.apply_button.text() == 'Apply to 2 spectra'
    assert [curve.id for curve in window._calculator_targets('selected')] == [curves[0].id, curves[2].id]
    panel.operation.setCurrentIndex(panel.operation.findData('y_add'))
    panel.value.setValue(10)
    panel.apply_button.click()
    np.testing.assert_allclose(curves[0].y, [11, 13, 12])
    np.testing.assert_allclose(curves[1].y, [2, 4, 3])
    np.testing.assert_allclose(curves[2].y, [13, 15, 14])
    assert window.undo_stack.count() == 1
    window.undo_stack.undo()
    for curve in curves:
        np.testing.assert_array_equal(curve.y, curve.original_y)
    select_rows(window)
    assert not panel.apply_button.isEnabled() and not panel.restore_button.isEnabled()
    assert window._calculator_targets('selected') == []
    assert window.active_curve_id is not None
    assert window.calculator.scope.currentText() == 'Selected spectra (0)'


def test_selected_series_scope_and_selection_context_do_not_reset_formula(calculator_window):
    _, window = calculator_window
    panel = window.calculator
    panel.formula.setText('y * 3')
    select_rows(window)
    window.curve_tree.topLevelItem(1).setSelected(True)
    window._selection_changed()
    panel.scope.setCurrentIndex(panel.scope.findData('selected'))
    assert window._calculator_targets('selected') == [window.project.curves[2]]
    assert panel.formula.text() == 'y * 3'
    assert panel.apply_button.text() == 'Apply to 1 spectrum'


@pytest.mark.parametrize('accept', [True, False])
def test_choose_multiple_keeps_real_separate_dialog_and_cancel_is_safe(calculator_window, monkeypatch, accept):
    _, window = calculator_window
    panel = window.calculator
    panel.scope.setCurrentIndex(panel.scope.findData(1))
    panel.operation.setCurrentIndex(panel.operation.findData('y_multiply'))
    panel.value.setValue(2)
    dialogs = []
    original_exec = SpectrumSelectionDialog.exec
    def execute(dialog):
        dialogs.append(dialog)
        assert isinstance(dialog, QDialog)
        assert dialog.parentWidget() is window
        assert not panel.isAncestorOf(dialog)
        dialog.all_series.setChecked(True)
        dialog._check_shown(True)
        QTimer.singleShot(0, dialog.accept if accept else dialog.reject)
        return original_exec(dialog)
    monkeypatch.setattr(SpectrumSelectionDialog, 'exec', execute)
    panel.apply_button.click()
    assert len(dialogs) == 1
    assert window.undo_stack.count() == int(accept)
    for curve in window.project.curves:
        np.testing.assert_array_equal(curve.y, curve.original_y * (2 if accept else 1))


def test_restore_toolbar_is_adjacent_and_restores_only_selected_with_undo(calculator_window):
    _, window = calculator_window
    toolbar = window.findChild(QToolBar, 'Main_toolbar')
    actions = toolbar.actions()
    index = actions.index(window.view_options_action)
    assert actions[index + 1] is window.restore_original_action
    assert actions[index + 2].isSeparator()
    button = toolbar.widgetForAction(window.restore_original_action)
    assert isinstance(button, QToolButton)
    assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert not window.restore_original_action.icon().pixmap(40, 40).isNull()
    curves = window.project.curves
    window.apply_calculator({'operation':'y_add', 'value':10., 'scope':2})
    select_rows(window, curves[1].id)
    controller = window.restore_original_controller
    controller.rebuild_menu()
    controller.scope_actions['selected'].trigger()
    np.testing.assert_allclose(curves[0].y, curves[0].original_y + 10)
    np.testing.assert_allclose(curves[1].y, curves[1].original_y)
    assert window.undo_stack.undoText() == 'Restore original data'
    window.undo_stack.undo()
    np.testing.assert_allclose(curves[1].y, curves[1].original_y + 10)
    window.undo_stack.redo()
    np.testing.assert_allclose(curves[1].y, curves[1].original_y)
    select_rows(window)
    controller.rebuild_menu()
    assert not controller.scope_actions['selected'].isEnabled()


def test_calculator_fields_and_expanded_saved_formulas_do_not_overlap(calculator_window):
    app, window = calculator_window
    window.show()
    window.calculator_action.trigger()
    panel = window.calculator
    panel.operation.setCurrentIndex(panel.operation.findData('y_multiply'))
    assert panel.formula.isHidden() and panel.saved_formulas_toggle.isHidden()
    assert not panel.value.isHidden()
    panel.operation.setCurrentIndex(panel.operation.findData('normalize_max'))
    assert panel.value.isHidden()
    panel.operation.setCurrentIndex(panel.operation.findData('curve_add'))
    assert not panel.operand.isHidden() and not panel.interpolation.isHidden()
    panel.operation.setCurrentIndex(panel.operation.findData('column_formula'))
    panel.saved_formulas_toggle.setChecked(True)
    app.processEvents()
    assert panel.operation_form.isRowVisible(panel.saved_formulas_body)
    assert panel.saved_formulas_body.geometry().top() >= panel.saved_formulas_toggle.geometry().bottom()
    assert panel.formula.geometry().bottom() < panel.saved_formulas_body.geometry().top()
    assert panel.result_group.title() == '3. Result'


@pytest.mark.parametrize('accept', [True, False])
def test_toolbar_restore_chooser_remains_separate_and_undoable(calculator_window, monkeypatch, accept):
    from curvemole.core.calculator import apply_scalar
    _, window = calculator_window
    for curve in window.project.curves:
        apply_scalar(curve, 'y_add', 10)
    original_exec = SpectrumSelectionDialog.exec
    dialogs = []
    def execute(dialog):
        dialogs.append(dialog)
        dialog.all_series.setChecked(True)
        dialog._check_shown(True)
        QTimer.singleShot(0, dialog.accept if accept else dialog.reject)
        return original_exec(dialog)
    monkeypatch.setattr(SpectrumSelectionDialog, 'exec', execute)
    controller = window.restore_original_controller
    controller.rebuild_menu()
    controller.scope_actions[1].trigger()
    assert len(dialogs) == 1
    assert window.undo_stack.count() == int(accept)
    for curve in window.project.curves:
        np.testing.assert_array_equal(curve.y, curve.original_y + (0 if accept else 10))
    if accept:
        window.undo_stack.undo()
        for curve in window.project.curves:
            np.testing.assert_array_equal(curve.y, curve.original_y + 10)


def test_restore_active_does_not_follow_unrelated_row_selection(calculator_window):
    from curvemole.core.calculator import apply_scalar
    _, window = calculator_window
    curves = window.project.curves
    for curve in curves:
        apply_scalar(curve, 'y_multiply', 3)
    select_rows(window, curves[2].id)
    assert window.active_curve_id == curves[0].id
    controller = window.restore_original_controller
    controller.rebuild_menu()
    controller.scope_actions[0].trigger()
    np.testing.assert_array_equal(curves[0].y, curves[0].original_y)
    for curve in curves[1:]:
        np.testing.assert_array_equal(curve.y, curve.original_y * 3)
