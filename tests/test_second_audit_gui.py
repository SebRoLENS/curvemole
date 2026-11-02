"""Atomic import and verified, responsive handoff regressions."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from curvemole import Curve, Project, Series
from curvemole.core.data import Dataset
from curvemole.core.errors import DataValidationError
from curvemole.core.project_handoff import file_digest, reply_to_request
from curvemole.core.serialization import ProjectLock, save_project
from curvemole.gui.app import CurveMoleMainWindow


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    instance = CurveMoleMainWindow()
    yield instance
    instance._cancel_project_transfer()
    instance.project.dirty = False
    instance.close()
    app.processEvents()


def test_import_conflict_is_rejected_before_push_and_preserves_original(window):
    original = Series('original', [Curve('old', [0, 1], [1, 2])])
    window.project.add_series(original)
    revision = window.project.revision
    new = Series('partial', [Curve('new', [0, 1], [3, 4])])
    collision = Series('collision', [Curve('new2', [0, 1], [5, 6])], id=original.id)
    acquisition = SimpleNamespace(dataset=Dataset([new, collision]), models={}, results={})
    with pytest.raises(DataValidationError):
        window.folder_import.commit(acquisition)
    assert window.project.dataset.series == [original]
    assert window.project.revision == revision
    assert window.undo_stack.count() == 0
    window.undo_stack.undo()
    assert window.project.curves == original.curves


def test_import_undo_redo_restores_only_the_imported_lot_and_handles_empty_tail(window):
    original = Series('original', [Curve('old', [0, 1], [1, 2])])
    window.project.add_series(original)
    curve = Curve('new', [0, 1], [3, 4])
    imported = Series('imported', [curve])
    acquisition = SimpleNamespace(dataset=Dataset([imported, Series('empty tail')]), models={}, results={})
    window.folder_import.follow = True
    window.folder_import.commit(acquisition)
    assert len(window.project.curves) == 2 and window.active_curve_id == curve.id
    window.undo_stack.undo()
    assert window.project.dataset.series == [original]
    assert curve.id not in window.project.models
    window.undo_stack.redo()
    assert len(window.project.curves) == 2 and window.active_curve_id == curve.id
    assert original.curves[0].id in window.project.models and curve.id in window.project.models


def prepare_transfer(window, tmp_path):
    path = save_project(Project('confirmed'), tmp_path / 'shared.fitproj')
    digest = file_digest(path)
    request = dict(request_id='audit', owner_session='old', requester_session='new', created_at=time.time())
    reply_to_request(path, request, accepted=True, digest=digest)
    window.project.path = path
    window.project.read_only = True
    window._transfer_request = request
    window._transfer_path = path
    window._transfer_monitor.stop()
    return path, digest


def test_handoff_rejects_replacement_after_lock_without_replacing_session(window, tmp_path, monkeypatch):
    path, digest = prepare_transfer(window, tmp_path)
    original = window.project
    replacement = save_project(Project('unconfirmed'), tmp_path / 'replacement.fitproj')
    class InterleavedLock(ProjectLock):
        def __enter__(self):
            result = super().__enter__()
            replacement.replace(path)
            return result
    monkeypatch.setattr('curvemole.gui.main_window.ProjectLock', InterleavedLock)
    window._poll_project_transfer()
    assert window.project is original and window.project.read_only
    assert window._project_lock is None and ProjectLock.owner(path) is None
    assert file_digest(path) != digest
    assert window._transfer_request is not None


def test_handoff_rejects_replacement_during_read_and_keeps_ui_responsive(window, tmp_path, monkeypatch):
    import curvemole.gui.main_window as main
    path, _ = prepare_transfer(window, tmp_path)
    original = window.project
    real_loader = main.load_project
    progressed = []
    def interleaved_loader(source, **kwargs):
        time.sleep(.04)
        project = real_loader(source, **kwargs)
        save_project(Project('unconfirmed'), source)
        return project
    monkeypatch.setattr(main, 'load_project', interleaved_loader)
    QTimer.singleShot(10, lambda: progressed.append(True))
    window._poll_project_transfer()
    assert progressed and window.project is original
    assert window.project.read_only and window._project_lock is None
    assert not window._project_loading
