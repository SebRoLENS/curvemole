from __future__ import annotations

import struct
import time

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from curvemole import Project
from curvemole.core.errors import DataValidationError
from curvemole.core.folder_import import FolderScan
from curvemole.core.importers import ColumnMapping, import_file, inspect_file
from curvemole.core.spe import read_spe_frame
from curvemole.gui.app import CurveMoleMainWindow


def spe_bytes(*, nx=100, frames=1):
    header = bytearray(4100)
    for offset, fmt, value in [
        (42, "H", nx),
        (656, "H", 1),
        (1446, "i", frames),
        (108, "h", 3),
        (1992, "f", 2.2),
        (2996, "I", 0x01234567),
        (3098, "B", 1),
        (3100, "B", 4),
        (3101, "B", 2),
        (1510, "H", 1),
    ]:
        struct.pack_into("<" + fmt, header, offset, value)
    struct.pack_into("<3H", header, 1512, 1, nx, 1)
    struct.pack_into("<6d", header, 3263, 690.0, 0.01, 1e-6, 0.0, 0.0, 0.0)
    return bytes(header) + np.arange(nx * frames, dtype="<u2").tobytes()


def test_spe_calibration_and_multiframe(tmp_path):
    path = tmp_path / "ruby.0"
    path.write_bytes(spe_bytes(frames=2))
    frame = read_spe_frame(path)
    x = np.arange(1, 101)
    np.testing.assert_allclose(frame.iloc[:, 0], 690.0 + 0.01 * x + 1e-6 * x * x)
    assert frame.shape == (100, 3)
    assert frame.iloc[0, 2] == 100
    assert inspect_file(path).columns[0] == "Wavelength [nm]"
    curves = import_file(path, ColumnMapping(x=0, y=[1, 2]))
    assert len(curves) == 2
    assert "[nm]" in curves[0].x_label


@pytest.mark.parametrize(
    "mutate", ["partial", "uncalibrated", "wrong_unit", "version3", "short_binary"]
)
def test_spe_rejects_incomplete_or_ambiguous_axis(tmp_path, mutate):
    blob = bytearray(spe_bytes())
    if mutate == "partial":
        blob = blob[:-20]
    elif mutate == "uncalibrated":
        blob[3098] = 0
    elif mutate == "wrong_unit":
        blob[3100] = 1
    elif mutate == "version3":
        struct.pack_into("<f", blob, 1992, 3.0)
    else:
        blob = blob[:1000]
    path = tmp_path / "ruby.spe"
    path.write_bytes(blob)
    with pytest.raises(DataValidationError):
        import_file(path, ColumnMapping(x=0, y=[1]))


def test_scan_filter_stability_existing_modified_and_retry(tmp_path):
    old = tmp_path / "ruby_old.txt"
    old.write_text("old")
    scan = FolderScan(tmp_path, "ruby", modified=True)
    assert not scan.ready(0)
    ruby = tmp_path / "RUBY.0"
    ruby.write_text("1")
    (tmp_path / "sample.txt").write_text("x")
    (tmp_path / "ruby.tmp").write_text("x")
    assert not scan.ready(0)
    ruby.write_text("12")
    assert not scan.ready(3)
    ready = scan.ready(6)
    assert [v[0] for v in ready] == [ruby]
    scan.consumed[ruby] = ready[0][1]
    assert not scan.ready(7)
    ruby.write_text("123")
    assert not scan.ready(8)
    ready = scan.ready(11)
    assert ready
    scan.failed[ruby] = ready[0][1]
    assert not scan.ready(12)
    scan.failed.clear()
    assert scan.ready(13)


def wait_until(app, predicate, timeout=5):
    until = time.monotonic() + timeout
    while not predicate() and time.monotonic() < until:
        app.processEvents()
        time.sleep(0.01)
    assert predicate()


def test_automatic_mode_off_by_default_imports_once_and_undo(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = CurveMoleMainWindow(Project())
    controller = window.folder_import
    assert controller.scan is None and not controller.timer.isActive()
    assert any(
        controller.action in action.menu().actions()
        for action in window.menuBar().actions()
        if action.menu()
    )
    controller.start(tmp_path, "ruby", settle=0.1)
    path = tmp_path / "ruby_0.txt"
    path.write_text("690 1\n691 3\n692 1\n")
    (tmp_path / "other.txt").write_text(path.read_text())
    wait_until(app, lambda: len(window.project.curves) == 1)
    curve = window.project.curves[0]
    assert window.active_curve_id == curve.id
    assert set(window.plot_workspace._data_items) == {curve.id}
    controller.tick()
    controller.tick()
    assert len(window.project.curves) == 1
    window.undo_stack.undo()
    assert not window.project.curves
    window.undo_stack.redo()
    assert len(window.project.curves) == 1
    controller.stop()
    assert controller.scan is None
    window.project.dirty = False
    window.close()


def test_project_change_stops_session(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = CurveMoleMainWindow(Project())
    window.folder_import.start(tmp_path)
    window.project = Project()
    window.folder_import.tick()
    assert window.folder_import.scan is None
    window.close()
    app.processEvents()


def test_completed_job_is_discarded_after_stop(tmp_path):
    from concurrent.futures import Future

    app = QApplication.instance() or QApplication([])
    window = CurveMoleMainWindow(Project())
    controller = window.folder_import
    controller.start(tmp_path)
    controller.future = Future()
    controller.pending = tmp_path / "ruby.txt", (1, 1), controller.generation, None
    controller.future.set_result((Project(), "digest", "unused"))
    controller.stop()
    controller.tick()
    assert not window.project.curves and controller.future is None
    window.close()
    app.processEvents()
