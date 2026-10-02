from __future__ import annotations

import multiprocessing
import time

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.core import uncertainty
from curvemole.core.data import CurveState
from curvemole.core.fitting import CancellationToken, FitPlan, Fitter
from curvemole.core.serialization import load_project, save_project
from curvemole.core.uncertainty import (
    AdaptiveReplicateSettings,
    ReplicaTimeout,
    UncertaintyAnalyzer,
)
from curvemole.gui.main_window import MainWindow


def _blocking_replica(delay):
    # Deliberately uncooperative work: no cancellation checks inside this call.
    def body(*args):
        time.sleep(delay)
        return [1.], None

    uncertainty._resample_trial_body = body
    return uncertainty._resample_trial(0, "residual_bootstrap", None, None, {}, {}, {},
                                      None, CancellationToken())


@pytest.mark.parametrize("workers", [1, 2])
def test_deadline_kills_unresponsive_workers_and_aborts_entire_analysis(workers):
    previous = {child.pid for child in multiprocessing.active_children()}
    started = time.monotonic()
    with pytest.raises(ReplicaTimeout, match="analysis was stopped"):
        uncertainty._parallel_map(_blocking_replica, [30.] * 4, workers, (),
                                  CancellationToken(), None, replica_timeout_seconds=.15)
    assert time.monotonic() - started < 10
    assert {child.pid for child in multiprocessing.active_children()} <= previous


def test_deadline_resets_for_each_replica_and_excludes_queue_wait():
    # The total batch exceeds the deadline, but every replica stays below it.
    results = uncertainty._parallel_map(_blocking_replica, [.12] * 6, 1, (),
                                       CancellationToken(), None, replica_timeout_seconds=.3)
    assert results == [([1.], None)] * 6


def _analysis():
    project = Project("timeout")
    x = np.linspace(0., 3., 21)
    curve = Curve("spectrum", x, 1. + .01*np.sin(x), sigma_y=np.full(len(x), .01))
    project.add_curve(curve)
    model = project.model_for(curve.id)
    model.add(Component.create("constant", initial={"offset": 1.}))
    plan = FitPlan([curve.id])
    analyzer = UncertaintyAnalyzer()
    baseline = analyzer.fitter.fit(plan, [curve], project.models)
    return project, curve, analyzer, baseline, plan


@pytest.mark.parametrize("method", ["parametric_monte_carlo", "residual_bootstrap", "block_bootstrap"])
@pytest.mark.parametrize("adaptive", [False, True])
def test_timeout_propagates_instead_of_counting_as_an_ordinary_failed_fit(monkeypatch, method, adaptive):
    project, curve, analyzer, baseline, plan = _analysis()
    # Exercise the serial fallback used by executable callback functions.
    monkeypatch.setattr(uncertainty, "_parallel_safe", lambda *args: False)
    analyzer.replica_timeout_seconds = 1e-9
    kwargs = {"adaptive": AdaptiveReplicateSettings(2, 1, .05, 1, 5)} if adaptive else {}
    with pytest.raises(ReplicaTimeout):
        getattr(analyzer, method)(baseline, plan, [curve], project.models, replicates=5, **kwargs)
    assert curve.state == CurveState.FITTED


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_replica_timeout_is_rejected(timeout):
    with pytest.raises(uncertainty.FitError, match="positive, finite"):
        UncertaintyAnalyzer(replica_timeout_seconds=timeout)


def test_replica_deadline_uses_high_resolution_clock(monkeypatch):
    # Model a platform whose monotonic clock has not advanced to its next tick.
    monkeypatch.setattr(uncertainty.time, "monotonic", lambda: 1.)
    monkeypatch.setattr(uncertainty.time, "perf_counter", lambda: 2.)
    token = uncertainty._ReplicaCancellation(CancellationToken(), 1.5, .5)
    with pytest.raises(ReplicaTimeout):
        token.raise_if_cancelled()


def test_serial_isolation_preserves_custom_fitter_behaviour():
    project, curve, analyzer, baseline, plan = _analysis()
    calls = []

    class CustomFitter(Fitter):
        def fit(self, *args, **kwargs):
            calls.append(1)
            return super().fit(*args, **kwargs)

    analyzer.fitter = CustomFitter()
    result = analyzer.residual_bootstrap(baseline, plan, [curve], project.models, replicates=3)
    assert result.completed == 3
    assert len(calls) == 3


