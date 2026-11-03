"""Size thresholds are overridable without relaxing project integrity checks."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from curvemole import Curve, Project
from curvemole.core.archive_validation import ArchiveLimits, read_array_header
from curvemole.core.errors import FitCancelled, ProjectFormatError, ProjectResourceLimitError
from curvemole.core.project_handoff import file_digest
from curvemole.core.serialization import load_project, save_project
from curvemole.gui.project_loading import load_project_responsive


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    widget = QWidget()
    yield widget
    widget.close()
    app.processEvents()


@pytest.fixture
def archive(tmp_path):
    project = Project("Preserved analysis")
    project.add_curve(Curve("signal", np.arange(20.0), np.arange(20.0) ** 2))
    return save_project(project, tmp_path / "project.fitproj")


@pytest.mark.parametrize("resource", ["members", "expanded_bytes", "manifest_bytes", "array_bytes"])
@pytest.mark.parametrize("accept", [False, True])
def test_every_size_budget_can_be_overridden_only_after_consent(
    window, archive, monkeypatch, resource, accept
):
    default = replace(ArchiveLimits(), **{resource: 1})
    monkeypatch.setattr("curvemole.core.serialization.ArchiveLimits", lambda: default)
    with pytest.raises(ProjectResourceLimitError) as caught:
        load_project(archive)
    assert resource in caught.value.required_limits
    prompts = []

    def answer(parent, title, message, buttons, selected):
        assert parent is window and window._project_loading
        assert "exhaust available memory" in message
        assert selected == QMessageBox.StandardButton.No
        prompts.append(message)
        return QMessageBox.StandardButton.Yes if accept else QMessageBox.StandardButton.No

    monkeypatch.setattr("curvemole.gui.project_loading.QMessageBox.warning", answer)
    if accept:
        restored, digest = load_project_responsive(window, archive, load_project, snapshot=True)
        assert digest == file_digest(archive)
        assert restored.name == "Preserved analysis"
        np.testing.assert_array_equal(restored.curves[0].original_y, np.arange(20.0) ** 2)
        # Consent is confined to this call, not a global disabling of validation.
        with pytest.raises(ProjectResourceLimitError):
            load_project(archive)
    else:
        with pytest.raises(FitCancelled):
            load_project_responsive(window, archive, load_project, snapshot=True)
    assert len(prompts) == 1
    assert not window._project_loading


def test_consent_preserves_previously_raised_budgets(window, archive, monkeypatch):
    monkeypatch.setattr(
        "curvemole.core.serialization.ArchiveLimits",
        lambda: replace(ArchiveLimits(), manifest_bytes=1, members=1, expanded_bytes=1, array_bytes=1),
    )
    # The first preflight groups metadata, total size and entry count. The array
    # threshold is discovered later when reading the actual NumPy header.
    monkeypatch.setattr(
        "curvemole.gui.project_loading.ArchiveLimits",
        lambda: replace(ArchiveLimits(), manifest_bytes=1, members=1, expanded_bytes=1, array_bytes=1),
    )
    prompts = []
    monkeypatch.setattr(
        "curvemole.gui.project_loading.QMessageBox.warning",
        lambda *args: prompts.append(args) or QMessageBox.StandardButton.Yes,
    )
    assert load_project_responsive(window, archive, load_project).curves
    assert len(prompts) == 2


def test_consent_does_not_bypass_checksums(window, archive, monkeypatch):
    with zipfile.ZipFile(archive) as source:
        members = {info.filename: source.read(info) for info in source.infolist()}
    name = next(key for key in members if key.endswith("original_y.npy"))
    stream = io.BytesIO()
    np.save(stream, np.zeros(20))
    members[name] = stream.getvalue()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as destination:
        for name, content in members.items():
            destination.writestr(name, content)
    monkeypatch.setattr(
        "curvemole.core.serialization.ArchiveLimits",
        lambda: replace(ArchiveLimits(), manifest_bytes=1),
    )
    monkeypatch.setattr(
        "curvemole.gui.project_loading.QMessageBox.warning",
        lambda *args: QMessageBox.StandardButton.Yes,
    )
    with pytest.raises(ProjectFormatError, match="Checksum mismatch"):
        load_project_responsive(window, archive, load_project)


def test_truncated_array_is_not_an_overridable_size_warning():
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        stream, {"descr": "<f8", "fortran_order": False, "shape": (10**12,)}
    )
    size = stream.tell()
    stream.seek(0)
    with pytest.raises(ProjectFormatError) as caught:
        read_array_header(stream, size, ArchiveLimits(array_bytes=1))
    assert not isinstance(caught.value, ProjectResourceLimitError)


def test_legacy_manifest_above_old_32_mib_limit_opens_without_warning(
    window, archive, monkeypatch
):
    with zipfile.ZipFile(archive) as source:
        members = {info.filename: source.read(info) for info in source.infolist()}
    manifest = json.loads(members["manifest.json"])
    manifest["schema_version"] = 1
    manifest["project"]["fit_history"] = []
    members["manifest.json"] = json.dumps(manifest).encode().ljust(33 * 1024**2, b" ")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as destination:
        for name, content in members.items():
            destination.writestr(name, content)
    monkeypatch.setattr(
        "curvemole.gui.project_loading.QMessageBox.warning",
        lambda *args: pytest.fail("A 33 MiB legacy manifest should open normally"),
    )
    assert load_project_responsive(window, archive, load_project).curves


def test_declining_open_preserves_session_and_releases_new_lock(
    window, archive, monkeypatch
):
    from curvemole.core.serialization import ProjectLock
    from curvemole.gui.main_window import MainWindow

    main = MainWindow(Project("Current session"))
    original = main.project
    errors = []
    monkeypatch.setattr(main, "_show_error", lambda *args: errors.append(args))
    monkeypatch.setattr(
        "curvemole.core.serialization.ArchiveLimits",
        lambda: replace(ArchiveLimits(), manifest_bytes=1),
    )
    monkeypatch.setattr(
        "curvemole.gui.project_loading.QMessageBox.warning",
        lambda *args: QMessageBox.StandardButton.No,
    )
    try:
        main.open_project(archive)
        assert main.project is original
        assert main._project_lock is None
        assert not errors
        with ProjectLock(archive) as lock:
            assert lock.acquired
    finally:
        main.project.dirty = False
        main.close()
