"""The model panel selects one uncertainty method for every spectrum."""

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from curvemole import Component, Curve, Fitter, Project
from curvemole.core.analysis_errors import recorded_analysis_error, selected_method
from curvemole.core.serialization import load_project, save_project
from curvemole.core.uncertainty import ResamplingResult
from curvemole.gui.main_window import MainWindow


@pytest.fixture
def selector_window():
    app = QApplication.instance() or QApplication([])
    project = Project("Display choices")
    first = Curve("Analysed spectrum", np.arange(5.), [1., 1.2, .8, 1.1, 1.],
                  sigma_y=np.full(5, .1))
    second = Curve("No analysis", np.arange(5.), np.ones(5))
    for curve in (first, second):
        project.add_curve(curve)
        project.model_for(curve.id).add(Component.create("constant", initial={"offset": 1.}))
    baseline = Fitter().fit_single(first, project.model_for(first.id))
    window = MainWindow(project)
    yield app, window, baseline
    window.project.dirty = False
    window.close()
    window.deleteLater()
    app.processEvents()


def store(window, baseline, method, minus, plus):
    path = baseline.free_parameter_paths[0]
    value = baseline.parameters[path].value
    result = ResamplingResult(method, 20, 20, 0, 42, [path],
                              np.full((20, 1), value),
                              {path: (value - minus, value + plus)}, .95, {})
    window._store_uncertainty_result(path.split(".", 1)[0], baseline, result)
    window.model_panel.refresh_parameters()


def click_header(window, section):
    header = window.model_panel.parameters.horizontalHeader()
    window.model_panel.parameters.horizontalScrollBar().setValue(header.sectionPosition(section))
    point = QPoint(header.sectionViewportPosition(section) + header.sectionSize(section) // 2,
                   header.height() // 2)
    QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=point)


def test_empty_selector_explains_and_opens_uncertainty_tool(selector_window):
    app, window, _baseline = selector_window
    window.show()
    window.uncertainty_dock.hide()
    window.activate_tool_dock(window.model_dock)
    app.processEvents()
    selector = window.model_panel.display_method
    assert not hasattr(window.uncertainty_panel, "display_method")
    assert selector.isEnabled()
    assert not selector.method_actions
    assert window.uncertainty_dock.isHidden()
    revision = window.project.revision
    click_header(window, 3)
    app.processEvents()
    assert selector.isVisible()
    assert "first run an analysis" in selector.empty_message.text()
    assert '<a href="uncertainty">' in selector.empty_message.text()
    selector.empty_message.linkActivated.emit("uncertainty")
    app.processEvents()
    assert not selector.isVisible()
    assert not window.uncertainty_dock.isHidden()
    assert window.uncertainty_dock in window.tabifiedDockWidgets(window.model_dock)
    assert window.project.revision == revision


def test_global_choice_stays_selected_on_missing_spectrum_and_survives_save(selector_window, tmp_path):
    app, window, baseline = selector_window
    first, second = window.project.curves
    store(window, baseline, "residual_bootstrap", .2, .4)
    store(window, baseline, "parametric_monte_carlo", .1, .3)
    selector = window.model_panel.display_method
    assert len(selector.method_actions) == 2
    selector.method_actions["parametric_monte_carlo"].trigger()
    assert window.model_panel.parameters.item(0, 3).text() == "−0.1 / +0.3"
    selector.method_actions["residual_bootstrap"].trigger()
    assert window.model_panel.parameters.item(0, 3).text() == "−0.2 / +0.4"
    window._set_active_curve(second.id)
    assert selector.current_method == "residual_bootstrap"
    assert "residual_bootstrap" in selector.method_actions
    assert window.model_panel.parameters.item(0, 3).text() == "—"
    window._set_active_curve(first.id)
    assert selector.current_method == "residual_bootstrap"
    assert window.model_panel.parameters.item(0, 3).text() == "−0.2 / +0.4"
    window.project.path = tmp_path / "choices.fitproj"
    assert window.save_project()
    restored = load_project(window.project.path)
    other = MainWindow(restored)
    try:
        assert other.model_panel.display_method.current_method == "residual_bootstrap"
        assert other.model_panel.parameters.item(0, 3).text() == "−0.2 / +0.4"
        other._set_active_curve(second.id)
        assert other.model_panel.display_method.current_method == "residual_bootstrap"
        assert other.model_panel.parameters.item(0, 3).text() == "—"
    finally:
        restored.dirty = False
        other.close()
        other.deleteLater()
        app.processEvents()