def test_timeout_tag_is_method_specific_persistent_and_cleared_on_success(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    project, curve, analyzer, baseline, plan = _analysis()
    previous = analyzer.residual_bootstrap(baseline, plan, [curve], project.models, replicates=3)
    window = MainWindow(project)
    panel = window.uncertainty_panel
    panel.method.setCurrentIndex(panel.method.findData("residual_bootstrap"))
    window._uncertainty_finished([(curve.id, baseline, previous)])
    window._uncertainty_task = {"method": "residual_bootstrap", "curve_ids": {curve.id},
                                "completed": set()}
    monkeypatch.setattr(window, "_show_error", lambda *args: None)
    window._task_failed(uncertainty._timeout_message(), "timeout")
    item = window.curve_tree.topLevelItem(0).child(0)
    assert "Uncertainty analysis failed" in item.text(2)
    assert "failed" in panel.results.summary.text()
    assert project.results["uncertainty_by_curve"][curve.id]["residual_bootstrap"] is previous
    assert curve.state == CurveState.FITTED
    saved = save_project(project, tmp_path / "timeout.fitproj")
    assert load_project(saved).results["uncertainty_failures_by_curve"][curve.id]["residual_bootstrap"]
    panel.method.setCurrentIndex(panel.method.findData("monte_carlo"))
    assert "Uncertainty analysis failed" not in item.text(2)
    panel.method.setCurrentIndex(panel.method.findData("residual_bootstrap"))
    window._uncertainty_finished([(curve.id, baseline, previous)])
    assert "Uncertainty analysed" in window.curve_tree.topLevelItem(0).child(0).text(2)
    window._task_done()
    assert window._uncertainty_task is None
    assert not window.progress.isVisible()
    project.dirty = False
    window.close()
    app.processEvents()


def test_completed_spectrum_keeps_its_analysis_tag_when_next_spectrum_times_out(monkeypatch):
    app = QApplication.instance() or QApplication([])
    project, curve, _, _, _ = _analysis()
    second = Curve("second", curve.x.copy(), curve.y.copy())
    project.add_curve(second)
    window = MainWindow(project)
    window._uncertainty_task = {"method": "block_bootstrap", "curve_ids": {curve.id, second.id},
                                "completed": {curve.id}}
    monkeypatch.setattr(window, "_show_error", lambda *args: None)
    window._task_failed(uncertainty._timeout_message(), "timeout")
    failures = project.results["uncertainty_failures_by_curve"]
    assert curve.id not in failures
    assert "block_bootstrap" in failures[second.id]
    project.dirty = False
    window.close()
    app.processEvents()


@pytest.mark.parametrize("workers", [1, 2])
@pytest.mark.parametrize("adaptive", [False, True])
def test_background_timeout_releases_gui_and_preserves_saved_fit(monkeypatch, workers, adaptive):
    app = QApplication.instance() or QApplication([])
    project, curve, _, baseline, _ = _analysis()
    window = MainWindow(project)
    window._fit_finished(baseline)
    panel = window.uncertainty_panel
    panel.method.setCurrentIndex(panel.method.findData("block_bootstrap"))
    errors = []
    monkeypatch.setattr(window, "_show_error", lambda title, error: errors.append(str(error)))
    previous = {child.pid for child in multiprocessing.active_children()}
    window.start_uncertainty(
        "block_bootstrap", 10, None, workers=workers,
        adaptive=AdaptiveReplicateSettings(2, 1, .05, 1, 5) if adaptive else None,
        replica_timeout_seconds=1e-9,
    )
    deadline = time.monotonic() + 10
    while window._thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert window._thread is None
    assert window.fit_action.isEnabled()
    assert not window.progress.isVisible()
    assert curve.state == CurveState.FITTED
    assert errors and "replica exceeded" in errors[0]
    assert "Uncertainty analysis failed" in window.curve_tree.topLevelItem(0).child(0).text(2)
    assert {child.pid for child in multiprocessing.active_children()} <= previous
    project.dirty = False
    window.close()
    app.processEvents()
