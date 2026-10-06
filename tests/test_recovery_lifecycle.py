import os

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from curvemole import Project
from curvemole.core.recovery import RecoveryManager
from curvemole.gui.recovery import RecoveryDialog
from curvemole.gui.recovery_monitor import should_warn
from curvemole.gui.recovery_session import RecoverySession


def test_deferred_sessions_survive_clean_exit_repeatedly_and_resolve(tmp_path):
    project = Project(id="project_one")
    project.touch()
    RecoveryManager(tmp_path).autosave(project)
    first = RecoverySession(tmp_path)
    first.record("project_one")
    first.finish(preserve=True)
    for _ in range(3):
        current = RecoverySession(tmp_path)
        assert current.crashed_projects == {"project_one"}
        assert current.projects == {"project_one"}
        current.finish(preserve=True)
        assert len(list(tmp_path.glob("session-*.json"))) == 1
    last = RecoverySession(tmp_path)
    last.resolve("project_one")
    last.finish(preserve=True)
    assert not list(tmp_path.glob("session-*.json"))


def test_failed_session_transfer_preserves_previous_marker(tmp_path, monkeypatch):
    project = Project(id="one")
    project.touch()
    RecoveryManager(tmp_path).autosave(project)
    first = RecoverySession(tmp_path)
    first.record("one")
    first.finish(preserve=True)
    with monkeypatch.context() as patch:
        def fail(*args):
            raise OSError("Disk full")
        patch.setattr(RecoverySession, "record", fail)
        with pytest.raises(OSError):
            RecoverySession(tmp_path)
    assert first.marker.exists()
    recovered = RecoverySession(tmp_path)
    assert "one" in recovered.projects
    recovered.finish()


def test_warning_bands_are_persistent_and_reset_only_below_fifty(tmp_path):
    filename = str(tmp_path / "settings.ini")
    settings = QSettings(filename, QSettings.Format.IniFormat)
    assert not should_warn(settings, 49, announce=True)
    assert should_warn(settings, 50, announce=True)
    assert not should_warn(settings, 53, announce=True)
    reloaded = QSettings(filename, QSettings.Format.IniFormat)
    assert not should_warn(reloaded, 53, announce=True)
    assert not should_warn(reloaded, 99, announce=True)
    assert should_warn(reloaded, 100, announce=True)
    assert not should_warn(reloaded, 149, announce=True)
    assert should_warn(reloaded, 150, announce=True)
    assert not should_warn(reloaded, 75, announce=True)
    assert not should_warn(reloaded, 100, announce=True)
    assert not should_warn(reloaded, 49)
    assert should_warn(reloaded, 50, announce=True)
    # A periodic count check must not consume an unseen startup warning.
    assert not should_warn(reloaded, 220)
    assert should_warn(reloaded, 220, announce=True)
    assert not should_warn(reloaded, 249, announce=True)
    assert should_warn(reloaded, 250, announce=True)


@pytest.mark.parametrize("count,band", [(0, 0), (49, 0), (50, 1), (99, 1), (100, 2), (149, 2), (150, 3), (399, 7), (400, 8)])
def test_warning_thresholds_are_multiples_of_fifty(count, band):
    from curvemole.gui.recovery_monitor import warning_band
    assert warning_band(count) == band


def test_dead_process_staging_files_removed_but_live_and_recovery_files_retained(tmp_path, monkeypatch):
    dead = tmp_path / ".autosave-987654-stale.fitproj"
    inner = tmp_path / "..autosave-987654-stale.fitproj.random.tmp"
    live = tmp_path / f".autosave-{os.getpid()}-active.fitproj"
    completed = tmp_path / "one.recovery-stamp.fitproj"
    for path in (dead, inner, live, completed):
        path.write_bytes(b"placeholder")
    monkeypatch.setattr("curvemole.core.recovery.process_alive", lambda pid: pid == os.getpid())
    RecoveryManager(tmp_path)
    assert not dead.exists() and not inner.exists()
    assert live.exists() and completed.exists()


