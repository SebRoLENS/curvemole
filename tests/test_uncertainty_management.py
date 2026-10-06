"""Deleting analyses and surfacing incomplete numerical-stability checks."""

from dataclasses import asdict

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QLabel

from curvemole import Component, Curve, Fitter, Project
from curvemole.core.data import CurveState
from curvemole.core.serialization import load_project, save_project
from curvemole.core.uncertainty import AdaptiveReplicateSettings, ResamplingResult
from curvemole.gui.main_window import MainWindow


@pytest.fixture
def management_window():
    app = QApplication.instance() or QApplication([])
    project = Project("Analysis management")
    baselines = []
    for index in range(2):
        curve = Curve(f"Spectrum {index}", np.arange(5.), [1., 1.2, .8, 1.1, 1.])
        project.add_curve(curve)
        model = project.model_for(curve.id)
        model.add(Component.create("constant", initial={"offset": 1.}))
        baselines.append(Fitter().fit_single(curve, model))
    window = MainWindow(project)
    yield app, window, baselines
    window.project.dirty = False
    window.close()
    window.deleteLater()
    app.processEvents()


def result(baseline, method="residual_bootstrap", converged=None):
    path = baseline.free_parameter_paths[0]
    value = baseline.parameters[path].value
    configuration = {}
    if converged is not None:
        configuration["adaptive"] = {
            **asdict(AdaptiveReplicateSettings(3, 2, .05, 2, 7)),
            "converged": converged, "attempted": 7, "stable_checks": 2 if converged else 0,
            "stop_reason": "stable_intervals" if converged else "maximum_attempts", "history": [],
        }
    return ResamplingResult(method, 7, 7, 0, 42, [path], np.full((7, 1), value),
                            {path: (value - .1, value + .3)}, .95, configuration)


def choose(window, method):
    panel = window.uncertainty_panel
    panel.method.setCurrentIndex(panel.method.findData(method))


def item(window, index=0):
    return window.curve_tree.topLevelItem(0).child(index)


def test_delete_selected_method_everywhere_updates_tags_and_supports_undo(management_window, tmp_path):
    _app, window, baselines = management_window
    project = window.project
    first, second = project.curves
    for curve, baseline in zip(project.curves, baselines, strict=True):
        window._uncertainty_finished([(curve.id, baseline, result(baseline, "parametric_monte_carlo"))])
    window._uncertainty_finished([(first.id, baselines[0], result(baselines[0], "block_bootstrap"))])
    project.results["uncertainty_failures_by_curve"] = {
        second.id: {"parametric_monte_carlo": {"reason": "timeout", "message": "Uncertainty replica timeout: test"}}}
    window._select_uncertainty_display("parametric_monte_carlo")
    choose(window, "monte_carlo")
    window.refresh_all()
    y_values = [curve.y.copy() for curve in project.curves]
    fitted_parameters = [project.model_for(curve.id).to_dict() for curve in project.curves]
    assert "Uncertainty analysed" in item(window).text(2)
    assert "failed" in item(window, 1).text(2)
    assert window.uncertainty_panel.delete_button.isEnabled()
    window.uncertainty_panel.delete_button.click()
    for key in ("uncertainty_reports_by_curve", "uncertainty_by_curve", "uncertainty_failures_by_curve"):
        assert all("parametric_monte_carlo" not in methods for methods in project.results[key].values())
    assert "parametric_monte_carlo" not in project.results["uncertainty"]
    assert "block_bootstrap" in project.results["uncertainty_reports_by_curve"][first.id]
    assert item(window).text(2) == item(window, 1).text(2) == "Fitted"
    assert item(window, 1).icon(1).isNull()
    assert window.model_panel.display_method.currentData() == "block_bootstrap"
    assert not window.uncertainty_panel.delete_button.isEnabled()
    for index, curve in enumerate(project.curves):
        assert curve.state == CurveState.FITTED
        np.testing.assert_array_equal(curve.y, y_values[index])
        assert project.model_for(curve.id).to_dict() == fitted_parameters[index]
    window.undo_stack.undo()
    assert "Uncertainty analysed" in item(window).text(2)
    assert "failed" in item(window, 1).text(2)
    assert window.model_panel.display_method.currentData() == "parametric_monte_carlo"
    assert window.uncertainty_panel.delete_button.isEnabled()
    window.undo_stack.redo()
    reopened = load_project(save_project(project, tmp_path / "deleted.fitproj"))
    assert all("parametric_monte_carlo" not in methods
               for methods in reopened.results["uncertainty_reports_by_curve"].values())
    choose(window, "block_bootstrap")
    assert "Uncertainty analysed" in item(window).text(2)


