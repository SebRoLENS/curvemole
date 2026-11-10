from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from curvemole import Curve, Project, Series
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.dialogs import ImportMappingDialog


@pytest.fixture
def importing_window(tmp_path):
    app = QApplication.instance() or QApplication([])
    project = Project()
    project.add_series(Series('Existing acquisition', [Curve('Original', [0., 1.], [2., 3.])]))
    project.add_series(Series('Other acquisition'))
    window = CurveMoleMainWindow(project)
    paths = []
    for index in range(2):
        path = tmp_path / f'scan{index}.csv'
        path.write_text('x,y\n0,2\n1,3\n')
        paths.append(str(path))
    yield app, window, project, paths
    project.dirty = False
    window.close()
    window.deleteLater()
    app.processEvents()


def test_import_batch_into_existing_series_keeps_identity_notes_and_existing_spectra(importing_window, monkeypatch):
    _, window, project, paths = importing_window
    destination = project.dataset.series[0]
    original = destination.curves[0]
    project.notebook.set_description(project, 'series', destination.id, 'Acquisition note')
    seen = []
    def choose(dialog):
        seen.append(dialog.destination_series.count())
        dialog.destination_series.setCurrentIndex(dialog.destination_series.findData(destination.id))
        assert not dialog.series_name.isEnabled()
        dialog.apply_all.setChecked(True)
        dialog._accept()
        return dialog.result()
    monkeypatch.setattr(ImportMappingDialog, 'exec', choose)
    window.import_data(paths)
    assert seen == [3]
    assert project.dataset.series[0] is destination
    assert len(project.dataset.series) == 2
    assert destination.curves[0] is original
    assert len(destination.curves) == 3
    assert [curve.name for curve in destination.curves[1:]] == ['scan0', 'scan1']
    assert window.active_curve_id == destination.curves[1].id
    assert all(curve.id in project.models for curve in destination.curves)
    assert 'Acquisition note' in project.notebook.as_text(project)


def test_cancelling_later_mapping_leaves_existing_series_unmodified(importing_window, monkeypatch):
    _, window, project, paths = importing_window
    destination = project.dataset.series[0]
    before = list(destination.curves)
    count = 0
    def choose(dialog):
        nonlocal count
        count += 1
        if count == 2:
            assert dialog.destination_series.currentData() == destination.id
            assert not dialog.destination_series.isEnabled()
            return dialog.DialogCode.Rejected
        dialog.destination_series.setCurrentIndex(dialog.destination_series.findData(destination.id))
        dialog.apply_all.setChecked(False)
        return dialog.DialogCode.Accepted
    monkeypatch.setattr(ImportMappingDialog, 'exec', choose)
    window.import_data(paths)
    assert count == 2
    assert destination.curves == before
    assert len(project.dataset.series) == 2


def test_parse_failure_does_not_append_partial_import(importing_window, monkeypatch):
    _, window, project, paths = importing_window
    destination = project.dataset.series[0]
    errors = []
    def choose(dialog):
        dialog.destination_series.setCurrentIndex(dialog.destination_series.findData(destination.id))
        dialog.apply_all.setChecked(True)
        return dialog.DialogCode.Accepted
    monkeypatch.setattr(ImportMappingDialog, 'exec', choose)
    monkeypatch.setattr(window, '_show_error', lambda title, error: errors.append(str(error)))
    Path(paths[1]).write_text('invalid table')
    window.import_data(paths)
    assert errors
    assert len(destination.curves) == 1
    assert len(project.dataset.series) == 2


def test_new_series_option_is_retained(importing_window, monkeypatch):
    _, window, project, paths = importing_window
    def choose(dialog):
        assert dialog.destination_series.currentData() is None
        dialog.series_name.setText('New acquisition')
        dialog.apply_all.setChecked(True)
        dialog._accept()
        return dialog.result()
    monkeypatch.setattr(ImportMappingDialog, 'exec', choose)
    window.import_data(paths)
    assert len(project.dataset.series) == 3
    assert project.dataset.series[-1].name == 'New acquisition'
    assert len(project.dataset.series[-1].curves) == 2


@pytest.mark.parametrize("start_by_position", [False, True])
def test_batch_import_by_position_preserves_file_headers(importing_window, monkeypatch, start_by_position):
    _, window, project, paths = importing_window
    Path(paths[1]).write_text("raman_shift,intensita_nuova\n10,20\n11,21\n")
    third = Path(paths[1]).with_name("scan2.csv")
    third.write_text("y,x\n12,22\n13,23\n")
    paths.append(str(third))
    seen = []
    prompts = []

    def choose(dialog):
        seen.append(dialog.path)
        assert dialog.match_column_positions.isEnabled()
        assert not dialog.match_column_positions.isChecked()
        dialog.match_column_positions.setChecked(start_by_position)
        return dialog.DialogCode.Accepted

    def confirm(file_name, reason):
        prompts.append(file_name)
        assert "Column 'x'" in reason
        return "position"

    monkeypatch.setattr(ImportMappingDialog, "exec", choose)
    monkeypatch.setattr(window, "_ask_import_column_positions", confirm)
    window.import_data(paths)

    assert seen == [Path(paths[0])]
    assert prompts == ([] if start_by_position else [Path(paths[1]).name])
    first, second, last = project.dataset.series[-1].curves
    assert (first.x_label, first.y_label) == ("x", "y")
    assert (second.x_label, second.y_label) == ("raman_shift", "intensita_nuova")
    assert (last.x_label, last.y_label) == ("y", "x")
    assert list(last.original_x) == [12, 13]
    assert list(last.original_y) == [22, 23]
    assert list(second.original_x) == [10, 11]
    assert list(second.original_y) == [20, 21]


def test_batch_import_can_disable_mapping_when_headers_change(importing_window, monkeypatch):
    _, window, project, paths = importing_window
    Path(paths[1]).write_text("x,other_y,metadata\n0,20,99\n1,30,99\n")
    third = Path(paths[1]).with_name("scan2.csv")
    third.write_text("x,last_y\n0,22\n1,32\n")
    paths.append(str(third))
    seen = []

    def choose(dialog):
        seen.append(dialog.path)
        if len(seen) == 2:
            assert "check column mapping" in dialog.windowTitle()
        if len(seen) > 1:
            assert not dialog.apply_all.isChecked()
            assert not dialog.match_column_positions.isChecked()
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(ImportMappingDialog, "exec", choose)
    monkeypatch.setattr(window, "_ask_import_column_positions", lambda *args: "manual")
    window.import_data(paths)

    assert seen == [Path(path) for path in paths]
    assert [curve.y_label for curve in project.dataset.series[-1].curves] == ["y", "other_y", "last_y"]
