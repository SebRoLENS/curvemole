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
from curvemole.core.functions import formula_definition
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
    if points:
        assert window._pending_component.is_background == background
        assert workspace._quick_add_placement
        assert workspace._continuous_peak_placement
        assert not workspace._manual_points_active
        workspace._finish_peak_placement(0., 1., 1.)
        workspace.finish_placement()
    else:
        assert window._pending_component is None
        assert workspace._placement_mode is None
        assert not workspace._quick_add_placement
    components = window.project.model_for(window.project.curves[0].id).components
    assert len(components) == 1
    assert components[0].function_id == "gaussian"
    assert components[0].is_background == background
    assert all(not parameter.fixed for parameter in components[0].parameters.values())
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
    reference = toolbar.widgetForAction(window.open_action)
    assert toolbar.widgetForAction(window.quick_peak_action) is None
    assert group.isAncestorOf(window.quick_add_button)
    assert group.isAncestorOf(window.quick_function_selector)
    assert group.isAncestorOf(window.quick_add_background)
    assert group.isAncestorOf(window.quick_add_manual_points)
    assert group.isAncestorOf(window.function_info_button)
    assert window.quick_add_title.text() == "Functions"
    assert window.quick_add_button.defaultAction() is window.quick_peak_action
    assert not window.quick_add_button.icon().isNull()
    assert window.quick_add_button.text() == "Add function"
    assert window.quick_add_button.iconSize() == reference.iconSize()
    assert window.quick_add_button.sizeHint().height() == reference.sizeHint().height()
    assert group.height() <= reference.sizeHint().height() + 4
    assert toolbar.height() <= reference.sizeHint().height() + 14
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
    set_checked(app, window.quick_add_manual_points, True)
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
    set_checked(app, window.quick_add_manual_points, True)
    window.quick_peak()
    workspace = window.plot_workspace
    workspace._finish_peak_placement(0., 1., 1.)
    set_checked(app, window.quick_add_manual_points, False)
    assert workspace._placement_mode is None
    assert not workspace._quick_add_placement
    assert len(window.project.model_for(window.project.curves[0].id).components) == 1
    window.quick_peak()
    assert len(window.project.model_for(window.project.curves[0].id).components) == 2


def activate_data(window, x, y):
    curve = Curve("Automatic estimate", x, y)
    window.project.add_curve(curve)
    window.active_curve_id = curve.id
    window.refresh_all()
    return curve


@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("function_id", ["gaussian", "lorentzian", "voigt", "pseudo_voigt"])
def test_automatic_click_estimates_signed_peak_and_undoes(quick_window, function_id, sign):
    app, window = quick_window
    x = np.linspace(-10, 10, 1001)
    curve = activate_data(window, x, 7 + sign * 5 * np.exp(-.5 * ((x-2)/.6)**2))
    window.quick_function_selector.setCurrentIndex(window.quick_function_selector.findData(function_id))
    set_checked(app, window.quick_add_manual_points, False)
    QTest.mouseClick(window.quick_add_button, Qt.MouseButton.LeftButton)
    components = window.project.model_for(curve.id).components
    assert len(components) == 1
    component = components[0]
    assert component.parameters["center"].value == pytest.approx(2, abs=.03)
    assert component.parameters["area"].value * sign > 0
    values = {name: p.value for name, p in component.parameters.items()}
    height = window.registry.get(function_id).evaluate(np.array([2.]), values)[0]
    assert height == pytest.approx(sign * 5, rel=.01)
    assert window.plot_workspace._placement_mode is None
    window.undo_action.trigger()
    assert not window.project.model_for(curve.id).components


def test_automatic_clicks_find_remaining_residual_peaks_and_respect_masks(quick_window):
    app, window = quick_window
    x = np.linspace(-15, 15, 3001)
    y = 5*np.exp(-.5*((x+4)/.5)**2) + 3*np.exp(-.5*((x-4)/.5)**2)
    curve = activate_data(window, x[::-1], y[::-1])
    for _ in range(2):
        QTest.mouseClick(window.quick_add_button, Qt.MouseButton.LeftButton)
    components = window.project.model_for(curve.id).components
    assert [c.parameters["center"].value for c in components] == pytest.approx([-4, 4], abs=.03)
    assert components[0].parameters["sigma"].value == pytest.approx(.5, rel=.02)
    window.undo_action.trigger()
    window.undo_action.trigger()
    curve.add_mask("Exclude strongest peak").excluded[:] = curve.x < 0
    QTest.mouseClick(window.quick_add_button, Qt.MouseButton.LeftButton)
    assert window.project.model_for(curve.id).components[0].parameters["center"].value == pytest.approx(4, abs=.03)


def test_automatic_custom_peak_uses_explicit_parameter_roles(quick_window):
    app, window = quick_window
    definition = formula_definition("role_peak", "Role peak", "h*exp(-.5*((x-p)/s)**2)", kind="peak")
    definition.custom_metadata["peak_roles"] = {"h": "height", "p": "center", "s": "sigma"}
    window.registry.register(definition)
    window._refresh_quick_function_selector(preferred="role_peak")
    x = np.linspace(-10, 10, 1001)
    curve = activate_data(window, x, 4*np.exp(-.5*((x-2)/.7)**2))
    QTest.mouseClick(window.quick_add_button, Qt.MouseButton.LeftButton)
    component = window.project.model_for(curve.id).components[0]
    assert component.parameters["p"].value == pytest.approx(2, abs=.03)
    assert component.parameters["s"].value == pytest.approx(.7, rel=.02)
    assert component.parameters["h"].value == pytest.approx(4, rel=.02)


