import copy

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolBar, QToolButton

from curvemole import Component, Curve, Project
from curvemole.core.data import Transformation
from curvemole.core.display import DisplayOptions, operation_keys
from curvemole.gui.app import CurveMoleMainWindow


@pytest.fixture
def view_window(tmp_path):
    app = QApplication.instance() or QApplication([])
    project = Project()
    for index in range(3):
        curve = Curve(f'sample {index}', [0, 1, 2, 3], [3, 4, 5, 6], sigma_y=[1, 1, 1, 1])
        project.add_curve(curve)
        background = Component.create('constant', initial={'offset': 2})
        background.is_background = True
        project.model_for(curve.id).add(background)
    window = CurveMoleMainWindow(project)
    window.active_curve_id = project.curves[0].id
    window.refresh_all()
    project.dirty = False
    yield app, window, window.view_options_controller, project.curves
    project.dirty = False
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def menu_action(controller, name):
    controller.rebuild_menu()
    return next(action for action in controller.menu.actions() if action.objectName() == name)


def plotted(window, curve):
    return window.plot_workspace._data_items[curve.id].getOriginalDataset()


def test_view_options_has_its_own_toolbar_group_and_opens_a_menu(view_window):
    app, window, controller, _ = view_window
    toolbar = window.findChild(QToolBar, 'Main_toolbar')
    actions = toolbar.actions()
    index = actions.index(window.view_options_action)
    assert actions[index - 1].isSeparator() and actions[index + 1].isSeparator()
    assert actions.index(window.revert_background_action) < index < actions.index(window.plot_workspace.mask_action)
    assert window.background_subtracted_view_action not in actions
    button = toolbar.widgetForAction(window.view_options_action)
    assert button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert not button.icon().isNull()
    controller.menu.popup(window.mapToGlobal(window.rect().center()))
    app.processEvents()
    assert controller.menu.isVisible()
    action = menu_action(controller, 'view_scope_all')
    QTest.mouseClick(controller.menu, Qt.MouseButton.LeftButton,
                     pos=controller.menu.actionGeometry(action).center())
    app.processEvents()
    assert controller.scope == 'all'
    assert controller.menu.isVisible()
    controller.menu.hide()


def test_current_original_preview_is_isolated_and_restores_normal_display(view_window):
    _, window, controller, curves = view_window
    curves[0].apply_transformation(Transformation('y_multiply', {'value': 4}))
    window.refresh_all()
    before = copy.deepcopy(window.project.to_metadata())
    undo_count = window.undo_stack.count()
    assert controller.apply({curves[0].id: DisplayOptions(original=True)})
    np.testing.assert_array_equal(plotted(window, curves[0])[1], curves[0].original_y)
    np.testing.assert_array_equal(curves[0].y, curves[0].original_y * 4)
    assert not window.plot_workspace._component_items
    assert not window.plot_workspace.residual_plot.listDataItems()
    assert not window.plot_workspace.residual_plot.isVisible()
    assert controller.bar.isVisible() is False  # Parent window is hidden in this test.
    assert not controller.bar.isHidden()
    assert window.project.to_metadata() == before
    assert window.undo_stack.count() == undo_count
    menu_action(controller, 'view_stored').trigger()
    np.testing.assert_array_equal(plotted(window, curves[0])[1], curves[0].y)
    assert window.plot_workspace._component_items
    assert window.plot_workspace.residual_plot.isVisible()
    assert controller.bar.isHidden()


def test_all_scope_groups_types_and_excludes_every_occurrence_only_where_present(view_window):
    _, window, controller, curves = view_window
    curves[0].apply_transformation(Transformation('y_multiply', {'value': 2}))
    curves[0].apply_transformation(Transformation('y_add', {'value': 7}))
    curves[0].apply_transformation(Transformation('y_multiply', {'value': 3}))
    curves[1].apply_transformation(Transformation('y_add', {'value': 2}))
    window.plot_workspace.display_mode.setCurrentIndex(1)
    window.refresh_all()
    controller.scope = 'all'
    controller.rebuild_menu()
    multiplication = next(a for a in controller.menu.actions() if a.data() == 'y_multiply')
    assert '1/3 spectra' in multiplication.text()
    addition = next(a for a in controller.menu.actions() if a.data() == 'y_add')
    assert '2/3 spectra' in addition.text()
    multiplication.trigger()
    np.testing.assert_array_equal(plotted(window, curves[0])[1], curves[0].original_y + 7)
    np.testing.assert_array_equal(plotted(window, curves[1])[1], curves[1].y)
    np.testing.assert_array_equal(plotted(window, curves[2])[1], curves[2].y)
    assert len(controller.for_curve(curves[0].id).excluded) == 2
    menu_action(controller, 'view_original').trigger()
    for curve in curves:
        np.testing.assert_array_equal(plotted(window, curve)[1], curve.original_y)
    controller.scope = 'current'
    menu_action(controller, 'view_stored').trigger()
    np.testing.assert_array_equal(plotted(window, curves[0])[1], curves[0].y)
    assert controller.for_curve(curves[1].id).original


