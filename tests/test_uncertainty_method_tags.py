from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Fitter, Project
from curvemole.core.data import CurveState
from curvemole.core.serialization import load_project, save_project
from curvemole.core.uncertainty import ProfileResult, ResamplingResult
from curvemole.gui.main_window import MainWindow


def _project():
    project = Project("method-specific tags")
    baselines = []
    for index in range(2):
        x = np.linspace(0., 3., 21)
        curve = Curve(f"spectrum {index}", x, 1. + index + .01*np.sin(x))
        project.add_curve(curve)
        model = project.model_for(curve.id)
        model.add(Component.create("constant", initial={"offset": 1.}))
        baselines.append(Fitter().fit_single(curve, model))
    project.dirty = False
    return project, baselines


def _result(method, baseline):
    if method == "covariance":
        return baseline
    path = baseline.free_parameter_paths[0]
    if method == "profile_likelihood":
        return ProfileResult(path, np.array([0., 1., 2.]), np.array([5., 0., 5.]), .95, (.9, 1.1), 0)
    method = "parametric_monte_carlo" if method == "monte_carlo" else method
    return ResamplingResult(method, 200, 200, 0, 42, [path], np.ones((200, 1)), {path: (.9, 1.1)}, .95, {})


def _choose(window, method):
    window.uncertainty_panel.method.setCurrentIndex(window.uncertainty_panel.method.findData(method))


def _items(window):
    return [window.curve_tree.topLevelItem(0).child(i) for i in range(2)]


@pytest.mark.parametrize("method", [
    "covariance", "monte_carlo", "residual_bootstrap", "block_bootstrap", "profile_likelihood",
])
def test_tag_is_specific_to_selected_method_and_spectrum(method):
    app = QApplication.instance() or QApplication([])
    project, baselines = _project()
    window = MainWindow(project)
    _choose(window, method)
    window._uncertainty_finished([(project.curves[0].id, baselines[0], _result(method, baselines[0]))])
    first, second = _items(window)
    assert "Uncertainty analysed" in first.text(2)
    assert second.text(2) == "Fitted"
    window.curve_tree.clearSelection()
    first.setSelected(True)
    second.setSelected(True)
    selected = window.curve_tree.selected_curve_ids()
    other = "monte_carlo" if method != "monte_carlo" else "block_bootstrap"
    _choose(window, other)
    # Updating tags leaves the rows and selection intact; no refresh/rerun needed.
    assert _items(window)[0] is first
    assert first.text(2) == second.text(2) == "Fitted"
    assert "not analysed" in first.toolTip(2)
    assert window.curve_tree.selected_curve_ids() == selected
    _choose(window, method)
    assert "Uncertainty analysed" in first.text(2)
    project.curves[0].state = CurveState.MODIFIED
    window.refresh_all()
    assert "Uncertainty analysis outdated" in _items(window)[0].text(2)
    _choose(window, other)
    assert _items(window)[0].text(2) == CurveState.MODIFIED.value
    project.dirty = False
    window.close()
    app.processEvents()


def test_finishing_another_method_does_not_mark_current_method_done():
    app = QApplication.instance() or QApplication([])
    project, baselines = _project()
    window = MainWindow(project)
    _choose(window, "block_bootstrap")
    # A Monte Carlo task can finish after the user has changed the method menu.
    window._uncertainty_finished([(project.curves[0].id, baselines[0], _result("monte_carlo", baselines[0]))])
    assert _items(window)[0].text(2) == "Fitted"
    assert window.uncertainty_panel.results.method == "block_bootstrap"
    assert "No recorded result" in window.uncertainty_panel.results.summary.text()
    _choose(window, "monte_carlo")
    assert "Uncertainty analysed" in _items(window)[0].text(2)
    assert "Parametric Monte Carlo" in _items(window)[0].toolTip(2)
    project.dirty = False
    window.close()
    app.processEvents()


def test_multiple_saved_methods_keep_separate_tags_after_refresh_and_reopen(tmp_path):
    app = QApplication.instance() or QApplication([])
    project, baselines = _project()
    window = MainWindow(project)
    window._uncertainty_finished([
        (project.curves[0].id, baselines[0], _result("block_bootstrap", baselines[0])),
        (project.curves[1].id, baselines[1], _result("monte_carlo", baselines[1])),
    ])
    path = tmp_path / "methods.fitproj"
    save_project(project, path)
    reopened = load_project(path)
    other = MainWindow(reopened)
    for current in (window, other):
        _choose(current, "block_bootstrap")
        current.refresh_all()
        assert "Uncertainty analysed" in _items(current)[0].text(2)
        assert _items(current)[1].text(2) == "Fitted"
        current._set_active_curve(project.curves[1].id)
        _choose(current, "monte_carlo")
        assert _items(current)[0].text(2) == "Fitted"
        assert "Uncertainty analysed" in _items(current)[1].text(2)
        assert set(current.project.results["uncertainty_reports_by_curve"]) == {c.id for c in project.curves}
        current.project.dirty = False
        current.close()
    app.processEvents()
