from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QStyle,
    QStyleFactory,
    QStyleOptionButton,
    QToolBar,
    QToolButton,
)

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
        option = QStyleOptionButton()
        checkbox.initStyleOption(option)
        # A stretched checkbox's centre can be blank space rather than part of
        # the native indicator/label hit area (notably with Windows styles).
        indicator = checkbox.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, option, checkbox)
        assert not indicator.isEmpty()
        point = indicator.center()
        assert checkbox.rect().contains(point)
        assert checkbox.hitButton(point)
        toggled = QSignalSpy(checkbox.toggled)
        QTest.mouseClick(checkbox, Qt.MouseButton.LeftButton, pos=point)
        app.processEvents()
        assert toggled.count() == 1
        assert toggled.at(0) == [checked]
    assert checkbox.isChecked() == checked


@pytest.mark.parametrize("style_name", ["Windows", "Fusion"])
@pytest.mark.parametrize("direction", [Qt.LayoutDirection.LeftToRight, Qt.LayoutDirection.RightToLeft])
def test_indicator_click_toggles_wide_short_label_checkbox(style_name, direction):
    app = QApplication.instance() or QApplication([])
    checkbox = QCheckBox("Background")
    style = QStyleFactory.create(style_name)
    assert style is not None
    style.setParent(checkbox)
    checkbox.setStyle(style)
    checkbox.setLayoutDirection(direction)
    checkbox.resize(500, 40)
    checkbox.show()
    app.processEvents()
    try:
        assert not checkbox.hitButton(checkbox.rect().center())
        set_checked(app, checkbox, True)
        set_checked(app, checkbox, False)
    finally:
        checkbox.close()
        checkbox.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("background", [False, True])
@pytest.mark.parametrize("points", [False, True])
def test_visible_choices_configure_and_add_quick_peak(quick_window, background, points):
    app, window = quick_window
    selector = window.quick_function_selector
    background_box = window.quick_add_background
    points_box = window.quick_add_manual_points
    assert selector.parent() is background_box.parent() is points_box.parent()
    assert selector.geometry().bottom() < background_box.geometry().top()
    assert background_box.geometry().top() == points_box.geometry().top()
    assert background_box.geometry().right() < points_box.geometry().left()
    set_checked(app, background_box, background)
    set_checked(app, points_box, points)
    QTest.mouseClick(window.quick_add_button, Qt.MouseButton.LeftButton)
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
    assert not window.quick_add_manual_points.isChecked()
    set_checked(app, window.quick_add_manual_points, True)
    selector.setCurrentIndex(selector.findData("gaussian"))
    assert window.quick_add_background.isChecked()
    assert window.quick_add_manual_points.isChecked()
    other = CurveMoleMainWindow(Project())
    try:
        assert other.quick_function_selector.currentData() == "gaussian"
        assert other.quick_add_background.isChecked()
        assert other.quick_add_manual_points.isChecked()
        other.quick_function_selector.setCurrentIndex(other.quick_function_selector.findData("linear"))
        assert other.quick_add_manual_points.isChecked()
    finally:
        other.project.dirty = False
        other.close()
        app.processEvents()


@pytest.mark.parametrize("function_id", ["gaussian", "linear", "cubic_spline"])
def test_both_options_start_off_and_ignore_legacy_add_preferences(quick_window, function_id):
    _app, window = quick_window
    window.settings.setValue(f"quick_add/{function_id}/background", True)
    window.settings.setValue(f"quick_add/{function_id}/manual_points", True)
    window.quick_function_selector.setCurrentIndex(window.quick_function_selector.findData(function_id))
    window._refresh_quick_function_selector()
    assert not window.quick_add_background.isChecked()
    assert not window.quick_add_manual_points.isChecked()
    window.quick_peak()
    if function_id == "gaussian":
        assert not window._pending_component.is_background
        assert window.plot_workspace._continuous_peak_placement
    else:
        component = window.project.model_for(window.project.curves[0].id).components[-1]
        assert component.function_id == function_id
        assert not component.is_background
        assert all(not parameter.fixed for parameter in component.parameters.values())
        assert window.plot_workspace._placement_mode is None


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width", [960, 1440])
def test_quick_add_group_contains_button_and_does_not_raise_toolbar_height(quick_window, theme, width):
    app, window = quick_window
    window.apply_theme(theme)
    window.resize(width, 700)
    app.processEvents()
    toolbar = window.findChild(QToolBar, "Main_toolbar")
    group = window.quick_add_group
    reference = toolbar.widgetForAction(window.add_component_action)
    assert toolbar.widgetForAction(window.quick_peak_action) is None
    assert group.isAncestorOf(window.quick_add_button)
    assert group.isAncestorOf(window.quick_function_selector)
    assert group.isAncestorOf(window.quick_add_background)
    assert group.isAncestorOf(window.quick_add_manual_points)
    assert window.quick_add_title.text() == "Quick Add"
    assert window.quick_add_button.defaultAction() is window.quick_peak_action
    assert not window.quick_add_button.icon().isNull()
    assert window.quick_add_button.text() == "Add"
    assert group.height() <= reference.sizeHint().height()
    assert toolbar.height() <= reference.sizeHint().height() + 10
    if not group.isVisible():
        # Native fonts and DPI can put the group in the toolbar's overflow.
        # Measure the collapsed toolbar above, then verify access there too.
        extension = toolbar.findChild(QToolButton, "qt_toolbar_ext_button")
        assert extension is not None and extension.isVisible()
        QTest.mouseClick(extension, Qt.MouseButton.LeftButton)
        QTest.qWait(250)  # Let the native overflow expansion finish.
    assert group.isVisible()


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