@pytest.mark.parametrize("converged", [False, True])
def test_adaptive_warning_colour_and_icon_follow_method_and_survive_reopen(management_window, tmp_path, converged):
    app, window, baselines = management_window
    first = window.project.curves[0]
    choose(window, "residual_bootstrap")
    window._uncertainty_finished([(first.id, baselines[0], result(baselines[0], converged=converged))])
    assert ("⚠" in item(window).text(2)) is not converged
    assert item(window).icon(1).isNull() is converged
    assert window.uncertainty_panel.results.warning.isHidden() is converged
    if not converged:
        assert item(window).foreground(2).color().name() != "#009e73"
        assert "stability has not been established" in window.uncertainty_panel.results.warning.text()
        assert "7/7 attempts" in item(window).toolTip(2)
    choose(window, "monte_carlo")
    assert "⚠" not in item(window).text(2)
    assert item(window).icon(1).isNull()
    assert item(window).foreground(2).color().name() == "#009e73"
    choose(window, "residual_bootstrap")
    assert ("⚠" in item(window).text(2)) is not converged
    saved = load_project(save_project(window.project, tmp_path / "warning.fitproj"))
    other = MainWindow(saved)
    try:
        choose(other, "residual_bootstrap")
        assert ("⚠" in item(other).text(2)) is not converged
        assert item(other).icon(1).isNull() is converged
        assert other.uncertainty_panel.results.warning.isHidden() is converged
    finally:
        saved.dirty = False
        other.close()
        other.deleteLater()
        app.processEvents()


def test_timeout_warns_without_replacing_previous_result_and_delete_clears_it(management_window, monkeypatch):
    _app, window, baselines = management_window
    first = window.project.curves[0]
    previous = result(baselines[0])
    choose(window, "residual_bootstrap")
    window._uncertainty_finished([(first.id, baselines[0], previous)])
    window._uncertainty_task = {"method": "residual_bootstrap", "curve_ids": {first.id}, "completed": set()}
    monkeypatch.setattr(window, "_show_error", lambda *args: None)
    window._task_failed("Uncertainty replica timeout: test", "test timeout")
    assert "⚠" in item(window).text(2) and "timeout" in item(window).text(2)
    assert not item(window).icon(1).isNull()
    assert item(window).foreground(2).color().name() != "#009e73"
    assert "Timeout" in window.uncertainty_panel.results.warning.text()
    assert window.project.results["uncertainty_by_curve"][first.id]["residual_bootstrap"] is previous
    window.uncertainty_panel.delete_button.click()
    assert item(window).text(2) == "Fitted"
    assert item(window).icon(1).isNull()
    assert window.uncertainty_panel.results.warning.isHidden()


def test_adaptive_default_and_manual_disclaimer_are_method_specific(management_window):
    _app, window, _baselines = management_window
    panel = window.uncertainty_panel
    assert panel.replica_mode.currentData() == "adaptive"
    assert not panel.form.isRowVisible(panel.fixed_warning)
    panel.replica_mode.setCurrentIndex(panel.replica_mode.findData("fixed"))
    assert panel.form.isRowVisible(panel.fixed_warning)
    assert "does not check" in panel.fixed_warning.text()
    assert "Prefer Adaptive" in panel.fixed_warning.text()
    assert "tests" in panel.fixed_warning.text() and "quick analysis" in panel.fixed_warning.text()
    choose(window, "profile_likelihood")
    assert not panel.form.isRowVisible(panel.fixed_warning)
    choose(window, "block_bootstrap")
    assert panel.form.isRowVisible(panel.fixed_warning)
    panel.replica_mode.setCurrentIndex(panel.replica_mode.findData("adaptive"))
    assert not panel.form.isRowVisible(panel.fixed_warning)


