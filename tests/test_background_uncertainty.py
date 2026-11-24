"""Verify the two uncertainty analyses of a recorded spline subtraction."""

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Model, Project
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


@pytest.mark.parametrize("mode,scalings,factor", [
    ("fixed", [], 1.0),
    ("joint", [], 1.0),
    ("fixed", [("y_multiply", 2.0)], 2.0),
    ("joint", [("y_multiply", 5.0), ("y_divide", 2.0)], 2.5),
    ("joint", [("y_divide", -2.0)], -0.5),
])
def test_background_uncertainty_uses_a_separate_reproducible_fit(mode, scalings, factor):
    project, curve, spline, peak = spline_project()
    spline.parameters["y1"].minimum = 1.5
    spline.parameters["y1"].maximum = 2.5
    for operation, value in scalings:
        apply_scalar(curve, operation, value)
    plan = FitPlan([curve.id])
    fitter = Fitter()
    baseline, curves, models = fit_background_uncertainty(
        fitter, plan, {curve.id: curve}, project.models, mode, None)
    analysis = UncertaintyAnalyzer(fitter).parametric_monte_carlo(
        baseline, plan, curves, models, replicates=12, seed=81)
    assert analysis.completed == 12
    assert not curves[curve.id].has_correlated_y_errors
    restored_spline = models[curve.id].component(spline.id)
    assert restored_spline.metadata["x_nodes"] == [-5., 0., 5.]
    np.testing.assert_allclose(curves[curve.id].current_sigma_y, 0.1 * abs(factor))
    if mode == "fixed":
        np.testing.assert_array_equal(curves[curve.id].y, curve.y)
        assert not any(path.startswith(f"{curve.id}.{spline.id}.") for path in analysis.parameter_paths)
    else:
        np.testing.assert_allclose(curves[curve.id].y, factor * curve.original_y)
        node_path = f"{curve.id}.{spline.id}.y1"
        assert node_path in analysis.parameter_paths
        assert restored_spline.output_scale == factor
        assert baseline.parameters[node_path].value == pytest.approx(2., abs=.08)
        assert models[curve.id].background(np.array([0.]), curve_id=curve.id)[0] == pytest.approx(
            factor * baseline.parameters[node_path].value)
        saved_model = Model.from_dict(baseline.provenance["initial_models"][curve.id])
        fitted_values = {path: estimate.value for path, estimate in baseline.parameters.items()}
        output = baseline.curve_outputs[curve.id]
        np.testing.assert_allclose(saved_model.evaluate(output.x, curve_id=curve.id, values=fitted_values),
                                   output.fitted)
    assert curve.has_correlated_y_errors and not spline.enabled
    assert all(parameter.fixed for parameter in spline.parameters.values())
    assert peak.parameters["area"].value == 12.
    record = background_uncertainty_record(baseline)
    assert background_uncertainty_is_current(project, record)
    spline.parameters["y1"].value += 0.2
    assert not background_uncertainty_is_current(project, record)


@pytest.mark.parametrize("operation", ["normalize_max", "normalize_area"])
def test_background_analysis_refuses_normalization_after_subtraction(operation):
    project, curve, _, _ = spline_project()
    apply_scalar(curve, operation)
    with pytest.raises(FitError, match="factor estimated from its data"):
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
    project, curve, spline, peak = spline_project()
    apply_scalar(curve, "y_multiply", 2.0)
    window = CurveMoleMainWindow(project)
    original_exec = QMessageBox.exec

    def choose(dialog):
        assert dialog.text() == "An estimated background was subtracted from Raman."
        # The regression clicks a Qt widget. Native message boxes handle clicks
        # through the platform instead and macOS omits the window title.
        dialog.setOption(QMessageBox.Option.DontUseNativeDialog)
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
    window._set_component_on_curve(curve.id, peak.id)
    window._select_uncertainty_display("covariance")
    table = window.model_panel.parameters
    area_row = next(row for row in range(table.rowCount()) if table.item(row, 0).text() == "area")
    cell = table.item(area_row, 3)
    report = project.results["uncertainty_reports_by_curve"][curve.id]["covariance"]
    estimate = report["baseline"]["parameters"][f"{curve.id}.{peak.id}.area"]
    assert f'{estimate["value"]:.8g}  −' in cell.text()
    assert note in cell.toolTip()
    assert "separate fit value" in cell.toolTip()
    assert "Separate uncertainty analysis" in window.curve_tree.topLevelItem(0).child(0).text(2)
    assert not spline.enabled and curve.has_correlated_y_errors
    path = tmp_path / "spline.fitproj"
    save_project(project, path)
    restored = load_project(path)
    report = restored.results["uncertainty_reports_by_curve"][curve.id]["covariance"]
    record = background_uncertainty_record(report["baseline"])
    assert record["mode"] == mode
    if mode == "joint":
        assert record["scaled_backgrounds"] == {curve.id: {spline.id: 2.0}}
        assert "working Y scale" in uncertainty_warning(restored, curve.id, "covariance")
    assert background_uncertainty_is_current(restored, record)
    assert note in uncertainty_warning(restored, curve.id, "covariance")
    project.dirty = False
    window.close()
    app.processEvents()