def test_named_backup_proposal_and_individual_deletion(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    manager = RecoveryManager(tmp_path)
    project = Project()
    project.path = tmp_path / "Ruby pressure.fitproj"
    for index in range(8):
        project.notebook.notes = str(index)
        project.touch()
        manager.autosave(project)
    paths = manager.candidates()
    assert len(paths) == 6
    dialog = RecoveryDialog(manager, paths)
    try:
        root = dialog.sessions.topLevelItem(0)
        assert root.text(0) == "Ruby pressure"
        assert root.childCount() == 6
        assert "Ruby pressure.fitproj" in dialog.message.text()
        assert paths[0].name in dialog.message.text()
        assert "backup 1" in dialog.versions.currentText()
        old = root.child(5)
        dialog.sessions.setCurrentItem(old)
        assert dialog.versions.currentData() == paths[5]
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        dialog._delete()
        assert len(manager.candidates()) == 5
        assert not paths[5].exists()
        assert paths[0].exists()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_invalid_copy_is_counted_and_can_be_deleted_without_affecting_valid_copy(tmp_path):
    manager = RecoveryManager(tmp_path)
    project = Project("Valid")
    project.touch()
    good = manager.autosave(project)
    bad = tmp_path / f"{project.id}.recovery-corrupt.fitproj"
    bad.write_bytes(b"broken")
    assert len(manager.files()) == 2
    assert manager.candidates() == [good]
    assert not manager.description(bad)["readable"]
    assert manager.delete_copies([bad]) == set()
    assert manager.candidates() == [good]


def test_delete_rejects_paths_outside_recovery_cache(tmp_path):
    manager = RecoveryManager(tmp_path / "cache")
    outside = tmp_path / "saved.fitproj"
    outside.write_bytes(b"original")
    with pytest.raises(ValueError):
        manager.delete_copies([outside])
    assert outside.exists()


def test_startup_warning_opens_manager_once_per_band_and_resets_after_cleanup(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from curvemole.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project())
    window.settings = QSettings(str(tmp_path / "warning.ini"), QSettings.Format.IniFormat)
    window.recovery = RecoveryManager(tmp_path / "cache")
    window._crashed_recovery_projects = set()
    warnings, dialogs = [], []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, text: warnings.append(text))

    class InspectDialog(RecoveryDialog):
        def exec(self):
            dialogs.append(self.message.text())
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr("curvemole.gui.recovery.RecoveryDialog", InspectDialog)

    def populate(project_number, copies):
        project = Project(f"Group {project_number}")
        project.path = tmp_path / f"Group {project_number}.fitproj"
        for index in range(copies):
            project.notebook.notes = str(index)
            project.touch()
            window.recovery.autosave(project)

    try:
        for number in range(8):
            populate(number, 6)
        populate(8, 5)
        assert len(window.recovery.files()) == 53
        window.show_recovery_sessions(startup=True)
        assert len(warnings) == len(dialogs) == 1
        assert "53" in warnings[0] and "disk" in warnings[0]
        assert "Group 8.fitproj" in dialogs[0]
        window.show_recovery_sessions(startup=True)
        assert len(warnings) == len(dialogs) == 1
        for number in range(9, 16):
            populate(number, 6)
        populate(16, 5)
        assert len(window.recovery.files()) == 100
        window.show_recovery_sessions(startup=True)
        assert len(warnings) == len(dialogs) == 2
        window.recovery.delete_copies(window.recovery.files()[49:])
        window._monitor_recovery_count()
        populate(17, 3)
        window.show_recovery_sessions(startup=True)
        assert len(warnings) == len(dialogs) == 3
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_quit_without_explicit_discard_keeps_recovery_proposal(tmp_path):
    from curvemole.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    project = Project("Interrupted")
    project.touch()
    window = MainWindow(project)
    window.recovery = RecoveryManager(tmp_path / "cache")
    backup = window.recovery.autosave(project)
    session = RecoverySession(window.recovery.directory)
    window._recovery_session = session
    session.record(project.id)
    window._finish_session()  # Application quit without QMainWindow.closeEvent.
    assert backup.exists()
    next_session = RecoverySession(window.recovery.directory)
    assert project.id in next_session.crashed_projects
    next_session.finish(preserve=True)
    again = RecoverySession(window.recovery.directory)
    assert project.id in again.crashed_projects
    again.resolve(project.id)
    again.finish(preserve=True)
    project.dirty = False
    window.close()
    window.deleteLater()
    app.processEvents()
