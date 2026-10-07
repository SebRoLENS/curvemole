from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from curvemole import Curve, Project
from curvemole.gui.app import CurveMoleMainWindow


@pytest.fixture
def quick_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "quick-options.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    settings.setValue("last_quick_function", "gaussian")
    project = Project("Quick Add options")
    x = np.linspace(-3, 3, 101)
    project.add_curve(Curve("Data", x, np.exp(-x*x)))
    window = CurveMoleMainWindow(project)
    window.show()
    app.processEvents()
    yield app, window
    window.plot_workspace.cancel_placement()
    project.dirty = False
    window.close()
    app.processEvents()


def set_checked(app, checkbox, checked):
    if checkbox.isChecked() != checked:
        QTest.mouseClick(checkbox, Qt.MouseButton.LeftButton)
        app.processEvents()
    assert checkbox.isChecked() == checked


@pytest.mark.parametrize("background", [False, True])
@pytest.mark.parametrize("points", [False, True])
def test_visible_choices_configure_and_add_quick_peak(quick_window, background, points):
    app, window = quick_window
    selector = window.quick_function_selector
    background_box = window.quick_add_background
    points_box = window.quick_add_manual_points
    assert selector.parent() is background_box.parent() is points_box.parent()
    assert selector.geometry().bottom() < background_box.geometry().top()
    assert background_box.geometry().bottom() < points_box.geometry().top()
    set_checked(app, background_box, background)
    set_checked(app, points_box, points)
    window.quick_add_function_action.trigger()
    workspace = window.plot_workspace
    assert window._pending_component.is_background == background
    assert workspace._quick_add_placement
    if points:
        assert workspace._manual_points_active
        for x, y in [(-1., .4), (0., 1.), (1., .4)]:
            workspace._add_spline_point(x, y)
        workspace.finish_placement()
    else:
        assert workspace._continuous_peak_placement
        workspace._finish_peak_placement(0., 1., 1.)
        workspace.finish_placement()
    components = window.project.model_for(window.project.curves[0].id).components
    assert len(components) == 1
    assert components[0].function_id == "gaussian"
    assert components[0].is_background == background
    assert all(parameter.fixed for parameter in components[0].parameters.values()) == points
    assert not workspace._quick_add_placement
    window.undo_action.trigger()
    assert not window.project.model_for(window.project.curves[0].id).components
    window.redo_action.trigger()
    assert window.project.model_for(window.project.curves[0].id).components[0].is_background == background


def test_choices_follow_function_and_persist_on_reopening(quick_window):
    app, window = quick_window
    set_checked(app, window.quick_add_background, True)
    set_checked(app, window.quick_add_manual_points, True)
    selector = window.quick_function_selector
    selector.setCurrentIndex(selector.findData("linear"))
    assert not window.quick_add_background.isChecked()
    assert window.quick_add_manual_points.isChecked()
    set_checked(app, window.quick_add_manual_points, False)
    selector.setCurrentIndex(selector.findData("gaussian"))
    assert window.quick_add_background.isChecked()
    assert window.quick_add_manual_points.isChecked()
    other = CurveMoleMainWindow(Project())
    try:
        assert other.quick_function_selector.currentData() == "gaussian"
        assert other.quick_add_background.isChecked()
        assert other.quick_add_manual_points.isChecked()
        other.quick_function_selector.setCurrentIndex(other.quick_function_selector.findData("linear"))
        assert not other.quick_add_manual_points.isChecked()
    finally:
        other.project.dirty = False
        other.close()
        app.processEvents()


def test_background_choice_updates_next_peak_in_active_quick_add(quick_window):
    app, window = quick_window
    window.quick_peak()
    workspace = window.plot_workspace
    workspace._finish_peak_placement(0., 1., 1.)
    set_checked(app, window.quick_add_background, True)
    assert window._pending_component.is_background
    workspace._finish_peak_placement(1., .5, 1.)
    workspace.finish_placement()
    components = window.project.model_for(window.project.curves[0].id).components
    assert [component.is_background for component in components] == [False, True]


def test_switching_point_choice_restarts_only_pending_placement(quick_window):
    app, window = quick_window
    window.quick_peak()
    workspace = window.plot_workspace
    workspace._finish_peak_placement(0., 1., 1.)
    set_checked(app, window.quick_add_manual_points, True)
    assert workspace._manual_points_active
    assert workspace._quick_add_placement
    assert len(window.project.model_for(window.project.curves[0].id).components) == 1
    set_checked(app, window.quick_add_manual_points, False)
    assert workspace._continuous_peak_placement
    assert not workspace._manual_points_active
    assert len(window.project.model_for(window.project.curves[0].id).components) == 1