@pytest.mark.parametrize("x,y", [([0, 1], [2, 2]), ([0, 1, 2], [4, 4, 4]), ([0, 1, 2], [1, 2, 3])])
def test_automatic_estimates_remain_finite_for_short_flat_or_monotonic_data(quick_window, x, y):
    app, window = quick_window
    curve = activate_data(window, x, y)
    QTest.mouseClick(window.quick_add_button, Qt.MouseButton.LeftButton)
    component = window.project.model_for(curve.id).components[0]
    assert all(np.isfinite(p.value) for p in component.parameters.values())
    assert component.parameters["sigma"].value > 0


def test_no_usable_data_reports_error_without_adding(quick_window, monkeypatch):
    _app, window = quick_window
    curve = window.project.curves[0]
    curve.add_mask("All points").excluded[:] = True
    errors = []
    monkeypatch.setattr(window, "_show_error", lambda title, error: errors.append(str(error)))
    window.quick_peak()
    assert errors and "no usable points" in errors[0]
    assert not window.project.model_for(curve.id).components


def test_selecting_automatic_peak_during_placement_does_not_insert(quick_window):
    app, window = quick_window
    set_checked(app, window.quick_add_manual_points, True)
    window.quick_peak()
    window.quick_function_selector.setCurrentIndex(window.quick_function_selector.findData("lorentzian"))
    assert window._pending_component is None
    assert not window.project.model_for(window.active_curve_id).components
    assert window.plot_workspace._placement_mode is None


def test_function_details_follow_selector_copy_formula_and_keep_advanced_add(quick_window, monkeypatch):
    app, window = quick_window
    window.function_info_action.trigger()
    dialog = window._function_info_dialog
    assert dialog.isVisible()
    assert dialog.function_selector.currentData() == "gaussian"
    assert {dialog.function_selector.itemData(i) for i in range(dialog.function_selector.count())} == set(window.registry.identifiers())
    assert "sigma" in dialog.browser.toPlainText()
    assert "FWHM" in dialog.browser.toPlainText()
    window.quick_function_selector.setCurrentIndex(window.quick_function_selector.findData("linear"))
    assert "f(x) = intercept + slope*x" in dialog.browser.toPlainText()
    assert "slope*x" in window.function_info_action.toolTip()
    assert dialog.function_selector.currentData() == "linear"
    dialog.function_selector.setCurrentIndex(dialog.function_selector.findData("constant"))
    assert window.quick_function_selector.currentData() == "constant"
    assert window.settings.value("last_quick_function") == "constant"
    assert "f(x) = offset" in dialog.browser.toPlainText()
    QTest.mouseClick(dialog.copy_button, Qt.MouseButton.LeftButton)
    assert app.clipboard().text() == "f(x) = offset"
    assert not window.project.model_for(window.active_curve_id).components
    from curvemole.gui.dialogs import AddComponentDialog
    selected = []
    def accept(dialog):
        selected.append(dialog.function.currentData())
        dialog.manual_points.setChecked(False)
        return dialog.DialogCode.Accepted
    monkeypatch.setattr(AddComponentDialog, "exec", accept)
    assert dialog.add_button.text() == "Add function…"
    QTest.mouseClick(dialog.add_button, Qt.MouseButton.LeftButton)
    assert selected == ["constant"]
    assert not dialog.isVisible()
    assert window.project.model_for(window.active_curve_id).components[-1].function_id == "constant"
    window.undo_action.trigger()
    assert not window.project.model_for(window.active_curve_id).components
    assert window.add_component_action.shortcut().toString() == "Ctrl+A"


def test_function_details_handle_custom_formulas_and_plugins(quick_window):
    _app, window = quick_window
    definition = formula_definition("custom_info", "<Custom>", "a*x+b")
    window.registry.register(definition)
    window._refresh_quick_function_selector(preferred="custom_info")
    window.function_info_action.trigger()
    dialog = window._function_info_dialog
    assert "<Custom>" in dialog.browser.toPlainText()
    assert "f(x) = a*x+b" in dialog.browser.toPlainText()
    definition.custom_metadata = {"plugin_owner": "external", "plugin_name": "External"}
    window._refresh_quick_function_selector(preferred="custom_info")
    assert "not supplied a formula" in dialog.browser.toPlainText()
    assert "External" in dialog.browser.toPlainText()
    assert not dialog.copy_button.isEnabled()
    late = formula_definition("late_info", "New plugin function", "b*x")
    late.custom_metadata.update(plugin_owner="external", plugin_name="External")
    window.registry.register(late)
    window._refresh_quick_function_selector()
    index = dialog.function_selector.findData("late_info")
    assert index >= 0
    dialog.function_selector.setCurrentIndex(index)
    assert window.quick_function_selector.currentData() == "late_info"
    assert "f(x) = b*x" in dialog.browser.toPlainText()


def test_browsing_function_details_cancels_pending_placement_without_inserting(quick_window):
    app, window = quick_window
    set_checked(app, window.quick_add_manual_points, True)
    window.quick_peak()
    window.plot_workspace._finish_peak_placement(0., 1., 1.)
    model = window.project.model_for(window.active_curve_id)
    undo_count = window.undo_stack.count()
    window.function_info_action.trigger()
    selector = window._function_info_dialog.function_selector
    for identifier in ("cubic_spline", "polynomial", "gaussian"):
        selector.setCurrentIndex(selector.findData(identifier))
        assert window.quick_function_selector.currentData() == identifier
        assert len(model.components) == 1
        assert window.undo_stack.count() == undo_count
        assert window.plot_workspace._placement_mode is None
        assert window._pending_component is None