def test_covariance_is_available_with_its_recorded_limits(selector_window):
    _app, window, baseline = selector_window
    first = window.project.curves[0]
    path = baseline.free_parameter_paths[0]
    estimate = baseline.parameters[path]
    window._store_uncertainty_result(first.id, baseline, baseline)
    window.project.results.pop("uncertainty_display_method", None)
    revision = window.project.revision
    window.model_panel.refresh_parameters()
    assert window.model_panel.display_method.current_method == "covariance"
    assert len(window.model_panel.display_method.method_actions) == 1
    assert recorded_analysis_error(window.project, first.id, path) == pytest.approx(
        (estimate.value - estimate.ci_low, estimate.ci_high - estimate.value))
    assert window.model_panel.parameters.item(0, 3).text() != "—"
    assert window.model_panel.parameters.item(0, 2).text() == f"{estimate.standard_error:.5g}"
    assert window.project.revision == revision


def test_global_selector_is_available_even_without_active_parameter_rows(selector_window):
    _app, window, baseline = selector_window
    store(window, baseline, "block_bootstrap", .1, .2)
    window.model_panel.set_context(window.project, None, 0)
    assert window.model_panel.display_method.isEnabled()
    assert window.model_panel.display_method.current_method == "block_bootstrap"
    assert window.model_panel.parameters.rowCount() == 0


def select_remote_function(window):
    panel = window.model_panel
    second = window.project.curves[1]
    component = window.project.model_for(second.id).components[0]
    panel.show_all_functions.setChecked(True)
    item = next(panel.components.item(row) for row in range(panel.components.count())
                if panel.components.item(row).data(Qt.ItemDataRole.UserRole) == component.id)
    panel.components.clearSelection()
    panel.components.setCurrentItem(item)
    item.setSelected(True)
    return second


def test_show_all_functions_choice_is_global_and_does_not_use_other_methods(selector_window):
    _app, window, baseline = selector_window
    first, second = window.project.curves
    store(window, baseline, "residual_bootstrap", .2, .4)
    other_fit = Fitter().fit_single(second, window.project.model_for(second.id))
    store(window, other_fit, "block_bootstrap", .1, .3)
    store(window, other_fit, "parametric_monte_carlo", .4, .6)
    select_remote_function(window)
    selector = window.model_panel.display_method
    assert window.active_curve_id == first.id
    assert selector.curve_id == second.id
    selector.method_actions["block_bootstrap"].trigger()
    assert window.project.results["uncertainty_display_method"] == "block_bootstrap"
    assert window.model_panel.parameters.item(0, 3).text() == "−0.1 / +0.3"
    assert window.active_curve_id == first.id
    window.model_panel.show_all_functions.setChecked(False)
    assert window.model_panel.display_method.current_method == "block_bootstrap"
    assert window.model_panel.parameters.item(0, 3).text() == "—"


def test_empty_remote_function_link_opens_analysis_for_its_spectrum(selector_window):
    _app, window, _baseline = selector_window
    second = select_remote_function(window)
    assert window.model_panel.display_method.current_method is None
    window.model_panel.display_method.empty_message.linkActivated.emit("uncertainty")
    assert window.active_curve_id == second.id
    assert window.uncertainty_panel.results.curve_id == second.id
    assert not window.uncertainty_dock.isHidden()


def test_methods_on_different_spectra_are_listed_together_without_fallback(selector_window):
    _app, window, baseline = selector_window
    first, second = window.project.curves
    store(window, baseline, "residual_bootstrap", .2, .4)
    second_fit = Fitter().fit_single(second, window.project.model_for(second.id))
    store(window, second_fit, "block_bootstrap", .1, .3)
    selector = window.model_panel.display_method
    assert len(selector.method_actions) == 2
    assert "block_bootstrap" in selector.method_actions
    selector.method_actions["block_bootstrap"].trigger()
    assert selected_method(window.project, first.id) is None
    assert window.model_panel.parameters.item(0, 3).text() == "—"
    assert "Block bootstrap: no valid interval" in window.model_panel.parameters.item(0, 3).toolTip()
    assert window.model_panel.parameters.item(0, 2).text() != "—"
    window._set_active_curve(second.id)
    assert selector.current_method == "block_bootstrap"
    assert window.model_panel.parameters.item(0, 3).text() == "−0.1 / +0.3"
    selector.method_actions["residual_bootstrap"].trigger()
    assert selected_method(window.project, second.id) is None
    assert window.model_panel.parameters.item(0, 3).text() == "—"
    window._set_active_curve(first.id)
    assert selector.current_method == "residual_bootstrap"
    assert window.model_panel.parameters.item(0, 3).text() == "−0.2 / +0.4"


