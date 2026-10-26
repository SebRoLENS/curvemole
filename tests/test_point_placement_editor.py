from __future__ import annotations

import math

import numpy as np
import pytest
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from curvemole import Curve, Project
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.manual_points_live import _stored_points


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    project = Project("Point editing")
    curve = Curve("Spectrum", np.arange(1., 10.), np.arange(1., 10.))
    project.add_curve(curve)
    main = CurveMoleMainWindow(project)
    main.resize(1450, 900)
    main.show()
    main.activateWindow()
    app.processEvents()
    yield app, main, curve
    main.project.dirty = False
    main.close()
    main.deleteLater()
    app.processEvents()


def start(app, main, function_id="linear"):
    main.settings.setValue(f"quick_add_controls/{function_id}/manual_points", True)
    main.quick_function_selector.setCurrentIndex(main.quick_function_selector.findData(function_id))
    main.quick_peak()
    workspace = main.plot_workspace
    workspace.view_box.setRange(xRange=(0, 10), yRange=(0, 10), padding=0)
    app.processEvents()
    return workspace


def pixel(workspace, x, y):
    x_offset, y_offset = workspace._active_display_offsets()
    x, y = x + x_offset, y + y_offset
    if workspace.plot.ctrl.logXCheck.isChecked():
        x = math.log10(x)
    if workspace.plot.ctrl.logYCheck.isChecked():
        y = math.log10(y)
    point = workspace.view_box.mapViewToScene(QPointF(x, y))
    result = workspace.graphics.mapFromScene(point)
    assert workspace.graphics.viewport().rect().contains(result)
    return result


def click(app, workspace, x, y):
    QTest.mouseClick(workspace.graphics.viewport(), Qt.MouseButton.LeftButton,
                     pos=pixel(workspace, x, y))
    app.processEvents()


def drag(app, workspace, origin, destination):
    begin, end = pixel(workspace, *origin), pixel(workspace, *destination)
    QTest.mousePress(workspace.graphics.viewport(), Qt.MouseButton.LeftButton, pos=begin)
    QTest.mouseMove(workspace.graphics.viewport(), end, delay=30)
    QTest.mouseRelease(workspace.graphics.viewport(), Qt.MouseButton.LeftButton, pos=end)
    app.processEvents()


def mode(workspace, value):
    combo = workspace.placement_editor.mode
    combo.setCurrentIndex(combo.findData(value))


@pytest.mark.parametrize("function_id", ["linear", "cubic_spline"])
def test_delete_clicked_point_minimum_undo_and_finish(window, function_id):
    app, main, curve = window
    w = start(app, main, function_id)
    for point in [(2, 2), (4, 7), (7, 3)]:
        click(app, w, *point)
    before = list(w._spline_points)
    mode(w, "delete")
    click(app, w, 9, 9)  # Clicking empty space never deletes a distant point.
    assert w._spline_points == before
    click(app, w, 4, 7)
    assert len(w._spline_points) == 2
    assert w.finish_placement_button.isEnabled()
    click(app, w, 2, 2)
    assert len(w._spline_points) == 1
    assert not w.finish_placement_button.isEnabled()
    w.finish_placement()  # Cannot commit an underdetermined function.
    assert not main.project.model_for(curve.id).components
    w.undo_point_button.click()
    w.undo_point_button.click()
    assert w._spline_points == before
    w.finish_placement_button.click()
    components = main.project.model_for(curve.id).components
    assert len(components) == 1
    if function_id == "linear":
        np.testing.assert_allclose(_stored_points(components[0]), sorted(before))
    else:
        np.testing.assert_allclose(components[0].metadata["x_nodes"], sorted(x for x, _ in before))
    assert main.undo_stack.count() == 1
    main.undo_stack.undo()
    assert not main.project.model_for(curve.id).components
    np.testing.assert_array_equal(curve.x, np.arange(1., 10.))
    np.testing.assert_array_equal(curve.y, np.arange(1., 10.))


@pytest.mark.parametrize("function_id", ["linear", "cubic_spline"])
def test_move_point_live_preview_one_undo_and_cancel(window, function_id):
    app, main, curve = window
    w = start(app, main, function_id)
    for point in [(2, 2), (4, 7), (7, 3)]:
        click(app, w, *point)
    before = list(w._spline_points)
    view = np.asarray(w.view_box.viewRange())
    old_preview = w._placement_items[-1].getData()[1].copy()
    mode(w, "move")
    click(app, w, 8, 8)
    assert w._spline_points == before
    drag(app, w, before[1], (5, 6))
    assert len(w._spline_points) == 3
    np.testing.assert_allclose(w._spline_points[1], (5, 6), atol=.05)
    assert not np.array_equal(w._placement_items[-1].getData()[1], old_preview)
    np.testing.assert_allclose(w.view_box.viewRange(), view)
    assert main.undo_stack.count() == 0  # Temporary edits are not project mutations.
    w.undo_point_button.click()
    assert w._spline_points == before
    w.cancel_placement()
    assert not main.project.model_for(curve.id).components
    assert w.placement_editor.mode.isHidden()
    w.begin_spline_placement("New function")
    assert w.placement_editor.mode.currentData() == "add"
    assert not w.undo_point_button.isEnabled()
    w.cancel_placement()
    w.begin_peak_placement("Peak")
    assert w.placement_editor.mode.isHidden()
    w.cancel_placement()


def test_empty_space_drag_pans_and_move_cannot_merge_points(window):
    app, main, _ = window
    w = start(app, main)
    for point in [(2, 2), (4, 7)]:
        click(app, w, *point)
    before = list(w._spline_points)
    mode(w, "move")
    view = np.asarray(w.view_box.viewRange())
    drag(app, w, (8, 8), (9, 8))
    assert not np.allclose(w.view_box.viewRange(), view)
    assert w._spline_points == before
    w.view_box.setRange(xRange=(0, 10), yRange=(0, 10), padding=0)
    # Exact collision guard uses data coordinates, without pixel rounding.
    editor = w.placement_editor
    editor._drag_index, editor._drag_before = 0, list(before)

    class Event:
        def isStart(self): return False
        def isFinish(self): return True
        def scenePos(self): return w.view_box.mapViewToScene(QPointF(before[1][0], 5))

    assert editor.drag(Event())
    assert w._spline_points == before
    w.cancel_placement()


@pytest.mark.parametrize("axes", ["linear", "log", "reversed", "waterfall"])
def test_point_hit_testing_respects_plot_coordinates(window, axes):
    app, main, _ = window
    w = start(app, main)
    if axes == "waterfall":
        extra = Curve("Other spectrum", np.arange(1., 10.), np.arange(1., 10.))
        main.project.add_curve(extra)
        main.active_curve_id = extra.id
        main.refresh_all()
        w.display_mode.setCurrentText(w.tr("Waterfall"))
        w.x_offset.setValue(2)
        w.y_offset.setValue(3)
        w.view_box.setRange(xRange=(0, 14), yRange=(0, 14), padding=0)
    elif axes == "log":
        w.set_log_x(True)
        w.set_log_y(True)
        w.view_box.setRange(xRange=(0, 1), yRange=(0, 1), padding=0)
    elif axes == "reversed":
        w.set_reverse_x(True)
        w.set_reverse_y(True)
    app.processEvents()
    click(app, w, 2, 2)
    click(app, w, 4, 7)
    mode(w, "move")
    drag(app, w, (4, 7), (5, 6))
    np.testing.assert_allclose(w._spline_points[1], (5, 6), atol=.08)
    mode(w, "delete")
    click(app, w, 5, 6)
    assert len(w._spline_points) == 1
    w.cancel_placement()
