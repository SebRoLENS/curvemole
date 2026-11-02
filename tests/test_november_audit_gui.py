"""Desktop regressions: consistent snapshots, session isolation and updater integrity."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication

from curvemole import Curve, Project
from curvemole.core.project_handoff import file_digest
from curvemole.core.serialization import save_project
from curvemole.core.uncertainty import ResamplingResult
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.updates import ReleaseAsset, UpdateController


@pytest.fixture
def app():
    application = QApplication.instance() or QApplication([])
    yield application
    application.processEvents()


def test_open_reads_after_confirmation_and_preserves_failed_open_session(
    app, tmp_path, monkeypatch
):
    path = tmp_path / "target.fitproj"
    save_project(Project("old"), path)
    window = CurveMoleMainWindow()

    def confirm():
        save_project(Project("latest"), path)
        return True

    monkeypatch.setattr(window, "_confirm_discard_or_save", confirm)
    window.open_project(path)
    assert window.project.name == "latest"
    assert window._project_disk_digest == file_digest(path)
    lock = window._project_lock
    errors = []
    monkeypatch.setattr(window, "_show_error", lambda *args: errors.append(args))
    window.open_project(tmp_path / "missing.fitproj")
    assert (
        errors and window.project.name == "latest" and window._project_lock is lock and lock.owns()
    )
    window.project.dirty = False
    window.close()


def test_new_project_clears_custom_layer(app, monkeypatch):
    p = Project(custom_functions=[{"identifier": "audit_project_only", "formula": "amplitude*x"}])
    window = CurveMoleMainWindow(p)
    assert "audit_project_only" in window.registry.identifiers()
    monkeypatch.setattr(window, "_confirm_discard_or_save", lambda: True)
    window.new_project()
    assert "audit_project_only" not in window.registry.identifiers()
    window.close()


def test_project_loading_processes_gui_events_and_cancellation(app):
    from curvemole.core.errors import FitCancelled
    from curvemole.gui.project_loading import load_project_responsive

    window = CurveMoleMainWindow()
    progressed = []

    def loader(path, cancellation):
        assert path == "test"
        import time

        for _ in range(200):
            cancellation.raise_if_cancelled()
            time.sleep(0.001)
        return Project("done")

    old_project = window.project

    def during_load():
        assert not window._can_replace_project()
        assert not window._ensure_editable()
        window.new_project()
        progressed.append(True)

    QTimer.singleShot(15, during_load)
    result = load_project_responsive(window, "test", loader)
    assert result.name == "done" and progressed
    assert window.project is old_project
    assert not window._project_loading

    def cancel_loader(path, cancellation):
        cancellation.cancel()
        cancellation.raise_if_cancelled()

    with pytest.raises(FitCancelled):
        load_project_responsive(window, "test", cancel_loader)
    window.close()


@pytest.mark.parametrize("digest", ["", "md5:1234", "sha256:short"])
def test_update_cannot_reach_installer_without_supported_digest(tmp_path, monkeypatch, digest):
    warnings = []
    monkeypatch.setattr(
        "curvemole.gui.updates.QMessageBox.warning", lambda *args: warnings.append(args)
    )
    path = tmp_path / "download"
    path.write_bytes(b"not an executable")
    installed = []
    stub = SimpleNamespace(
        _download_path=path,
        _download_asset=ReleaseAsset("x", "https://example.invalid", digest),
        _download_version="1.0.0",
        _download_handle=None,
        _drain_download=lambda: None,
        _install_download=lambda *args: installed.append(True),
        window=SimpleNamespace(
            tr=lambda s: s,
            _log=lambda s: None,
            progress=SimpleNamespace(setVisible=lambda v: None),
            fit_action=SimpleNamespace(setEnabled=lambda v: None),
        ),
    )
    reply = SimpleNamespace(
        error=lambda: QNetworkReply.NetworkError.NoError, deleteLater=lambda: None
    )
    UpdateController._download_finished(stub, reply)
    assert warnings and not installed and not path.exists()


def test_uncertainty_report_never_materializes_sample_lists(app, monkeypatch):
    class NoListArray(np.ndarray):
        def tolist(self):
            raise AssertionError("Unnecessary sample conversion")

    window = CurveMoleMainWindow()
    c = Curve("c", [0, 1, 2, 3], [1, 2, 1, 2])
    window.project.add_curve(c)
    from curvemole import Component, Fitter

    window.project.add_component(c.id, Component.create("constant"))
    baseline = Fitter().fit_single(c, window.project.model_for(c.id))
    samples = np.ones((10, 1)).view(NoListArray)
    result = ResamplingResult("residual_bootstrap", 10, 10, 0, 1, ["p"], samples, {}, 0.95, {})
    monkeypatch.setattr(window, "_sync_uncertainty_method", lambda: None)
    window._store_uncertainty_result(c.id, baseline, result)
    assert (
        "samples"
        not in window.project.results["uncertainty_reports_by_curve"][c.id]["residual_bootstrap"][
            "analysis"
        ]
    )
    window.project.dirty = False
    window.close()
