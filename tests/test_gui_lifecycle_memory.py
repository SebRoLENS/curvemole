"""Regression coverage for data retained by finished GUI interactions."""

from __future__ import annotations

import gc
import weakref

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit
from shiboken6 import isValid

from curvemole import Component, Curve, Fitter, Project
from curvemole.core.fitting import FitPlan
from curvemole.gui.dialogs import FitPlanDialog
from curvemole.gui.main_window import MainWindow
from curvemole.gui.windowing import transient_widget


def drain_deletions(app):
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()


@pytest.fixture
def memory_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    project = Project("Lifecycle")
    curve = Curve("Data", np.arange(21.), np.ones(21))
    project.add_curve(curve)
    project.model_for(curve.id).add(Component.create("constant", initial={"offset": 1.}))
    project.dirty = False
    window = MainWindow(project)
    del project, curve
    yield app, window
    window.project.dirty = False
    window.close()
    drain_deletions(app)


def test_cancelled_fit_dialogs_release_their_project(memory_window, monkeypatch):
    app, window = memory_window
    original_exec = FitPlanDialog.exec
    dialogs = []

    def reject(dialog):
        dialogs.append(weakref.ref(dialog))
        QTimer.singleShot(0, dialog.reject)
        return original_exec(dialog)

    monkeypatch.setattr(FitPlanDialog, "exec", reject)
    project_id = window.project.id
    array_ref = weakref.ref(window.project.curves[0].original_x)
    for _ in range(8):
        window.start_fit()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert not window.findChildren(FitPlanDialog)
    window.new_project()
    # Project replacement must also retire older Python widget cycles without
    # waiting for future allocations or a test-side gc.collect().
    QTest.qWait(20)
    assert all(dialog() is None for dialog in dialogs)
    assert not any(isinstance(obj, Project) and obj.id == project_id for obj in gc.get_objects())
    assert array_ref() is None


def test_accepted_fit_dialog_is_alive_until_values_are_extracted(memory_window, monkeypatch):
    app, window = memory_window
    original_plan = FitPlanDialog.plan
    plans = []
    dialogs = []

    def accept(dialog):
        dialogs.append(weakref.ref(dialog))
        return QDialog.DialogCode.Accepted

    def extract_after_nested_events(dialog):
        # Handlers can show a second modal confirmation before reading values.
        drain_deletions(app)
        assert isValid(dialog)
        return original_plan(dialog)

    monkeypatch.setattr(FitPlanDialog, "exec", accept)
    monkeypatch.setattr(FitPlanDialog, "plan", extract_after_nested_events)
    monkeypatch.setattr(window, "_run_fit", plans.append)
    window.start_fit()
    assert plans[0].curve_ids == [window.active_curve_id]
    drain_deletions(app)
    assert dialogs[0]() is None


def test_transient_widget_cleans_up_on_error_after_reading_fields(memory_window):
    app, window = memory_window
    dialog = QDialog(window)
    editor = QLineEdit("accepted value", dialog)
    with pytest.raises(ValueError, match="handler failed"), transient_widget(dialog):
        dialog.accept()
        drain_deletions(app)
        assert editor.text() == "accepted value"
        raise ValueError("handler failed")
    drain_deletions(app)
    assert not isValid(dialog)


def test_hidden_notebook_and_paused_fit_release_old_project(memory_window):
    app, window = memory_window
    project_id = window.project.id
    array_ref = weakref.ref(window.project.curves[0].original_x)
    result = Fitter().fit(FitPlan([window.active_curve_id]), window.project.curves, window.project.models)
    result_array_ref = weakref.ref(result.curve_outputs[window.active_curve_id].residual)
    window._paused_result = result
    window._sequential_pause_result = result
    window._sequential_resume_plan = FitPlan([window.active_curve_id])
    window._fit_undo_before = {"results": {"last_fit": result}}
    window._ensure_notebook_widget()
    assert window.notebook_dock.isHidden()
    notebook_ref = weakref.ref(window._notebook_widget)
    window.worksheet.set_curve(window.project.curves[0])
    assert window.worksheet.table.model().rowCount() > 0
    del result
    window.new_project()
    QTest.qWait(20)
    assert window._notebook_widget is None
    assert notebook_ref() is None
    assert not any(isinstance(obj, Project) and obj.id == project_id for obj in gc.get_objects())
    assert result_array_ref() is None
    assert array_ref() is None
    assert window.worksheet.table.model().rowCount() == 0
    assert window._sequential_resume_plan is None
    assert not window.resume_action.isEnabled()
    window.open_notebook()
    assert window._notebook_widget.project is window.project


@pytest.mark.parametrize("change", ["delete_curve", "replace_project"])
def test_hidden_worksheet_releases_arrays_after_project_edits(memory_window, change):
    _, window = memory_window
    window.worksheet.set_curve(window.project.curves[0])
    array_ref = weakref.ref(window.project.curves[0].x.base)
    if change == "delete_curve":
        for series in window.project.dataset.series:
            series.curves.clear()
        window.project.models.clear()
    else:
        # Plugins and Undo can replace the context without new_project().
        window.project = Project()
    window.active_curve_id = None
    window.refresh_all()
    assert window.worksheet.table.model().rowCount() == 0
    assert array_ref() is None


@pytest.mark.parametrize("action", ["new", "open", "recovery"])
@pytest.mark.parametrize("activity", ["fit", "automation"])
def test_project_replacement_waits_for_running_activity(memory_window, monkeypatch, action, activity):
    _, window = memory_window
    original = window.project
    notices = []
    monkeypatch.setattr(window, "_notify", lambda text, **kwargs: notices.append(text))
    if activity == "fit":
        window._thread = object()
    else:
        window.automation_runner.process = object()
    try:
        if action == "new":
            window.new_project()
        elif action == "open":
            window.open_project("must-not-be-read.fitproj")
        else:
            window.show_recovery_sessions()
        assert window.project is original
        assert notices
    finally:
        window._thread = None
        window.automation_runner.process = None
