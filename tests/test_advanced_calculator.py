import copy

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from curvemole.core.calculator import apply_column_formula, apply_scalar
from curvemole.core.data import Curve, CurveState, Series
from curvemole.core.errors import CurveMoleError
from curvemole.core.importers import ColumnMapping, ImportConfig, import_file
from curvemole.core.project import Project
from curvemole.core.serialization import load_project, save_project


def spectrum(tmp_path):
    path = tmp_path / "three.csv"
    path.write_text("Energy,Counts,Monitor counts\n1,8,2\n2,18,3\n3,32,4\n")
    return import_file(path, ColumnMapping(x=0, y=[1]), ImportConfig(delimiter=",", header=True))[0]


def test_columns_replay_and_archive_without_source(tmp_path):
    curve = spectrum(tmp_path)
    apply_scalar(curve, "y_multiply", 2)
    apply_column_formula(curve, "y", "y / c3^2")
    np.testing.assert_allclose(curve.y, 4)
    np.testing.assert_allclose(curve.columns["c2"], curve.y)
    apply_column_formula(curve, "c3", "${Monitor counts} + 1")
    np.testing.assert_allclose(curve.columns["c3"], [3, 4, 5])
    curve.undo_transformation()
    project = Project()
    project.dataset.series.append(Series("Data", [curve]))
    path = save_project(project, tmp_path / "columns.fitproj")
    (tmp_path / "three.csv").unlink()
    loaded = load_project(path).curves[0]
    np.testing.assert_allclose(loaded.y, 4)
    loaded.redo_transformation()
    np.testing.assert_allclose(loaded.columns["c3"], [3, 4, 5])
    loaded.restore_original()
    np.testing.assert_allclose(loaded.y, [8, 18, 32])
    np.testing.assert_allclose(loaded.columns["c3"], [2, 3, 4])
    assert loaded.column_labels["c3"] == "Monitor counts"


@pytest.mark.parametrize("formula", ["y/c9", "y/0", "__import__('os')", "c3[0]", "${missing}"])
def test_invalid_formula_does_not_change_history(tmp_path, formula):
    curve = spectrum(tmp_path)
    apply_scalar(curve, "y_add", 1)
    curve.undo_transformation()
    with pytest.raises(CurveMoleError):
        apply_column_formula(curve, "y", formula)
    assert not curve.transformations
    assert len(curve.redo_transformations) == 1
    np.testing.assert_allclose(curve.y, curve.original_y)


def test_batch_atomic_and_single_undo(tmp_path, monkeypatch):
    from curvemole.gui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    first = spectrum(tmp_path)
    second = Curve("Old project", first.x, first.y)
    first.state = CurveState.FITTED
    window.project.dataset.series = [Series("Data", [first, second])]
    window.active_curve_id = first.id
    monkeypatch.setattr(window, "_calculator_targets", lambda scope: [first, second])
    errors = []
    monkeypatch.setattr(window, "_show_error", lambda title, error: errors.append(str(error)))
    window.apply_calculator({"operation": "column_formula", "column_target": "y", "formula": "y/c3"})
    assert errors and "Old project" in errors[0]
    assert not first.transformations
    assert first.state == CurveState.FITTED
    second.original_columns = copy.deepcopy(first.original_columns)
    second.column_axes = dict(first.column_axes)
    second._recompute()
    window.apply_calculator({"operation": "column_formula", "column_target": "y", "formula": "y/c3"})
    np.testing.assert_allclose(first.y, [4, 6, 8])
    np.testing.assert_allclose(second.y, first.y)
    window.undo_stack.undo()
    np.testing.assert_allclose(first.y, first.original_y)
    assert first.state == CurveState.FITTED
    window.undo_stack.redo()
    np.testing.assert_allclose(second.y, [4, 6, 8])
    window.project.dirty = False
    window.hide()
    window.deleteLater()
    app.processEvents()


def test_picker_and_saved_advanced_formula(tmp_path):
    from curvemole.gui.panels import CalculatorPanel
    from curvemole.gui.series_groups import SpectrumSelectionDialog
    app = QApplication.instance() or QApplication([])
    curve = spectrum(tmp_path)
    other = Curve("Other", curve.x, curve.y)
    project = Project()
    project.dataset.series = [Series("First", [curve]), Series("Second", [other])]
    picker = SpectrumSelectionDialog(project, curve.id)
    picker._check_shown(True)
    assert picker.selected_ids() == [curve.id]
    picker.all_series.setChecked(True)
    picker._check_shown(True)
    assert set(picker.selected_ids()) == {curve.id, other.id}
    picker.active_series.setChecked(True)
    assert picker.selected_ids() == [curve.id]
    assert not picker.targets.item(0).flags() & Qt.ItemFlag.ItemIsUserCheckable
    panel = CalculatorPanel()
    project.custom_formulas = [{"name": "Monitor", "formula": "y/c3**2", "mode": "column_formula", "target": "y"}]
    panel.set_curves(project, curve.id)
    panel.saved_formula.setCurrentIndex(1)
    assert panel.operation.currentData() == "column_formula"
    assert panel.column_target.currentData() == "y"
    assert panel.operation.itemData(0, Qt.ItemDataRole.ForegroundRole).isValid()
    assert panel.column_target.findData("c3") >= 0
    picker.deleteLater()
    panel.deleteLater()
    app.processEvents()


def test_unplotted_destination_then_axis_formula_and_mask_alignment(tmp_path):
    curve = spectrum(tmp_path)
    curve.masks[curve.active_mask].excluded[1] = True
    apply_column_formula(curve, "c3", "c3 = where(c3 >= 3, c3*2, c3)")
    np.testing.assert_allclose(curve.y, [8, 18, 32])
    apply_column_formula(curve, "c1", "c1 * 10")
    np.testing.assert_allclose(curve.x, [10, 20, 30])
    apply_column_formula(curve, "y", "c2 / c3")
    np.testing.assert_allclose(curve.y, [4, 3, 4])
    assert curve.masks[curve.active_mask].excluded.tolist() == [False, True, False]


def test_save_advanced_formula_and_insert_dropdown(tmp_path, monkeypatch):
    from curvemole.gui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    curve = spectrum(tmp_path)
    window.project.add_curve(curve)
    window.active_curve_id = curve.id
    window.refresh_all()
    errors = []
    monkeypatch.setattr(window, "_show_error", lambda title, error: errors.append(str(error)))
    window.save_custom_formula({"name": "Conditional", "axis": "y", "mode": "column_formula",
                                "target": "c3", "formula": "where(c3 >= 3, c3^2, c3)"})
    assert not errors
    panel = window.calculator
    panel.saved_formula.setCurrentIndex(1)
    assert panel.column_target.currentData() == "c3"
    panel.formula.setText("y / ")
    panel.formula.setCursorPosition(4)
    panel.column_input.setCurrentIndex(panel.column_input.findData("c3"))
    panel.column_input.activated.emit(panel.column_input.currentIndex())
    assert panel.formula.text() == "y / "
    panel.column_insert.click()
    assert panel.formula.text() == "y / c3"
    assert panel.formula_summary.text() == "c3 — Monitor counts ← y / c3"
    saved = load_project(save_project(window.project, tmp_path / "saved.fitproj"))
    assert saved.custom_formulas[0]["target"] == "c3"
    assert saved.custom_formulas[0]["mode"] == "column_formula"
    window.hide()
    window.deleteLater()
    app.processEvents()
