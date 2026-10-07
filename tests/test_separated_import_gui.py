from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from curvemole import Project
from curvemole.core.importers import import_file
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.dialogs import ImportMappingDialog


@pytest.fixture
def dialog_factory(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialogs = []
    def create(header, row):
        path = tmp_path / f"file{len(dialogs)}.csv"
        path.write_text(header + "\n" + row + "\n" + row + "\n")
        dialog = ImportMappingDialog(path)
        dialogs.append(dialog)
        return dialog
    yield create
    for dialog in dialogs:
        dialog.close()
    app.processEvents()


def select(combo, value):
    combo.setCurrentIndex(combo.findData(value))


def test_normal_import_remains_single_and_multi_controls_hidden(dialog_factory):
    simple = dialog_factory("x,y", "0,1")
    assert simple.separated_files.isHidden()
    assert simple.spectra_editor.isHidden()
    assert simple.select_all_y_button.isHidden()
    dialog = dialog_factory("x,y,z", "0,1,2")
    assert not dialog.separated_files.isHidden()
    assert not dialog.separated_files.isChecked()
    assert dialog.spectra_editor.isHidden()
    dialog.y_columns.item(2).setCheckState(Qt.CheckState.Checked)
    assert dialog.mapping().y == ["z"]
    curve = import_file(dialog.path, dialog.mapping())[0]
    assert len(curve.original_columns) == 3
    assert curve.name == dialog.path.stem


def test_shared_x_independent_errors_adjacency_and_conflicts(dialog_factory):
    dialog = dialog_factory("x,A,eA,B,pB,mB", "0,10,1,20,3,2")
    dialog.separated_files.setChecked(True)
    dialog.y_columns.item(3).setCheckState(Qt.CheckState.Checked)
    table = dialog.spectra_editor.table
    select(table.cellWidget(0, 2), "sigma_y")
    assert table.cellWidget(0, 3).currentData() == 2
    select(table.cellWidget(1, 2), "asymmetric")
    assert table.cellWidget(1, 3).currentData() == 4
    assert table.cellWidget(1, 4).currentData() == 5
    table.cellWidget(1, 5).setValue(90)
    mapping = dialog.mapping()
    curves = import_file(dialog.path, mapping)
    assert [c.name for c in curves] == ["A", "B"]
    np.testing.assert_array_equal(curves[0].sigma_y, [1, 1])
    np.testing.assert_array_equal(curves[1].error_y_minus, [2, 2])
    assert curves[1].error_confidence_level == .9
    dialog.spectrum_preview.refresh()
    assert dialog.spectrum_preview.label.text().startswith("Spectrum preview — file")
    assert len(dialog.spectrum_preview.graph.listDataItems()) >= 2
    select(table.cellWidget(0, 3), 3)
    with pytest.raises(ValueError, match="already assigned"):
        dialog.mapping()
    assert "already assigned" in dialog.spectra_editor.status.text()
    dialog.separated_files.setChecked(False)
    assert dialog.mapping().y == ["A"]


def test_patterns_are_explicit_and_can_be_edited_or_customized(dialog_factory):
    dialog = dialog_factory("x1,y1,x2,y2,x3,y3", "0,10,5,20,8,30")
    dialog.separated_files.setChecked(True)
    editor = dialog.spectra_editor
    assert editor.structure.currentData() == "shared"
    assert len(dialog.mapping().spectra) == 1  # Labels do not select a pattern.
    select(editor.structure, "repeated")
    assert [(s.x, s.y) for s in dialog.mapping().spectra] == [(0, [1]), (2, [3]), (4, [5])]
    dialog.spectrum_preview.refresh()
    assert len(dialog.spectrum_preview.graph.listDataItems()) == 3
    editor.y_per_x.setValue(2)
    editor.apply_pattern.click()
    assert [(s.x, s.y) for s in dialog.mapping().spectra] == [(0, [1]), (0, [2]), (3, [4]), (3, [5])]
    select(editor.structure, "custom")
    editor.table.selectRow(3)
    editor.remove_button.click()
    assert editor.table.rowCount() == 3
    select(editor.table.cellWidget(2, 0), 5)
    curves = import_file(dialog.path, dialog.mapping())
    assert curves[2].x_label == "y3"
    editor.add_button.click()
    assert editor.table.rowCount() == 4


def test_repeated_error_patterns_and_unused_trailing_columns(dialog_factory):
    dialog = dialog_factory("x,A,p,m,x2,B,p2,m2,orphanX", "0,10,3,2,1,20,5,4,9")
    dialog.separated_files.setChecked(True)
    editor = dialog.spectra_editor
    select(editor.structure, "repeated")
    select(editor.pattern_error, "asymmetric")
    editor.apply_pattern.click()
    mapping = dialog.mapping()
    assert [(s.x, s.y[0], s.error_y_plus, s.error_y_minus) for s in mapping.spectra] == [
        (0, 1, 2, 3), (4, 5, 6, 7)]
    assert "excluded): 9" in editor.status.text()
    curves = import_file(dialog.path, mapping)
    np.testing.assert_array_equal(curves[1].error_y_plus, [5, 5])


def test_default_errors_for_normal_import_and_missing_error_columns(dialog_factory):
    dialog = dialog_factory("x,y,plus,minus", "0,10,3,2")
    dialog.uncertainty_kind.setCurrentIndex(1)
    assert dialog.uncertainty_column.currentData() == "plus"
    dialog.asymmetric_error.setChecked(True)
    assert dialog.error_plus_column.currentData() == "plus"
    assert dialog.error_minus_column.currentData() == "minus"
    dialog.y_columns.item(3).setCheckState(Qt.CheckState.Checked)
    assert dialog.error_plus_column.currentData() is None
    assert dialog.error_minus_column.currentData() is None
    dialog.separated_files.setChecked(True)
    select(dialog.spectra_editor.table.cellWidget(0, 2), "sigma_y")
    with pytest.raises(ValueError, match="Select an error"):
        dialog.mapping()


def test_reparse_to_two_columns_restores_simple_mode(dialog_factory):
    dialog = dialog_factory("x,y,z", "0,10,20")
    dialog.separated_files.setChecked(True)
    dialog.path.write_text("x,y\n0,10\n1,20\n")
    dialog._reload()
    assert dialog.separated_files.isHidden()
    assert not dialog.separated_files.isChecked()
    assert dialog.spectra_editor.isHidden()
    assert not dialog.mapping().spectra


def test_batch_import_keeps_actual_y_names_and_per_spectrum_errors(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    paths = []
    for name in ("A", "B"):
        path = tmp_path / f"{name}.csv"
        path.write_text(f"x,{name},error\n0,10,1\n1,11,2\n")
        paths.append(str(path))
    window = CurveMoleMainWindow(Project())
    monkeypatch.setattr(window, "_show_error", lambda title, exc: pytest.fail(f"{title}: {exc}"))
    accepted = []
    def accept(dialog):
        accepted.append(dialog)
        dialog.separated_files.setChecked(True)
        select(dialog.spectra_editor.table.cellWidget(0, 2), "sigma_y")
        dialog.apply_all.setChecked(True)
        dialog._accept()
        return dialog.result()
    monkeypatch.setattr(ImportMappingDialog, "exec", accept)
    try:
        window.import_data(paths)
        assert len(accepted) == 1
        assert [curve.name for curve in window.project.curves] == ["A", "B"]
        for curve in window.project.curves:
            np.testing.assert_array_equal(curve.sigma_y, [1, 2])
    finally:
        window.project.dirty = False
        window.close()
        app.processEvents()


def test_header_changes_preserve_positional_spectra_and_errors(dialog_factory):
    dialog = dialog_factory("x,A,p,m,B,e", "0,10,3,2,20,1")
    dialog.separated_files.setChecked(True)
    dialog.y_columns.item(4).setCheckState(Qt.CheckState.Checked)
    table = dialog.spectra_editor.table
    select(table.cellWidget(0, 2), "asymmetric")
    table.cellWidget(0, 5).setValue(90)
    select(table.cellWidget(1, 2), "sigma_y")
    dialog.header.setChecked(False)
    mapping = dialog.mapping()
    assert [(s.x, s.y[0], s.error_y_plus, s.error_y_minus, s.sigma_y) for s in mapping.spectra] == [
        (0, 1, 2, 3, None), (0, 4, None, None, 5)]
    assert mapping.spectra[0].error_confidence_level == .9
    curves = import_file(dialog.path, mapping, dialog.config())
    assert [c.name for c in curves] == ["Y — column 2", "Y — column 5"]


def test_normal_error_axes_conflict_and_missing_column(dialog_factory):
    dialog = dialog_factory("x,y,z", "0,10,20")
    dialog.x_column.setCurrentIndex(2)
    dialog.uncertainty_kind.setCurrentIndex(1)
    assert dialog.uncertainty_column.currentData() == "z"
    with pytest.raises(ValueError, match="already assigned"):
        dialog.mapping()
    dialog.y_columns.item(2).setCheckState(Qt.CheckState.Checked)
    with pytest.raises(ValueError, match="Select the error"):
        dialog.mapping()