def test_new_analysis_preserves_explicit_global_choice(selector_window):
    _app, window, baseline = selector_window
    store(window, baseline, "residual_bootstrap", .2, .4)
    store(window, baseline, "parametric_monte_carlo", .1, .3)
    selector = window.model_panel.display_method
    selector.method_actions["parametric_monte_carlo"].trigger()
    store(window, baseline, "residual_bootstrap", .4, .8)
    assert selector.current_method == "parametric_monte_carlo"
    assert window.model_panel.parameters.item(0, 3).text() == "−0.1 / +0.3"


def test_partial_result_on_another_spectrum_refreshes_global_methods(selector_window):
    _app, window, _baseline = selector_window
    first, second = window.project.curves
    second_fit = Fitter().fit_single(second, window.project.model_for(second.id))
    path = second_fit.free_parameter_paths[0]
    value = second_fit.parameters[path].value
    result = ResamplingResult("block_bootstrap", 20, 20, 0, 42, [path],
                              np.full((20, 1), value), {path: (value - .1, value + .3)}, .95, {})
    window._partial_uncertainty_result([(second.id, second_fit, result)])
    assert window.active_curve_id == first.id
    assert window.model_panel.display_method.current_method == "block_bootstrap"
    assert window.model_panel.parameters.item(0, 3).text() == "—"


def test_header_opens_method_menu_and_real_click_selects_global_errors(selector_window):
    app, window, baseline = selector_window
    store(window, baseline, "residual_bootstrap", .2, .4)
    store(window, baseline, "parametric_monte_carlo", .1, .3)
    window.resize(1000, 700)
    window.show()
    window.activate_tool_dock(window.model_dock)
    app.processEvents()
    panel = window.model_panel
    menu = panel.display_method
    assert isinstance(menu, QMenu)
    assert not hasattr(panel, "uncertainty_display_label")
    click_header(window, 0)
    app.processEvents()
    assert not menu.isVisible()
    click_header(window, 3)
    app.processEvents()
    assert menu.isVisible()
    assert set(menu.method_actions) == {"residual_bootstrap", "parametric_monte_carlo"}
    assert menu.method_actions["residual_bootstrap"].isChecked()
    action = menu.method_actions["parametric_monte_carlo"]
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
    app.processEvents()
    assert not menu.isVisible()
    assert menu.current_method == "parametric_monte_carlo"
    assert sum(action.isChecked() for action in menu.method_actions.values()) == 1
    assert panel.parameters.item(0, 3).text() == "−0.1 / +0.3"
    window._set_active_curve(window.project.curves[1].id)
    assert menu.current_method == "parametric_monte_carlo"
    assert panel.parameters.item(0, 3).text() == "—"


def test_legacy_conflicting_choices_migrate_to_one_saved_project_choice(selector_window, tmp_path):
    app, window, baseline = selector_window
    first, second = window.project.curves
    store(window, baseline, "parametric_monte_carlo", .2, .4)
    second_fit = Fitter().fit_single(second, window.project.model_for(second.id))
    store(window, second_fit, "block_bootstrap", .1, .3)
    project = window.project
    project.results.pop("uncertainty_display_method")
    project.results["uncertainty_display_method_by_curve"] = {
        first.id: "monte_carlo", second.id: "block_bootstrap"}
    restored = load_project(save_project(project, tmp_path / "old-choices.fitproj"))
    assert restored.results["uncertainty_display_method"] == "parametric_monte_carlo"
    assert "uncertainty_display_method_by_curve" not in restored.results
    other = MainWindow(restored)
    try:
        other._set_active_curve(second.id)
        assert other.model_panel.display_method.current_method == "parametric_monte_carlo"
        assert other.model_panel.parameters.item(0, 3).text() == "—"
        saved = load_project(save_project(restored, tmp_path / "migrated.fitproj"))
        assert saved.results["uncertainty_display_method"] == "parametric_monte_carlo"
        assert selected_method(saved, second.id) is None
    finally:
        restored.dirty = False
        other.close()
        other.deleteLater()
        app.processEvents()
