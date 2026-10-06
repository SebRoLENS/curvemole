import threading
import time
from contextlib import suppress
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from curvemole import Curve, Project
from curvemole.core import recovery
from curvemole.core.recovery import RecoveryManager
from curvemole.core.serialization import load_project
from curvemole.gui.main_window import MainWindow


def wait_until(app, predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert predicate()


@pytest.fixture
def autosave_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("CURVEMOLE_DISABLE_PLUGINS", "1")
    project = Project("Autosave")
    project.add_curve(Curve("Spectrum", [0, 1, 2], [0, 1, 0]))
    project.notebook.notes = "Before"
    window = MainWindow(project)
    window.autosave_timer.stop()
    window.recovery = RecoveryManager(tmp_path / "recovery")
    logs = []
    monkeypatch.setattr(window, "_log", logs.append)
    yield app, window, logs
    future = window._autosave_controller._future
    window._autosave_controller.shutdown()
    if future is not None:
        with suppress(Exception):
            future.result(timeout=10)
    window._thread = None
    window.project.dirty = False
    window.close()
    window.deleteLater()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def paused_writer(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    original = recovery.save_project

    def paused(project, *args, **kwargs):
        calls.append((project.revision, threading.get_ident()))
        entered.set()
        assert release.wait(10)
        return original(project, *args, **kwargs)

    monkeypatch.setattr(recovery, "save_project", paused)
    yield entered, release, calls
    release.set()


def test_gui_remains_responsive_and_saves_a_coherent_snapshot(autosave_window, paused_writer):
    app, window, _ = autosave_window
    entered, release, calls = paused_writer
    gui_thread = threading.get_ident()
    records = []
    window._recovery_session = SimpleNamespace(
        record=lambda project_id: records.append((project_id, threading.get_ident())), finish=lambda: None,
    )
    revision = window.project.revision
    window._autosave()
    assert entered.wait(10)
    assert records == [(window.project.id, gui_thread)]
    heartbeat = []
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    window.project.notebook.notes = "Edits during autosave"
    window.project.touch()
    app.processEvents()
    assert heartbeat == [True]
    assert not window._autosave_controller._future.done()
    release.set()
    wait_until(app, lambda: not window._autosave_controller.busy)
    assert calls == [(revision, calls[0][1])]
    assert calls[0][1] != gui_thread
    assert records == [(window.project.id, gui_thread)]
    assert load_project(window.recovery.candidates()[0]).notebook.notes == "Before"
    assert window.project.notebook.notes == "Edits during autosave"
    assert window.project.dirty and window.project.path is None
    assert window.recovery.needs_autosave(window.project)


def test_overlapping_requests_coalesce_to_latest_revision(autosave_window, paused_writer):
    app, window, _ = autosave_window
    entered, release, calls = paused_writer
    first_revision = window.project.revision
    window._autosave()
    assert entered.wait(10)
    for index in range(5):
        window.project.notebook.notes = f"Edits {index}"
        window.project.touch()
        window._autosave()
    assert len(calls) == 1
    release.set()
    wait_until(app, lambda: not window._autosave_controller.busy)
    assert [revision for revision, _ in calls] == [first_revision, window.project.revision]
    paths = window.recovery.candidates()
    assert len(paths) == 2
    assert load_project(paths[0]).notebook.notes == "Edits 4"


@pytest.mark.parametrize("action", ["save", "discard", "close"])
def test_manual_save_discard_and_close_cannot_resurrect_backups(
    autosave_window, paused_writer, tmp_path, monkeypatch, action,
):
    app, window, logs = autosave_window
    entered, release, _ = paused_writer
    project_id = window.project.id
    window._autosave()
    assert entered.wait(10)
    future = window._autosave_controller._future
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    if action == "save":
        window.project.path = tmp_path / "saved.fitproj"
        assert window.save_project()
    elif action == "discard":
        window.new_project()
        assert window.project.id != project_id
    else:
        assert window.close()
    release.set()
    assert future.result(timeout=10) is None
    wait_until(app, lambda: not window._autosave_controller.busy)
    assert window.recovery.candidates(project_id) == []
    assert not any(log.startswith("Recovery saved:") for log in logs)
    assert not list(window.recovery.directory.glob(".autosave-*"))


def test_autosave_waits_for_fit_before_capturing(autosave_window):
    app, window, _ = autosave_window
    window._thread = object()
    window._autosave()
    assert window._autosave_controller._future is None
    assert window._autosave_controller.busy
    window.project.notebook.notes = "After fit"
    window.project.touch()
    window._thread = None
    wait_until(app, lambda: not window._autosave_controller.busy)
    assert load_project(window.recovery.candidates()[0]).notebook.notes == "After fit"


def test_unchanged_saved_and_read_only_projects_need_no_new_snapshot(autosave_window, monkeypatch):
    app, window, _ = autosave_window
    window._autosave()
    wait_until(app, lambda: not window._autosave_controller.busy)
    monkeypatch.setattr("curvemole.gui.autosave.capture_project_snapshot",
                        lambda *args: pytest.fail("Unnecessary snapshot"))
    window._autosave()
    assert not window._autosave_controller.busy
    window.project.touch()
    window.project.dirty = False
    window._autosave()
    window.project.dirty = True
    window.project.read_only = True
    window._autosave()
    assert not window._autosave_controller.busy
    assert len(window.recovery.candidates()) == 1


def test_failed_background_save_is_logged_and_can_be_retried(autosave_window, monkeypatch):
    app, window, logs = autosave_window
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise OSError("Disk full")
        patch.setattr(recovery, "save_project", fail)
        window._autosave()
        wait_until(app, lambda: not window._autosave_controller.busy)
    assert any("Autosave failed: Disk full" in log for log in logs)
    assert window.project.dirty
    assert window.recovery.candidates() == []
    window._autosave()
    wait_until(app, lambda: not window._autosave_controller.busy)
    assert len(window.recovery.candidates()) == 1
