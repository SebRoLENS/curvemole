from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.core.data import CurveState
from curvemole.core.serialization import load_project, save_project
from curvemole.gui.app import CurveMoleMainWindow


@pytest.fixture
def point_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    monkeypatch.setattr('curvemole.gui.main_window.QSettings', lambda *args: settings)
    project = Project('Point editor')
    curve = Curve('Measured spectrum', np.arange(9.), [1, 1, 2, 4, 6, 4, 2, 1, 1],
                  sigma_y=np.full(9, .2))
    project.add_curve(curve)
    main = CurveMoleMainWindow(project)
    main.resize(1400, 900)
    main.show()
    main.activateWindow()
    app.processEvents()
    workspace = main.plot_workspace
    workspace.view_box.setRange(xRange=(-1, 9), yRange=(0, 9), padding=0)
    yield app, main, curve
    project.dirty = False
    main.close()
    main.deleteLater()
    app.processEvents()


def begin(app, main):
    main.edit_data_points_action.setChecked(True)
    app.processEvents()
    editor = main.plot_workspace.point_editor
    assert editor.active
    return editor


def test_plugin_point_editor_service_checks_live_context_before_opening(point_window, monkeypatch):
    from curvemole.core.extensions import Contribution, extensions
    from curvemole.gui.plugin_services import PluginServices

    _, main, curve = point_window
    owner = 'test.point_editor'
    monkeypatch.setattr(extensions, 'entries', {
        owner: Contribution(owner, owner, 'Edit points', 'panels', lambda ctx: None)
    })
    service = PluginServices(main.plugin_host, owner)
    editor = main.plot_workspace.point_editor
    for axes in ('invalid', ''):
        with pytest.raises(ValueError, match='x, y or xy'):
            service.edit_data_points(curve.id, axes=axes)
    for curve_id in (None, 'stale-spectrum'):
        with pytest.raises(ValueError, match='selected spectrum changed'):
            service.edit_data_points(curve_id)
    main.project.read_only = True
    with pytest.raises(ValueError, match='editable project'):
        service.edit_data_points(curve.id)
    main.project.read_only = False
    main._thread = object()
    try:
        with pytest.raises(ValueError, match='calculation to finish'):
            service.edit_data_points(curve.id)
    finally:
        main._thread = None
    main.plot_workspace.display_mode.setCurrentIndex(1)
    curve.visible = False
    main.refresh_all()
    with pytest.raises(ValueError, match='Show the active spectrum'):
        service.edit_data_points(curve.id)
    assert not editor.active and main.undo_stack.count() == 0
    curve.visible = True
    main.refresh_all()
    for axes in ('x', 'xy', 'y'):
        service.edit_data_points(curve.id, axes=axes)
        assert editor.active and editor.axes.currentData() == axes
        assert main.edit_data_points_action.isChecked()
        assert main.undo_stack.count() == 0
    editor.finish()
    monkeypatch.setattr(extensions, 'entries', {})
    with pytest.raises(ValueError, match='disabled or unloaded'):
        service.edit_data_points(curve.id)
    assert not editor.active


def scene(workspace, x, y):
    return workspace.view_box.mapViewToScene(QPointF(x, y))


def click(app, workspace, x, y):
    point = workspace.graphics.mapFromScene(scene(workspace, x, y))
    QTest.mouseClick(workspace.graphics.viewport(), Qt.MouseButton.LeftButton, pos=point)
    app.processEvents()


