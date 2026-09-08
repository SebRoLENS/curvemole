from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from curvemole import Project
from curvemole.core.recovery import RecoveryManager
from curvemole.gui.main_window import MainWindow
from curvemole.gui.recovery import RecoveryDialog


def window_with_recoveries(tmp_path):
    app = QApplication.instance() or QApplication([])
    project = Project("Work")
    window = MainWindow(project)
    window.recovery = RecoveryManager(tmp_path / "recovery")
    for i in range(3):
        project.notebook.notes = f"Notes {i}"
        project.touch()
        window._autosave()
    return app, window


def test_save_removes_three_backups_but_failed_or_cancelled_save_preserves_them(tmp_path, monkeypatch):
    app, window = window_with_recoveries(tmp_path)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    assert not window.save_project()
    assert len(window.recovery.candidates()) == 3
    window.project.path = tmp_path / "saved.fitproj"
    from curvemole.gui import main_window

    with monkeypatch.context() as patch:
        def fail(*args):
            raise OSError("Disk full")
        patch.setattr(main_window, "save_project", fail)
        patch.setattr(window, "_show_error", lambda *args: None)
        assert not window.save_project()
    assert len(window.recovery.candidates()) == 3
    assert window.save_project()
    assert not window.recovery.candidates()
    assert window.project.path.exists()
    window.close()
    app.processEvents()


def test_explicit_discard_on_close_removes_recoveries(tmp_path):
    app, window = window_with_recoveries(tmp_path)
    def discard():
        box = app.activeModalWidget()
        if isinstance(box, QMessageBox):
            box.button(QMessageBox.StandardButton.Discard).click()
    QTimer.singleShot(0, discard)
    assert window.close()
    assert not window.recovery.candidates()
    app.processEvents()


def test_discard_cleans_only_current_project_cancel_preserves(tmp_path, monkeypatch):
    app, window = window_with_recoveries(tmp_path)
    other = Project("Other")
    other.touch()
    window.recovery.autosave(other)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    assert not window._confirm_discard_or_save()
    assert len(window.recovery.candidates(window.project.id)) == 3
    old_id = window.project.id
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window.new_project()
    assert window.project.id != old_id
    assert not window.recovery.candidates(old_id)
    assert window.recovery.candidates(other.id)
    window.close()
    app.processEvents()


def test_cancel_open_does_not_discard_current_recovery(tmp_path, monkeypatch):
    app, window = window_with_recoveries(tmp_path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: ("", ""))
    def unexpected(*args):
        raise AssertionError("No discard question before choosing a file")
    monkeypatch.setattr(QMessageBox, "question", unexpected)
    window.open_project()
    assert len(window.recovery.candidates()) == 3
    window.project.dirty = False
    window.close()
    app.processEvents()


def test_startup_recovery_dialog_and_menu_recover_real_backup(tmp_path):
    app, window = window_with_recoveries(tmp_path)
    window.project = Project()
    window.refresh_all()
    seen = []
    def later():
        dialog = app.activeModalWidget()
        if isinstance(dialog, RecoveryDialog):
            seen.append(dialog.sessions.topLevelItemCount())
            assert dialog.versions.count() == 3
            dialog.later_button.click()
    QTimer.singleShot(0, later)
    window.show_recovery_sessions(startup=True)
    assert seen == [1]
    assert len(window.recovery.candidates()) == 3
    def recover():
        dialog = app.activeModalWidget()
        if isinstance(dialog, RecoveryDialog):
            dialog.recover_button.click()
    QTimer.singleShot(0, recover)
    window.recovery_action.trigger()
    assert window.project.name == "Work"
    assert window.project.notebook.notes == "Notes 2"
    assert window.project.path is None
    assert window.project.dirty
    assert len(window.recovery.candidates()) == 3
    window.project.path = tmp_path / "recovered.fitproj"
    assert window.save_project()
    assert not window.recovery.candidates()
    window.close()
    app.processEvents()
