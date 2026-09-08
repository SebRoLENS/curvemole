from __future__ import annotations

from curvemole import Project
from curvemole.core.recovery import RecoveryManager


def test_rotation_same_second_project_switch_and_clear(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from curvemole.core import recovery

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 8, tzinfo=UTC)

    monkeypatch.setattr(recovery, "datetime", FixedClock)
    manager = RecoveryManager(tmp_path)
    first, second = Project("First"), Project("Second")
    for index in range(5):
        first.notebook.notes = str(index)
        first.touch()
        assert manager.autosave(first)
    assert len(manager.candidates(first.id)) == 3
    assert manager.recover(manager.candidates(first.id)[0]).notebook.notes == "4"
    manager._last_project_id, manager._last_revision = first.id, first.revision
    assert manager.autosave(first) is None
    second.revision = first.revision
    second.dirty = True
    assert manager.autosave(second)
    manager.clear(first.id)
    assert not manager.candidates(first.id)
    assert len(manager.candidates(second.id)) == 1
    manager.clear(second.id)
    assert manager.autosave(second)


def test_recover_returns_unsaved_copy_and_keeps_backup(tmp_path):
    project = Project("Experiment")
    project.notebook.notes = "Before crash"
    project.touch()
    manager = RecoveryManager(tmp_path)
    path = manager.autosave(project)
    recovered = manager.recover(path)
    assert recovered.dirty
    assert recovered.path is None
    assert recovered.notebook.notes == "Before crash"
    assert path.exists()
    assert manager.autosave(recovered)