def test_background_modes_work_for_current_and_all_with_waterfall_offsets(view_window):
    _, window, controller, curves = view_window
    ws = window.plot_workspace
    ws.display_mode.setCurrentIndex(2)
    ws.y_offset.setValue(5)
    window.refresh_all()
    controller.apply({curves[0].id: DisplayOptions(background='subtract')})
    np.testing.assert_allclose(plotted(window, curves[0])[1], curves[0].y - 2)
    np.testing.assert_allclose(plotted(window, curves[1])[1], curves[1].y + 5)
    controller.scope = 'all'
    menu_action(controller, 'view_background_subtract').trigger()
    for index, curve in enumerate(curves):
        np.testing.assert_allclose(plotted(window, curve)[1], curve.y - 2 + index * 5)
    menu_action(controller, 'view_stored').trigger()
    for curve in curves:
        curve.apply_transformation(Transformation('background_subtract', operand=np.full(4, 2)))
        window.project.model_for(curve.id).components[0].enabled = False
    window.refresh_all()
    menu_action(controller, 'view_background_restore').trigger()
    for index, curve in enumerate(curves):
        np.testing.assert_allclose(plotted(window, curve)[1], curve.original_y + index * 5)
    assert not ws._component_items


def test_invalid_all_scope_combination_keeps_all_existing_views(view_window, monkeypatch):
    _, window, controller, curves = view_window
    curves[1].delete_points([1])
    curves[1].apply_transformation(Transformation('replace_y', operand=np.array([8, 9, 10])))
    warnings = []
    monkeypatch.setattr('curvemole.gui.view_options.QMessageBox.warning', lambda *args: warnings.append(args))
    updates = {curves[0].id: DisplayOptions(original=True),
               curves[1].id: DisplayOptions(excluded=frozenset(operation_keys(curves[1])[:1]))}
    assert not controller.apply(updates)
    assert warnings
    assert controller.options == {}


def test_preview_autoscale_errors_masks_and_editing_use_consistent_data(view_window):
    _, window, controller, curves = view_window
    curve = curves[0]
    curve.apply_transformation(Transformation('x_add', {'value': 100}))
    curve.apply_transformation(Transformation('y_multiply', {'value': 50}))
    curve.masks[curve.active_mask].excluded[1] = True
    curve.delete_points([2])
    window.refresh_all()
    controller.apply({curve.id: DisplayOptions(original=True)})
    ws = window.plot_workspace
    np.testing.assert_array_equal(plotted(window, curve)[0], curve.original_x)
    assert curve.id in ws._error_items
    ws.auto_range()
    assert ws.plot.viewRange()[0][1] < 10
    assert ws.point_editor.begin()
    assert not controller.replays(curve)
    assert not curve.original_y.flags.writeable
    np.testing.assert_array_equal(plotted(window, curve)[0], curve.x[~curve.effective_mask])
    ws.point_editor.finish()
    controller.apply({curve.id: DisplayOptions(original=True)})
    assert window._ensure_editable()
    assert not controller.replays(curve)


def test_current_choices_follow_navigation_and_clear_for_new_projects(view_window):
    _, window, controller, curves = view_window
    controller.apply({curves[0].id: DisplayOptions(original=True)})
    window.active_curve_id = curves[1].id
    window.refresh_all()
    assert not menu_action(controller, 'view_original').isChecked()
    assert controller.bar.isHidden()
    window.active_curve_id = curves[0].id
    window.refresh_all()
    assert menu_action(controller, 'view_original').isChecked()
    window.project = Project()
    window.active_curve_id = None
    window.refresh_all()
    assert controller.options == {}
    assert not controller.action.isEnabled()


def test_current_scope_can_exclude_individual_repeated_operations(view_window):
    _, window, controller, curves = view_window
    curve = curves[0]
    curve.apply_transformation(Transformation('y_multiply', {'value': 2}, 'Multiply by 2'))
    curve.apply_transformation(Transformation('y_add', {'value': 7}, 'Add 7'))
    curve.apply_transformation(Transformation('y_multiply', {'value': 3}, 'Multiply by 3'))
    window.refresh_all()
    menu_action(controller, 'view_operation_2').trigger()
    np.testing.assert_array_equal(plotted(window, curve)[1], curve.original_y * 2 + 7)
    menu_action(controller, 'view_operation_0').trigger()
    np.testing.assert_array_equal(plotted(window, curve)[1], curve.original_y + 7)
    assert len(controller.for_curve(curve.id).excluded) == 2


def test_all_scope_also_applies_to_hidden_spectra(view_window):
    _, window, controller, curves = view_window
    hidden = curves[2]
    hidden.apply_transformation(Transformation('y_multiply', {'value': 5}))
    hidden.visible = False
    window.plot_workspace.display_mode.setCurrentIndex(1)
    window.refresh_all()
    controller.scope = 'all'
    menu_action(controller, 'view_original').trigger()
    assert controller.for_curve(hidden.id).original
    hidden.visible = True
    window.refresh_all()
    np.testing.assert_array_equal(plotted(window, hidden)[1], hidden.original_y)
