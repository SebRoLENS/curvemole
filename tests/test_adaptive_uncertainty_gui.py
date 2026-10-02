from __future__ import annotations

import time

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Fitter, Project
from curvemole.core.serialization import load_project, save_project
from curvemole.core.uncertainty import AdaptiveReplicateSettings
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.panels import UncertaintyPanel


def test_adaptive_controls_and_run_request_are_method_specific():
    app = QApplication.instance() or QApplication([])
    panel = UncertaintyPanel()
    assert panel.adaptive_settings() is None
    panel.replica_mode.setCurrentIndex(panel.replica_mode.findData("adaptive"))
    assert panel.adaptive_settings() == AdaptiveReplicateSettings()
    assert not panel.replicates.isEnabled()
    assert panel.adaptive_initial.isEnabled()
    requested = []
    panel.runRequested.connect(lambda *args: requested.append(args))
    panel._run()
    assert requested[0][-1] == AdaptiveReplicateSettings()
    panel.method.setCurrentIndex(panel.method.findData("covariance"))
    assert panel.adaptive_settings() is None
    assert not panel.adaptive_initial.isEnabled()
    assert not panel.replica_mode.isEnabled()
    panel.method.setCurrentIndex(panel.method.findData("profile_likelihood"))
    assert panel.adaptive_settings() is None
    panel.method.setCurrentIndex(panel.method.findData("block_bootstrap"))
    assert panel.adaptive_settings() == AdaptiveReplicateSettings()
    panel.adaptive_initial.setValue(12_000)
    assert panel.adaptive_maximum.value() == 12_000
    panel.close()
    app.processEvents()


@pytest.mark.parametrize("scope", ["selected", "all"])
@pytest.mark.parametrize("adaptive_mode", [False, True])
def test_custom_formulas_parallelize_from_gui_and_save_adaptive_results(tmp_path, scope, adaptive_mode):
    app = QApplication.instance() or QApplication([])
    project = Project("custom formula parallel uncertainty")
    # Load the formula through the same project path used by real workspaces.
    project.custom_functions.append({
        "identifier": "uncertainty_test_line", "display_name": "Test line",
        "formula": "a + b*x", "defaults": {"a": 1., "b": 2.},
    })
    window = CurveMoleMainWindow(project)
    assert window.registry.get("uncertainty_test_line").custom_metadata["formula"] == "a + b*x"
    x = np.linspace(0., 2., 21)
    for index in range(3):
        curve = Curve(f"scan {index}", x, 1. + index + 2*x + .05*np.sin(5*x))
        project.add_curve(curve)
        model = project.model_for(curve.id)
        model.add(Component.create("uncertainty_test_line", registry=window.registry))
        result = Fitter(window.registry).fit_single(curve, model)
        window._fit_finished(result)
    window._set_active_curve(project.curves[0].id)
    if scope == "selected":
        window.curve_tree.clearSelection()
        parent = window.curve_tree.topLevelItem(0)
        parent.child(0).setSelected(True)
        parent.child(2).setSelected(True)
        expected = {project.curves[0].id, project.curves[2].id}
    else:
        expected = {curve.id for curve in project.curves}
    panel = window.uncertainty_panel
    panel.method.setCurrentIndex(panel.method.findData("block_bootstrap"))
    panel.scope.setCurrentIndex(panel.scope.findData(scope))
    panel.workers.setValue(12)
    panel.replicates.setValue(10)
    if adaptive_mode:
        panel.replica_mode.setCurrentIndex(panel.replica_mode.findData("adaptive"))
        panel.adaptive_initial.setValue(3)
        panel.adaptive_batch.setValue(2)
        panel.adaptive_tolerance.setValue(99.)
        panel.adaptive_checks.setValue(1)
        panel.adaptive_maximum.setValue(7)
    panel._run()
    deadline = time.monotonic() + 20
    while window._thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert window._thread is None
    reports = project.results["uncertainty_reports_by_curve"]
    assert set(reports) == expected
    for curve_id in expected:
        analysis = reports[curve_id]["block_bootstrap"]["analysis"]
        assert analysis["failed"] == 0
        assert analysis["configuration"]["batch_workers_used"] == min(panel.workers.value(), len(expected))
        if adaptive_mode:
            config = analysis["configuration"]["adaptive"]
            assert config["attempted"] <= 7
            assert config["initial_successes"] == 3
    if adaptive_mode:
        path = tmp_path / "adaptive.fitproj"
        save_project(project, path)
        restored = load_project(path)
        for curve_id in expected:
            saved = restored.results["uncertainty_reports_by_curve"][curve_id]["block_bootstrap"]["analysis"]
            assert saved["configuration"]["adaptive"] == reports[curve_id]["block_bootstrap"]["analysis"]["configuration"]["adaptive"]
        window.uncertainty_panel.results.show_method("block_bootstrap")
        assert "attempts" in window.uncertainty_panel.results.summary.text()
        assert "Stop reason:" in window.uncertainty_panel.results.details.toPlainText()
    project.dirty = False
    window.close()
    app.processEvents()