def test_menu_selection_real_drag_delete_and_global_undo_redo(point_window):
    app, main, curve = point_window
    data_menu = next(menu for menu in main.menuBar().actions() if menu.text().replace('&', '') == 'Data').menu()
    assert main.edit_data_points_action in data_menu.actions()
    assert main.plot_workspace.point_editor.isHidden()
    curve.state = CurveState.FITTED
    editor = begin(app, main)
    workspace = main.plot_workspace
    click(app, workspace, 4, 6)
    assert editor.selected_row == 4
    assert editor.delete_button.isEnabled()
    assert 'X = 4, Y = 6' in editor.coordinates.text()
    initial_view = np.array(workspace.view_box.viewRange())
    start = workspace.graphics.mapFromScene(scene(workspace, 4, 6))
    end = workspace.graphics.mapFromScene(scene(workspace, 5, 7))
    QTest.mousePress(workspace.graphics.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(workspace.graphics.viewport(), end, delay=50)
    QTest.mouseRelease(workspace.graphics.viewport(), Qt.MouseButton.LeftButton, pos=end)
    app.processEvents()
    assert curve.x[4] == pytest.approx(5, abs=.06)
    assert curve.y[4] == pytest.approx(7, abs=.06)
    assert main.undo_stack.count() == 1
    assert curve.state == CurveState.MODIFIED
    np.testing.assert_allclose(workspace.view_box.viewRange(), initial_view)
    np.testing.assert_array_equal(curve.original_x, np.arange(9.))
    QTest.keyClick(workspace.graphics.viewport(), Qt.Key.Key_Delete)
    app.processEvents()
    assert len(curve) == 8
    assert 4 not in curve.row_indices
    assert main.undo_stack.count() == 2
    main.undo_action.trigger()
    assert len(curve) == 9
    main.undo_action.trigger()
    assert curve.x[4] == 4
    assert curve.y[4] == 6
    assert curve.state == CurveState.FITTED
    main.redo_action.trigger()
    main.redo_action.trigger()
    assert len(curve) == 8
    editor.done_button.click()
    assert not editor.active
    assert not main.edit_data_points_action.isChecked()


@pytest.mark.parametrize(('axes', 'expected'), [('x', (5, 6)), ('y', (4, 7)), ('xy', (5, 7))])
def test_axis_constraints_preview_atomicity_and_saved_edits(point_window, tmp_path, axes, expected):
    app, main, curve = point_window
    editor = begin(app, main)
    editor.axes.setCurrentIndex(editor.axes.findData(axes))
    workspace = main.plot_workspace
    assert editor.begin_drag(scene(workspace, 4, 6))
    editor.update_drag(scene(workspace, 5, 7))
    assert curve.x[4] == 4 and curve.y[4] == 6  # Drag preview is never saved as real data.
    assert main.undo_stack.count() == 0
    editor.end_drag(scene(workspace, 5, 7))
    np.testing.assert_allclose([curve.x[4], curve.y[4]], expected)
    assert main.undo_stack.count() == 1
    path = tmp_path / 'edited.fitproj'
    save_project(main.project, path)
    restored = load_project(path).curves[0]
    np.testing.assert_allclose([restored.x[4], restored.y[4]], expected)
    assert restored.transformations[-1].operation == 'move_points'


def test_cancel_and_click_away_do_not_change_data(point_window):
    app, main, curve = point_window
    editor = begin(app, main)
    workspace = main.plot_workspace
    assert editor.begin_drag(scene(workspace, 4, 6))
    editor.update_drag(scene(workspace, 5, 7))
    QTest.keyClick(workspace.graphics.viewport(), Qt.Key.Key_Escape)
    app.processEvents()
    assert not editor.active
    assert main.undo_stack.count() == 0
    np.testing.assert_array_equal(curve.x, np.arange(9.))
    begin(app, main)
    click(app, workspace, 4, 8.5)
    assert editor.selected_row is None
    QTest.keyClick(workspace.graphics.viewport(), Qt.Key.Key_Delete)
    assert len(curve) == 9


def test_selection_survives_undo_and_uses_current_row_identity(point_window):
    app, main, curve = point_window
    editor = begin(app, main)
    workspace = main.plot_workspace
    click(app, workspace, 2, 2)
    editor.delete_button.click()
    assert len(curve) == 8
    click(app, workspace, 4, 6)
    assert editor.selected_row == 4
    editor.begin_drag(scene(workspace, 4, 6))
    editor.end_drag(scene(workspace, 5, 7))
    assert curve.transformations[-1].parameters['indices'] == [4]
    assert curve.x[3] == pytest.approx(5)
    main.undo_stack.undo()
    main.undo_stack.undo()
    assert len(curve) == 9
    assert curve.x[4] == 4
    assert editor.selected_row == 4


def test_editing_ends_on_dataset_change_or_placement(point_window):
    app, main, curve = point_window
    editor = begin(app, main)
    workspace = main.plot_workspace
    workspace.begin_peak_placement('Gaussian')
    assert not editor.active
    assert not main.edit_data_points_action.isChecked()
    assert workspace._placement_mode == 'peak'
    begin(app, main)
    assert workspace._placement_mode is None
    other = Curve('Other', [0, 1, 2], [1, 2, 1])
    main.project.add_curve(other)
    main.active_curve_id = other.id
    main.refresh_all()
    assert not editor.active
    assert not main.edit_data_points_action.isChecked()
    assert len(curve) == 9


def test_log_axes_and_waterfall_edit_actual_coordinates(point_window):
    app, main, curve = point_window
    workspace = main.plot_workspace
    other = Curve('First', [1, 2, 3], [1, 2, 3])
    main.project.dataset.series[0].curves.insert(0, other)
    main.refresh_all()
    workspace.display_mode.setCurrentIndex(2)
    workspace.x_offset.setValue(10)
    workspace.y_offset.setValue(20)
    workspace.set_log_x(True)
    workspace.set_log_y(True)
    workspace.view_box.setRange(xRange=(.8, 1.4), yRange=(1.1, 1.7), padding=0)
    editor = begin(app, main)
    assert editor.begin_drag(scene(workspace, np.log10(14), np.log10(26)))
    editor.end_drag(scene(workspace, np.log10(15), np.log10(27)))
    assert curve.x[4] == pytest.approx(5)
    assert curve.y[4] == pytest.approx(7)
    np.testing.assert_allclose(editor._marker.getOriginalDataset(), [[15], [27]])


def test_background_subtracted_view_keeps_y_constraint_in_data_coordinates(point_window):
    app, main, curve = point_window
    workspace = main.plot_workspace
    model = main.project.model_for(curve.id)
    component = Component.create('linear', initial={'slope': .2, 'intercept': 1})
    component.is_background = True
    model.add(component)
    workspace.set_background_subtracted_view(True)
    main.refresh_all()
    editor = begin(app, main)
    editor.axes.setCurrentIndex(editor.axes.findData('x'))
    assert editor.begin_drag(scene(workspace, 4, 6 - 1.8))
    editor.end_drag(scene(workspace, 5, 6 - 1.8))
    assert curve.x[4] == pytest.approx(5)
    assert curve.y[4] == 6
    np.testing.assert_allclose(editor._marker.getOriginalDataset(), [[5], [4]])


def test_deletion_keeps_two_points_and_read_only_disables_edits(point_window, monkeypatch):
    app, main, curve = point_window
    curve.delete_points(range(2, 9))
    main.refresh_all()
    editor = begin(app, main)
    click(app, main.plot_workspace, 1, 1)
    messages = []
    monkeypatch.setattr(main, '_notify', lambda message, **kwargs: messages.append(message))
    editor.delete_button.click()
    assert len(curve) == 2
    assert main.undo_stack.count() == 0
    assert 'at least two' in messages[-1]
    main.project.read_only = True
    main.refresh_all()
    assert not editor.active
    assert not main.edit_data_points_action.isChecked()
    assert len(curve) == 2


def test_keyboard_delete_is_inactive_outside_editor(point_window):
    app, main, curve = point_window
    workspace = main.plot_workspace
    workspace.graphics.setFocus()
    QTest.keyClick(workspace.graphics.viewport(), Qt.Key.Key_Delete)
    app.processEvents()
    assert len(curve) == 9
    assert main.undo_stack.count() == 0


def test_editing_data_point_takes_priority_over_function_handles(point_window):
    app, main, curve = point_window
    component = Component.create('gaussian', initial={
        'center': 4, 'sigma': 1, 'area': 6 * np.sqrt(2 * np.pi)})
    main.project.model_for(curve.id).add(component)
    main.selected_component_id = component.id
    main.refresh_all()
    editor = begin(app, main)
    workspace = main.plot_workspace
    assert editor.begin_drag(scene(workspace, 4, 6))
    editor.end_drag(scene(workspace, 5, 7))
    assert curve.x[4] == pytest.approx(5)
    assert component.parameters['center'].value == 4
    editor.finish()
    assert workspace._handles
    assert all(handle.isEnabled() for handle in workspace._handles)


def test_hidden_dataset_ends_editing(point_window):
    app, main, curve = point_window
    editor = begin(app, main)
    main.plot_workspace.display_mode.setCurrentIndex(1)
    curve.visible = False
    main.refresh_all()
    assert not editor.active
    assert not main.edit_data_points_action.isChecked()


def test_dense_point_drag_disables_sorted_clipping_when_x_crosses_neighbors(point_window):
    app, main, _ = point_window
    x = np.linspace(0, 100, 5000)
    curve = Curve('Dense', x, np.sin(x / 10) + 2)
    main.project.add_curve(curve)
    main.active_curve_id = curve.id
    workspace = main.plot_workspace
    appearance = workspace.plot_appearance()
    appearance['data_style'] = 'Lines + points'
    workspace.set_plot_appearance(appearance)
    workspace.display_mode.setCurrentIndex(1)
    main.refresh_all()
    workspace.view_box.setRange(xRange=(0, 100), yRange=(0, 4), padding=0)
    editor = begin(app, main)
    index = 2500
    assert editor.nearest_index(scene(workspace, x[index], curve.y[index])) == index
    assert editor.begin_drag(scene(workspace, x[index], curve.y[index]))
    editor.update_drag(scene(workspace, 80, 3))
    assert curve.x[index] == x[index]
    item = workspace._data_items[curve.id]
    assert item.opts['symbol'] is None
    assert not item.opts['clipToView']
    assert not editor._points.opts['clipToView']
    editor.end_drag(scene(workspace, 80, 3))
    assert curve.x[index] == pytest.approx(80)
    assert curve.y[index] == pytest.approx(3)
    assert main.undo_stack.count() == 1
