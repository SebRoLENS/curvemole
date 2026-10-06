from __future__ import annotations

import copy
import os
import subprocess
import sys
import threading
import time

import numpy as np
import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Fitter, Project
from curvemole.core.fitting import CancellationToken, FitMode, FitPlan
from curvemole.core.recovery import RecoveryManager
from curvemole.core.serialization import load_project
from curvemole.core.uncertainty import ResamplingResult, UncertaintyAnalyzer
from curvemole.gui.main_window import MainWindow


def wait_for(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    app.processEvents()
    assert predicate()


@pytest.fixture
def task_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    project = Project("Task lifecycle")
    curve = Curve("Data", np.arange(21.), np.ones(21))
    project.add_curve(curve)
    project.model_for(curve.id).add(Component.create("constant", initial={"offset": 1.}))
    baseline = Fitter().fit(FitPlan([curve.id]), [curve], project.models)
    window = MainWindow(project)
    window._fit_finished(baseline)
    window.project.path = tmp_path / "task.fitproj"
    window.recovery = RecoveryManager(tmp_path / "recovery")
    window._TASK_CANCEL_GRACE_SECONDS = .03
    window._task_watchdog.setInterval(5)
    errors = []
    monkeypatch.setattr(window, "_show_error", lambda title, error: errors.append(str(error)))
    yield app, window, errors
    wait_for(app, lambda: window._thread is None)
    project.dirty = False
    window.close()
    app.processEvents()


@pytest.mark.parametrize("error", [RuntimeError, SystemExit])
def test_worker_errors_release_all_busy_state(task_window, error):
    app, window, errors = task_window

    def operation(progress):
        progress(1, "Finished replicas")
        raise error("worker exited")

    window._run_background(operation, lambda result: pytest.fail("Unexpected result"), "Test")
    wait_for(app, lambda: window._thread is None)
    assert errors == ["worker exited"]
    assert window.fit_action.isEnabled()
    assert not window.cancel_action.isEnabled()
    assert window._task_callbacks is None


@pytest.mark.parametrize("hook", ["result", "partial", "cleanup"])
def test_gui_hook_errors_cannot_leave_task_busy(task_window, monkeypatch, hook):
    app, window, errors = task_window

    def fail(*args):
        raise RuntimeError("GUI hook failed")

    def operation(progress, publish=None):
        if publish:
            publish("partial")
        return "result"

    if hook == "cleanup":
        monkeypatch.setattr(window, "_task_done", fail)
    window._run_background(operation, fail if hook == "result" else lambda result: None,
                           "Test", partial=fail if hook == "partial" else None)
    wait_for(app, lambda: window._thread is None)
    assert window.fit_action.isEnabled()
    assert not window.cancel_action.isEnabled()
    assert not window.progress.isVisible()
    assert window._cancellation is None
    assert window._task_callbacks is None
    if hook != "cleanup":
        assert errors == ["GUI hook failed"]


def test_watchdog_recovers_result_and_busy_state_if_completion_signal_is_lost(task_window):
    app, window, _ = task_window
    release = threading.Event()
    results = []
    window._run_background(lambda progress: release.wait(3) or "result", results.append, "Test")
    runner = window._thread
    window._worker.finished.disconnect(window._task_callbacks.finished)
    runner.finished.disconnect(window._task_callbacks.done)
    release.set()
    wait_for(app, lambda: window._thread is None)
    assert results == [True]
    assert window.fit_action.isEnabled()


def test_unresponsive_uncertainty_can_be_saved_cancelled_and_replaced(task_window, monkeypatch):
    app, window, errors = task_window
    project = window.project
    curve = project.curves[0]
    model = project.model_for(curve.id)
    entered, release = threading.Event(), threading.Event()
    inputs = []

    def unresponsive(self, baseline, plan, curves, models, **kwargs):
        inputs.append((curves[curve.id], models[curve.id], kwargs["cancellation"]))
        paths = baseline.free_parameter_paths
        # Pretend a solver ignores cancellation even after reporting all replicas.
        kwargs["progress"](1, "Replicas completed")
        entered.set()
        assert release.wait(5)
        return ResamplingResult("residual_bootstrap", 5, 5, 0, 1, paths,
                                np.ones((5, len(paths))), {path: (.5, 1.5) for path in paths}, .95, {})

    monkeypatch.setattr(UncertaintyAnalyzer, "residual_bootstrap", unresponsive)
    watchdog_release = QTimer(window)
    watchdog_release.setSingleShot(True)
    watchdog_release.timeout.connect(release.set)
    watchdog_release.start(4000)  # Prevent a regression from hanging the test suite.
    window.start_uncertainty("residual_bootstrap", 5, None)
    old_runner = window._thread
    try:
        wait_for(app, entered.is_set)
        assert inputs[0][0] is not curve
        assert inputs[0][1] is not model
        assert window.progress.value() == 99
        window._autosave()
        wait_for(app, lambda: not window._autosave_controller.busy)
        assert window.recovery.candidates()
        assert window.save_project()
        assert not release.is_set(), "Saving waited for the stuck calculation"
        saved = load_project(project.path)
        assert saved.results["last_fit"].success
        assert not saved.results.get("uncertainty_by_curve")
        window.cancel_task()
        wait_for(app, lambda: window._thread is None)
        assert old_runner.isRunning()
        assert inputs[0][2].cancelled
        assert window.fit_action.isEnabled()
        assert window._cancellation is None

        next_release = threading.Event()
        window._cancellation = CancellationToken()
        window._run_background(lambda progress: next_release.wait(3), lambda result: None, "Next task")
        next_runner = window._thread
        release.set()
        wait_for(app, lambda: not old_runner.isRunning())
        assert window._thread is next_runner
        assert not window.fit_action.isEnabled()
        assert not project.results.get("uncertainty_by_curve")
        next_release.set()
        wait_for(app, lambda: window._thread is None)
        assert errors == []
    finally:
        watchdog_release.stop()
        release.set()
        old_runner.wait(5000)


def test_retired_task_does_not_prevent_closing_the_window(task_window):
    app, window, _ = task_window
    release = threading.Event()
    window._task_snapshot_safe = True
    window._cancellation = CancellationToken()
    window._run_background(lambda progress: release.wait(5), lambda result: None, "Test")
    runner = window._thread
    try:
        window.cancel_task()
        wait_for(app, lambda: window._thread is None)
        window.project.dirty = False
        assert window.close()
        assert runner.isRunning()
    finally:
        release.set()
        runner.wait(5000)
        app.processEvents()


@pytest.mark.parametrize("mode", list(FitMode))
def test_unresponsive_fit_cannot_mutate_saved_project_or_deliver_late_results(
    task_window, monkeypatch, mode,
):
    app, window, errors = task_window
    project = window.project
    curve = project.curves[0]
    model = project.model_for(curve.id)
    parameter = model.components[0].parameters["offset"]
    baseline = copy.deepcopy(project.results["last_fit"])
    entered, release = threading.Event(), threading.Event()

    def unresponsive(self, plan, curves, models, **kwargs):
        assert curves[curve.id] is not curve
        assert models[curve.id] is not model
        models[curve.id].components[0].parameters["offset"].value = 999
        kwargs["progress"](1, "Fit completed")
        entered.set()
        assert release.wait(5)
        baseline.mode = mode
        for estimate in baseline.parameters.values():
            estimate.value = 999
        return baseline

    monkeypatch.setattr(Fitter, "fit", unresponsive)
    window._run_fit(FitPlan([curve.id], mode))
    runner = window._thread
    guard = QTimer(window)
    guard.setSingleShot(True)
    guard.timeout.connect(release.set)
    guard.start(4000)
    try:
        wait_for(app, entered.is_set)
        assert parameter.value == pytest.approx(1)
        assert window.save_project()
        assert not release.is_set()
        restored = load_project(project.path)
        assert restored.model_for(curve.id).components[0].parameters["offset"].value == pytest.approx(1)
        window.cancel_task()
        wait_for(app, lambda: window._thread is None)
        assert runner.isRunning()
        assert window.fit_action.isEnabled()
        release.set()
        wait_for(app, lambda: not runner.isRunning())
        assert parameter.value == pytest.approx(1)
        assert project.results["last_fit"].parameters[next(iter(baseline.parameters))].value == pytest.approx(1)
        assert errors == []
    finally:
        guard.stop()
        release.set()
        runner.wait(5000)


def test_retired_daemon_cannot_hold_application_exit(tmp_path):
    script = tmp_path / "task_exit.py"
    script.write_text('''
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from curvemole import Project
from curvemole.gui.main_window import MainWindow

app = QApplication([])
window = MainWindow(Project())
window._TASK_CANCEL_GRACE_SECONDS = .02
window._task_watchdog.setInterval(5)
window._task_snapshot_safe = True
window._run_background(lambda progress: time.sleep(30), lambda result: None, "Test")
window.cancel_task()

def close_when_retired():
    if window._thread is not None:
        QTimer.singleShot(5, close_when_retired)
        return
    window.project.dirty = False
    assert window.close()
    app.quit()

QTimer.singleShot(5, close_when_retired)
app.exec()
''', encoding="utf-8")
    env = dict(os.environ, CURVEMOLE_DISABLE_PLUGINS="1",
               XDG_CONFIG_HOME=str(tmp_path / "config"),
               XDG_DATA_HOME=str(tmp_path / "data"),
               XDG_CACHE_HOME=str(tmp_path / "cache"))
    result = subprocess.run([sys.executable, str(script)], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "Destroyed while thread" not in result.stderr
