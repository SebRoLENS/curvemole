from __future__ import annotations

import copy
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Fitter, Project
from curvemole.core.data import CurveState
from curvemole.core.fit_records import plan_to_record
from curvemole.core.fitting import FitMode, FitPlan, FitSettings, _merge_results
from curvemole.core.uncertainty import ResamplingResult, UncertaintyAnalyzer
from curvemole.gui import app as gui_app  # noqa: F401
from curvemole.gui.main_window import MainWindow


def _wait_for(app: QApplication, predicate, timeout: float = 6.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not predicate():
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert predicate()


def _project():
    project = Project("progressive")
    x = np.linspace(-4, 4, 81)
    for center in (-0.7, 1.0):
        curve = Curve(f"spectrum {center}", x, np.exp(-((x - center) / 0.7) ** 2))
        project.add_curve(curve)
        project.model_for(curve.id).add(Component.create(
            "gaussian", initial={"area": 1.0, "center": 0.0, "sigma": 1.0}
        ))
    project.dirty = False
    return project


def test_first_multicore_fit_is_visible_before_second_finishes(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    project = _project()
    curves = project.curves
    reference = [Fitter().fit_single(copy.deepcopy(curve), project.model_for(curve.id).clone())
                 for curve in curves]
    release = threading.Event()
    window = MainWindow(project)

    def staged_fit(self, plan, curve_map, models, *, cancellation=None, progress=None,
                   on_curve_result=None):
        assert on_curve_result is not None
        on_curve_result(curves[0].id, reference[0])
        if not release.wait(5):
            raise RuntimeError("test gate timed out")
        on_curve_result(curves[1].id, reference[1])
        return _merge_results(reference, FitMode.INDEPENDENT, plan.settings)

    monkeypatch.setattr(Fitter, "fit", staged_fit)
    try:
        window._run_fit(FitPlan([curve.id for curve in curves], FitMode.INDEPENDENT,
                                FitSettings(workers=2)))
        _wait_for(app, lambda: curves[0].state == CurveState.FITTED)
        assert window._thread is not None
        assert curves[1].state != CurveState.FITTED
        assert window._fit_for_uncertainty(curves[0].id) is not None
        component = project.model_for(curves[0].id).components[0]
        assert component.parameters["center"].value == pytest.approx(-0.7, abs=0.02)
        assert component.id in window.plot_workspace._component_items
        window._set_active_curve(curves[1].id)
        assert window.active_curve_id == curves[1].id
        window._set_active_curve(curves[0].id)
        assert window.model_panel.parameters.rowCount() > 0
        assert component.id in window.plot_workspace._component_items
        release.set()
        _wait_for(app, lambda: window._thread is None)
        assert curves[1].state == CurveState.FITTED
    finally:
        release.set()
        _wait_for(app, lambda: window._thread is None)
        project.dirty = False
        window.close()


def test_first_uncertainty_report_is_visible_while_batch_runs(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    project = _project()
    for curve in project.curves:
        plan = FitPlan([curve.id])
        baseline = Fitter().fit(plan, [curve], {curve.id: project.model_for(curve.id)})
        project.results.setdefault("fit_by_curve", {})[curve.id] = {
            "plan": plan_to_record(plan), "baseline": baseline,
        }
    project.dirty = False
    window = MainWindow(project)
    release = threading.Event()

    def staged_batch(self, method, jobs, *, replicates, option, workers,
                     cancellation, progress, on_result):
        results = []
        for index, (baseline, _plan, _curves, _models) in enumerate(jobs):
            paths = list(baseline.free_parameter_paths)
            result = ResamplingResult(method, replicates, 5, 0, 123, paths,
                                      np.zeros((5, len(paths))),
                                      {path: (-0.1, 0.1) for path in paths},
                                      0.95, {})
            results.append(result)
            on_result(index, result)
            if index == 0 and not release.wait(5):
                raise RuntimeError("test gate timed out")
        return results

    monkeypatch.setattr(UncertaintyAnalyzer, "resampling_batch", staged_batch)
    try:
        window.start_uncertainty("residual_bootstrap", 10, None, scope="all", workers=2)
        first, second = project.curves
        _wait_for(app, lambda: "residual_bootstrap" in project.results.get(
            "uncertainty_reports_by_curve", {}).get(first.id, {}))
        assert window._thread is not None
        assert "residual_bootstrap" not in project.results.get(
            "uncertainty_reports_by_curve", {}).get(second.id, {})
        assert window.uncertainty_panel.display_method.findData("residual_bootstrap") >= 0
        window._set_active_curve(second.id)
        assert window.uncertainty_panel.display_method.findData("residual_bootstrap") < 0
        window._set_active_curve(first.id)
        assert window.uncertainty_panel.display_method.findData("residual_bootstrap") >= 0
        release.set()
        _wait_for(app, lambda: window._thread is None)
        assert "residual_bootstrap" in project.results[
            "uncertainty_reports_by_curve"][second.id]
    finally:
        release.set()
        _wait_for(app, lambda: window._thread is None)
        project.dirty = False
        window.close()
