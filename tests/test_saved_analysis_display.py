import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Fitter, Project
from curvemole.core.analysis_errors import analysis_error
from curvemole.core.data import CurveState
from curvemole.core.serialization import load_project, save_project
from curvemole.core.uncertainty import ProfileResult, ResamplingResult
from curvemole.gui.main_window import MainWindow


@pytest.fixture
def analysis_window():
    app = QApplication.instance() or QApplication([])
    project = Project("Saved analysis")
    curve = Curve("Measured spectrum", np.linspace(0., 1., 21), np.ones(21))
    project.add_curve(curve)
    project.model_for(curve.id).add(Component.create("constant", initial={"offset": 1.}))
    baseline = Fitter().fit_single(curve, project.model_for(curve.id))
    window = MainWindow(project)
    yield app, window, baseline
    project.dirty = False
    window.close()
    window.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("method", ["residual_bootstrap", "parametric_monte_carlo", "profile_likelihood"])
@pytest.mark.parametrize("state", [CurveState.FITTED, CurveState.MODIFIED])
@pytest.mark.parametrize("legacy", [False, True])
def test_saved_display_works_for_current_and_explicitly_historical_reports(analysis_window, tmp_path, method, state, legacy):
    app, window, baseline = analysis_window
    project = window.project
    curve = project.curves[0]
    path = baseline.free_parameter_paths[0]
    value = baseline.parameters[path].value
    interval = (value - .2, value + .4)
    if method == "profile_likelihood":
        result = ProfileResult(path, np.array([value]), np.array([0.]), .95, interval, 0)
    else:
        result = ResamplingResult(method, 200, 200, 0, 42, [path],
                                  np.full((200, 1), value), {path: interval}, .95, {})
    window._store_uncertainty_result(curve.id, baseline, result)
    project.results["uncertainty_display_method_by_curve"].clear()
    if legacy:
        record = project.results.pop("uncertainty_reports_by_curve")[curve.id][method]
        saved_method = "monte_carlo" if method == "parametric_monte_carlo" else method
        project.results["uncertainty_reports"] = {saved_method: record}
    curve.state = state
    project.path = tmp_path / "analysis.fitproj"
    assert window.save_project()  # Exercise the background snapshot writer too.
    restored = load_project(project.path)
    other = MainWindow(restored)
    try:
        assert other.model_panel.parameters.item(0, 3).text() == "—"
        index = other.uncertainty_panel.display_method.findData(method)
        assert index > 0
        other.uncertainty_panel.display_method.setCurrentIndex(index)
        cell = other.model_panel.parameters.item(0, 3)
        if state == CurveState.FITTED:
            assert cell.text() == "−0.2 / +0.4"
            assert analysis_error(restored, curve.id, path) == pytest.approx((.2, .4))
        else:
            assert cell.text() == "Recorded: −0.2 / +0.4"
            assert "not uncertainties of the current fit" in cell.toolTip()
            assert "recorded fit value 1" in cell.toolTip()
            assert analysis_error(restored, curve.id, path) is None
        assert restored.results["uncertainty_reports_by_curve"][curve.id][method]
        assert not restored.results.get("uncertainty_reports")
    finally:
        restored.dirty = False
        other.close()
        other.deleteLater()
        app.processEvents()


def test_read_only_project_can_select_saved_display_without_becoming_dirty(analysis_window, monkeypatch):
    _app, window, baseline = analysis_window
    curve = window.project.curves[0]
    path = baseline.free_parameter_paths[0]
    value = baseline.parameters[path].value
    result = ResamplingResult("block_bootstrap", 200, 200, 0, 42, [path],
                              np.full((200, 1), value), {path: (value - .1, value + .3)}, .95, {})
    window._store_uncertainty_result(curve.id, baseline, result)
    window.project.results["uncertainty_display_method_by_curve"].clear()
    window.project.read_only = True
    window.project.dirty = False
    window.uncertainty_panel.set_parameters(window.project, curve.id)
    monkeypatch.setattr(window, "_ensure_editable", lambda: pytest.fail("Viewing results must work read-only"))
    window.uncertainty_panel.display_method.setCurrentIndex(
        window.uncertainty_panel.display_method.findData("block_bootstrap"))
    assert window.model_panel.parameters.item(0, 3).text() == "−0.1 / +0.3"
    assert not window.project.dirty


def test_saved_monte_carlo_alias_restores_selected_errors_automatically(analysis_window, tmp_path):
    app, window, baseline = analysis_window
    project = window.project
    curve = project.curves[0]
    path = baseline.free_parameter_paths[0]
    value = baseline.parameters[path].value
    project.results["uncertainty_reports_by_curve"] = {curve.id: {"monte_carlo": {
        "baseline": baseline.to_dict(),
        "analysis": {"intervals": {path: [value - .3, value + .5]}, "confidence_level": .95},
    }}}
    project.results["uncertainty_display_method_by_curve"] = {curve.id: "monte_carlo"}
    restored = load_project(save_project(project, tmp_path / "monte-carlo.fitproj"))
    other = MainWindow(restored)
    try:
        assert other.uncertainty_panel.display_method.currentData() == "parametric_monte_carlo"
        assert other.model_panel.parameters.item(0, 3).text() == "−0.3 / +0.5"
    finally:
        restored.dirty = False
        other.close()
        other.deleteLater()
        app.processEvents()


def test_legacy_report_is_per_spectrum_and_does_not_return_after_refit(analysis_window, tmp_path):
    from curvemole.core.fitting import FitPlan

    app, window, baseline = analysis_window
    project = window.project
    first = project.curves[0]
    second = Curve("Other spectrum", [0., 1.], [1., 1.])
    project.add_curve(second)
    project.results["uncertainty_reports"] = {
        "covariance": {"baseline": baseline.to_dict(), "analysis": baseline.to_dict()},
    }
    restored = load_project(save_project(project, tmp_path / "legacy.fitproj"))
    assert set(restored.results["uncertainty_reports_by_curve"]) == {first.id}
    other = MainWindow(restored)
    try:
        other._running_fit_plan = FitPlan([first.id])
        other._fit_finished(Fitter().fit_single(restored.curves[0], restored.model_for(first.id)))
        assert first.id not in restored.results["uncertainty_reports_by_curve"]
        assert not restored.results.get("uncertainty_reports")
    finally:
        restored.dirty = False
        other.close()
        other.deleteLater()
        app.processEvents()
