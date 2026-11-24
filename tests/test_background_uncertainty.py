"""Verify the two uncertainty analyses of a recorded spline subtraction."""

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Project
from curvemole.core.background_uncertainty import (
    background_uncertainty_is_current,
    background_uncertainty_record,
    fit_background_uncertainty,
    joint_background_components,
)
from curvemole.core.calculator import apply_background_subtraction, apply_scalar
from curvemole.core.errors import FitError
from curvemole.core.fitting import FitPlan
from curvemole.core.initialization import initialise_spline_component
from curvemole.core.serialization import load_project, save_project
from curvemole.core.uncertainty import UncertaintyAnalyzer
from curvemole.core.uncertainty_status import uncertainty_warning


def spline_project():
    x = np.linspace(-5., 5., 101)
    y = 2. + x / 10 + 5 * np.exp(-x**2 / 2) + np.random.default_rng(42).normal(0, 0.1, len(x))
    curve = Curve("Raman", x, y, sigma_y=np.full_like(x, 0.1))
    project = Project("Spline uncertainty")
    project.add_curve(curve)
    model = project.model_for(curve.id)
    spline = Component.create("cubic_spline", metadata={"x_nodes": [-5., 0., 5.]})
    initialise_spline_component(spline, [(-5., 1.5), (0., 2.1), (5., 2.5)])
    spline.is_background = True
    model.add(spline)
    peak = Component.create("gaussian", initial={"area": 12., "sigma": 1., "center": 0.})
    model.add(peak)
    apply_background_subtraction(curve, model.background(x), method="model_components", description="Spline",
                                 parameters={"component_ids": [spline.id]})
    spline.enabled = False
    return project, curve, spline, peak


@pytest.mark.parametrize("mode", ["fixed", "joint"])
def test_background_uncertainty_uses_a_separate_reproducible_fit(mode):
    project, curve, spline, peak = spline_project()
    plan = FitPlan([curve.id])
    fitter = Fitter()
    baseline, curves, models = fit_background_uncertainty(
        fitter, plan, {curve.id: curve}, project.models, mode, None)
    analysis = UncertaintyAnalyzer(fitter).parametric_monte_carlo(
        baseline, plan, curves, models, replicates=12, seed=81)
    assert analysis.completed == 12
    assert not curves[curve.id].has_correlated_y_errors
    assert models[curve.id].component(spline.id).metadata["x_nodes"] == [-5., 0., 5.]
    if mode == "fixed":
        np.testing.assert_array_equal(curves[curve.id].y, curve.y)
        assert not any(path.startswith(f"{curve.id}.{spline.id}.") for path in analysis.parameter_paths)
    else:
        np.testing.assert_array_equal(curves[curve.id].y, curve.original_y)
        assert f"{curve.id}.{spline.id}.y1" in analysis.parameter_paths
        assert baseline.parameters[f"{curve.id}.{spline.id}.y1"].value == pytest.approx(2., abs=.08)
    assert curve.has_correlated_y_errors and not spline.enabled
    assert all(parameter.fixed for parameter in spline.parameters.values())
    assert peak.parameters["area"].value == 12.
    record = background_uncertainty_record(baseline)
    assert background_uncertainty_is_current(project, record)
    spline.parameters["y1"].value += 0.2
    assert not background_uncertainty_is_current(project, record)


def test_background_analysis_refuses_unmodelled_correlations_or_later_operations():
    project, curve, _, _ = spline_project()
    apply_scalar(curve, "normalize_max")
    with pytest.raises(FitError, match="later data operation"):
        joint_background_components(curve, project.model_for(curve.id))
    with pytest.raises(FitError, match="other data operations"):
        fit_background_uncertainty(Fitter(), FitPlan([curve.id]), {curve.id: curve}, project.models, "fixed", None)


@pytest.mark.parametrize("button_label, mode, note", [
    ("Ignore background uncertainty", "fixed", "Background uncertainty excluded"),
    ("Refit with background", "joint", "Node positions and the choice of nodes were held fixed"),
])
def test_run_dialog_and_saved_background_result(button_label, mode, note, tmp_path, monkeypatch):
    pytest.importorskip("PySide6", exc_type=ImportError)
    pytest.importorskip("pyqtgraph", exc_type=ImportError)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from curvemole.gui.app import CurveMoleMainWindow

    app = QApplication.instance() or QApplication([])
    project, curve, spline, _ = spline_project()
    window = CurveMoleMainWindow(project)
    original_exec = QMessageBox.exec

    def choose(dialog):
        assert dialog.windowTitle() == "Background uncertainty"
        button = next(item for item in dialog.buttons() if item.text() == button_label)
        assert button.isEnabled()
        QTimer.singleShot(0, button.click)
        return original_exec(dialog)

    def run_now(operation, finished, *_args, **_kwargs):
        finished(operation(lambda *_: None))

    monkeypatch.setattr(QMessageBox, "exec", choose)
    monkeypatch.setattr(window, "_run_background", run_now)
    window.start_uncertainty("covariance", 10, None)
    assert note in window.uncertainty_panel.results.warning.text()
    assert "Separate uncertainty analysis" in window.curve_tree.topLevelItem(0).child(0).text(2)
    assert not spline.enabled and curve.has_correlated_y_errors
    path = tmp_path / "spline.fitproj"
    save_project(project, path)
    restored = load_project(path)
    report = restored.results["uncertainty_reports_by_curve"][curve.id]["covariance"]
    record = background_uncertainty_record(report["baseline"])
    assert record["mode"] == mode
    assert background_uncertainty_is_current(restored, record)
    assert note in uncertainty_warning(restored, curve.id, "covariance")
    project.dirty = False
    window.close()
    app.processEvents()
