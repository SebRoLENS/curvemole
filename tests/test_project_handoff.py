from __future__ import annotations

import json
import os
import socket

import pytest

from curvemole.core.project_handoff import (
    file_digest,
    pending_requests,
    read_reply,
    reply_to_request,
    request_control,
)
from curvemole.core.project import Project
from curvemole.core.serialization import ProjectLock, save_project


def test_local_crash_recovers_dead_process(tmp_path, monkeypatch):
    path = tmp_path / "crash.fitproj"
    marker = tmp_path / "crash.fitproj.lock"
    marker.write_text(json.dumps({
        "pid": 9876543, "host": socket.gethostname(),
        "session_id": "old", "process_start": "old-boot:1",
    }), encoding="utf-8")
    monkeypatch.setattr("curvemole.core.serialization.process_alive", lambda pid: False)
    with ProjectLock(path) as lock:
        assert lock.acquired
        assert ProjectLock.owner(path)["session_id"] == lock.session_id
    assert not marker.exists()


def test_reused_pid_recovers_old_session(tmp_path, monkeypatch):
    path = tmp_path / "pid.fitproj"
    marker = tmp_path / "pid.fitproj.lock"
    marker.write_text(json.dumps({
        "pid": os.getpid(), "host": socket.gethostname(),
        "session_id": "old", "process_start": "previous-boot:123",
    }), encoding="utf-8")
    monkeypatch.setattr("curvemole.core.serialization.process_alive", lambda pid: True)
    monkeypatch.setattr("curvemole.core.serialization._process_identity", lambda pid: "new-boot:456")
    with ProjectLock(path) as lock:
        assert lock.acquired
        assert lock.owns()


def test_silent_remote_lock_is_never_assumed_dead(tmp_path):
    path = tmp_path / "remote.fitproj"
    marker = tmp_path / "remote.fitproj.lock"
    marker.write_text(json.dumps({
        "host": "different-workstation.example", "pid": 777,
        "session_id": "remote-session", "heartbeat_at": "1999-01-01T00:00:00+00:00",
    }), encoding="utf-8")
    with ProjectLock(path) as lock:
        assert not lock.acquired
    assert ProjectLock.owner(path)["session_id"] == "remote-session"


def test_requested_transfer_uses_matching_session_and_project_digest(tmp_path):
    path = save_project(Project("shared"), tmp_path / "shared.fitproj")
    owner = ProjectLock(path)
    owner.__enter__()
    assert owner.owns()
    try:
        request = request_control(path, owner.session_id)
        assert pending_requests(path, owner.session_id) == [request]
        assert pending_requests(path, "some-other-session") == []
        digest = file_digest(path)
        reply_to_request(path, request, accepted=True, digest=digest)
        response = read_reply(path, request)
        assert response["project_sha256"] == digest
        assert response["requester_session"] == request["requester_session"]
    finally:
        owner.__exit__(None, None, None)

    with ProjectLock(path, takeover_from=owner.session_id) as new_owner:
        assert new_owner.owns()


def test_authorized_handoff_does_not_take_unrelated_session(tmp_path):
    path = tmp_path / "session.fitproj"
    with ProjectLock(path) as owner:
        other = ProjectLock(path, takeover_from="not-this-session")
        other.__enter__()
        assert not other.acquired
        assert owner.owns()


def test_releasing_old_lock_cannot_erase_new_ownership(tmp_path):
    path = tmp_path / "ownership.fitproj"
    owner = ProjectLock(path)
    owner.__enter__()
    assert owner.owns()
    marker = tmp_path / "ownership.fitproj.lock"
    successor = {"session_id": "new-owner", "host": "remote.example", "pid": 99}
    marker.write_text(json.dumps(successor), encoding="utf-8")
    owner.__exit__(None, None, None)
    assert ProjectLock.owner(path)["session_id"] == "new-owner"


def test_precommit_guard_blocks_overwrite_when_version_changes(tmp_path):
    path = save_project(Project("first"), tmp_path / "data.fitproj")
    original = file_digest(path)
    with pytest.raises(RuntimeError, match="conflict"):
        save_project(
            Project("second"), path,
            pre_commit_check=lambda: (_ for _ in ()).throw(RuntimeError("conflict")),
        )
    assert file_digest(path) == original


def test_save_as_moves_gui_lock_to_new_project(tmp_path, monkeypatch):
    pytest.importorskip("PySide6", exc_type=ImportError)
    pytest.importorskip("pyqtgraph", exc_type=ImportError)
    from PySide6.QtWidgets import QApplication
    from curvemole.gui.main_window import MainWindow

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CURVEMOLE_DISABLE_PLUGINS", "1")
    app = QApplication.instance() or QApplication([])
    first = tmp_path / "first.fitproj"
    second = tmp_path / "second.fitproj"
    window = MainWindow()
    try:
        window.project.name = "project"
        assert window._manual_save_controller.save(first, save_project)
        assert (tmp_path / "first.fitproj.lock").exists()
        assert window._manual_save_controller.save(second, save_project)
        assert not (tmp_path / "first.fitproj.lock").exists()
        assert (tmp_path / "second.fitproj.lock").exists()
        assert window._project_lock.project_path == second
        assert window._project_lock.owns()
    finally:
        window.close()
        app.processEvents()
    assert not (tmp_path / "second.fitproj.lock").exists()


def test_owner_releases_on_request_and_requester_recovers_editing(tmp_path, monkeypatch):
    pytest.importorskip("PySide6", exc_type=ImportError)
    pytest.importorskip("pyqtgraph", exc_type=ImportError)
    from PySide6.QtWidgets import QApplication
    from curvemole.gui.main_window import MainWindow

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CURVEMOLE_DISABLE_PLUGINS", "1")
    app = QApplication.instance() or QApplication([])
    path = save_project(Project("handoff"), tmp_path / "handoff.fitproj")

    owner_window = MainWindow()
    requester_window = MainWindow()
    try:
        owner_window.open_project(path)
        assert owner_window._project_lock.owns()
        current_session = owner_window._project_lock.session_id

        request = request_control(path, current_session)
        owner_window._poll_project_lock()
        assert owner_window.project.read_only
        assert not (tmp_path / "handoff.fitproj.lock").exists()
        assert read_reply(path, request)["accepted"]

        # Simulate another computer that has received both acknowledgement and
        # exact project bytes. We inject its pending request directly because
        # both test windows share the same hostname.
        requester_window.open_project(path)
        requester_window.project.read_only = True
        requester_window._release_lock()
        requester_window._transfer_request = request
        requester_window._transfer_path = path
        requester_window._poll_project_transfer()
        assert not requester_window.project.read_only
        assert requester_window._project_lock.owns()
        assert requester_window._project_disk_digest == file_digest(path)
    finally:
        requester_window.close()
        owner_window.close()
        app.processEvents()