def test_delete_is_disabled_for_readonly_or_running_tasks(management_window):
    _app, window, baselines = management_window
    first = window.project.curves[0]
    choose(window, "residual_bootstrap")
    window._uncertainty_finished([(first.id, baselines[0], result(baselines[0]))])
    panel = window.uncertainty_panel
    panel.set_busy(True)
    assert not panel.delete_button.isEnabled()
    choose(window, "monte_carlo")
    choose(window, "residual_bootstrap")
    assert not panel.delete_button.isEnabled()
    panel.set_busy(False)
    assert panel.delete_button.isEnabled()
    window.project.read_only = True
    panel.set_parameters(window.project, first.id)
    assert not panel.delete_button.isEnabled()


def test_adaptive_panel_scrolls_without_overlapping_report_widgets(management_window):
    app, window, baselines = management_window
    first = window.project.curves[0]
    choose(window, "residual_bootstrap")
    window._uncertainty_finished([(first.id, baselines[0], result(baselines[0], converged=False))])
    window.resize(1000, 650)
    window.show()
    window.activate_tool_dock(window.uncertainty_dock)
    app.processEvents()
    panel = window.uncertainty_panel
    assert panel.scroll.verticalScrollBar().maximum() > 0
    panel.scroll.ensureWidgetVisible(panel.results.table)
    app.processEvents()
    legend = next(label for label in panel.results.findChildren(QLabel) if label.text().startswith("OK:"))
    assert panel.results.table.height() >= panel.results.table.minimumHeight()
    assert panel.results.table.geometry().bottom() < legend.geometry().top()


def test_one_failed_replica_warns_globally_without_flagging_valid_parameter(management_window, tmp_path):
    app, window, baselines = management_window
    first = window.project.curves[0]
    analysis = result(baselines[0])
    analysis.requested = 5000
    analysis.completed = 4999
    analysis.failed = 1
    analysis.failure_messages = ["Maximum function evaluations reached"]
    choose(window, "residual_bootstrap")
    window._uncertainty_finished([(first.id, baselines[0], analysis)])
    results = window.uncertainty_panel.results
    assert results.table.item(1, 4).text() == "OK"
    assert all("replica" not in reason.lower() for reason in results._assessment_rows[1]["reason_items"])
    assert "1 replica(s) failed out of 5000 attempts" in results.warning.text()
    assert "4999 successful" in results.warning.text()
    assert "⚠" in item(window).text(2)
    assert not item(window).icon(1).isNull()
    assert item(window).foreground(2).color().name() != "#009e73"
    saved = load_project(save_project(window.project, tmp_path / "one-failure.fitproj"))
    other = MainWindow(saved)
    try:
        choose(other, "residual_bootstrap")
        assert other.uncertainty_panel.results.table.item(1, 4).text() == "OK"
        assert "1 replica(s) failed out of 5000 attempts" in other.uncertainty_panel.results.warning.text()
        assert "⚠" in item(other).text(2)
        choose(other, "monte_carlo")
        assert other.uncertainty_panel.results.warning.isHidden()
        assert item(other).icon(1).isNull()
    finally:
        saved.dirty = False
        other.close()
        other.deleteLater()
        app.processEvents()


def test_failed_replica_and_adaptive_limit_are_both_reported(management_window):
    _app, window, baselines = management_window
    first = window.project.curves[0]
    analysis = result(baselines[0], converged=False)
    analysis.completed = 6
    analysis.failed = 1
    choose(window, "residual_bootstrap")
    window._uncertainty_finished([(first.id, baselines[0], analysis)])
    text = window.uncertainty_panel.results.warning.text()
    assert "Adaptive limit reached" in text
    assert "1 replica(s) failed out of 7 attempts" in text
