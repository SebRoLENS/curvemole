import threading

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from curvemole import Project
from curvemole.core.recovery import RecoveryManager
from curvemole.core.serialization import load_project, save_project
from curvemole.gui.main_window import MainWindow


@pytest.fixture
def saved_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project("Internal name"))
    window.project.path = tmp_path / "Named experiment.fitproj"
    window.recovery = RecoveryManager(tmp_path / "recovery")
    window.project.notebook.notes = "Before"
    window.project.touch()
    window.recovery.autosave(window.project)
    yield app, window
    window.project.dirty = False
    window.close()
    window.deleteLater()
    app.processEvents()


def test_manual_writer_runs_off_gui_and_keeps_later_edits_and_backups(saved_window, monkeypatch):
    app, window = saved_window
    gui_thread = threading.get_ident()
    entered, release = threading.Event(), threading.Event()
    worker_threads = []
    pulses = []

    def writer(*args, **kwargs):
        worker_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(10)
        return save_project(*args, **kwargs)

    monkeypatch.setattr("curvemole.gui.main_window.save_project", writer)

    def edit_when_started():
        if not entered.is_set():
            QTimer.singleShot(5, edit_when_started)
            return
        pulses.append(window._manual_save_controller._status.isVisibleTo(window.statusBar()))
        window.project.notebook.notes = "During save"
        window.project.touch()
        release.set()

    QTimer.singleShot(0, edit_when_started)
    try:
        assert window.save_project()
    finally:
        release.set()
    assert pulses == [True]
    assert worker_threads and worker_threads[0] != gui_thread
    assert load_project(window.project.path).notebook.notes == "Before"
    assert window.project.notebook.notes == "During save"
    assert window.project.dirty
    assert len(window.recovery.candidates()) == 1
    assert window.save_project()
    assert not window.project.dirty
    assert window.recovery.candidates() == []


def test_close_during_save_waits_without_implicitly_discarding_new_edits(saved_window, monkeypatch):
    app, window = saved_window
    entered, release = threading.Event(), threading.Event()
    results = []

    def writer(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return save_project(*args, **kwargs)

    monkeypatch.setattr("curvemole.gui.main_window.save_project", writer)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)

    def close_when_started():
        if not entered.is_set():
            QTimer.singleShot(5, close_when_started)
            return
        window.project.notebook.notes = "New edits"
        window.project.touch()
        QTimer.singleShot(10, release.set)
        results.append(window.close())

    QTimer.singleShot(0, close_when_started)
    try:
        assert window.save_project()
    finally:
        release.set()
    assert results == [False]
    assert not window._session_finished
    assert window.project.dirty
    assert window.recovery.candidates()


def test_successful_save_resolves_pending_recovery(saved_window):
    from curvemole.gui.recovery_session import RecoverySession

    _app, window = saved_window
    session = RecoverySession(window.recovery.directory)
    window._recovery_session = session
    session.record(window.project.id)
    assert window.save_project()
    assert window.project.id not in session.projects
    window.close()
    assert not session.marker.exists()


def test_portable_copy_does_not_clear_dirty_state_or_recovery(saved_window, tmp_path):
    _app, window = saved_window
    original_path = window.project.path
    destination = tmp_path / "Portable.fitproj"
    assert window._manual_save_controller.save(destination, save_project, portable=True)
    assert destination.exists()
    assert window.project.path == original_path
    assert window.project.dirty
    assert len(window.recovery.candidates()) == 1


def test_new_project_waits_for_active_save(saved_window, monkeypatch):
    _app, window = saved_window
    old_id = window.project.id
    entered, release = threading.Event(), threading.Event()

    def writer(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return save_project(*args, **kwargs)

    monkeypatch.setattr("curvemole.gui.main_window.save_project", writer)

    def switch():
        if not entered.is_set():
            QTimer.singleShot(5, switch)
            return
        QTimer.singleShot(10, release.set)
        window.new_project()

    QTimer.singleShot(0, switch)
    try:
        assert window.save_project()
    finally:
        release.set()
    assert window.project.id != old_id
    assert window.recovery.candidates(old_id) == []


def test_failed_manual_save_keeps_backups_and_dirty_state(saved_window, monkeypatch):
    _app, window = saved_window
    errors = []
    def fail(*args, **kwargs):
        raise OSError("Disk full")
    monkeypatch.setattr("curvemole.gui.main_window.save_project", fail)
    monkeypatch.setattr(window, "_show_error", lambda _title, error: errors.append(str(error)))
    assert not window.save_project()
    assert errors == ["Disk full"]
    assert window.project.dirty
    assert len(window.recovery.candidates()) == 1
