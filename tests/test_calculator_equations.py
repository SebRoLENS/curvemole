"""Calculator-library, unified-column and searchable-picker regressions."""
from __future__ import annotations

import json

import numpy as np
import pytest
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QListView

from curvemole.core.calculator import apply_column_formula, apply_scalar
from curvemole.core.calculator_equations import (
    EQUATION_SUFFIX,
    load_equations,
    normalize_equation,
    save_equation,
)
from curvemole.core.data import Curve
from curvemole.core.errors import CurveMoleError
from curvemole.core.project import Project
from curvemole.core.serialization import load_project, save_project
from curvemole.gui.calculator_columns import choose_column
from curvemole.gui.main_window import MainWindow
from curvemole.gui.panels import CalculatorPanel


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def equation(**changes):
    return {"name": "Monitor normalisation", "formula": "c2 / c3**2",
            "mode": "column_formula", "target": "c2", **changes}


def curve_with_columns(count=3):
    columns = {f"c{i}": np.arange(1., 4.) * i for i in range(1, count + 1)}
    return Curve("Columns", columns["c1"], columns["c2"], original_columns=columns,
                 column_axes={"x": "c1", "y": "c2"},
                 column_labels={key: f"Measurement {i}" for i, key in enumerate(columns, 1)})


def project_with_curve(count=3):
    project = Project()
    curve = curve_with_columns(count)
    project.add_curve(curve)
    return project, curve


def test_portable_equation_roundtrip_and_same_name_replacement(tmp_path):
    directory = tmp_path / "my_curvemole_equations"
    path = save_equation(directory, equation(name="../Monitor / μ"))
    assert path.parent == directory
    assert path.name.endswith(EQUATION_SUFFIX)
    save_equation(directory, equation(name="../Monitor / μ", formula="c2/c3"))
    values, failures = load_equations(directory)
    assert not failures and len(values) == 1
    assert values[0]["formula"] == "c2/c3"
    assert json.loads(path.read_text())["schema_version"] == 1


@pytest.mark.parametrize("value,target,source", [
    ({"name": "Old X", "axis": "x", "formula": "X = 1240/x"}, "x", "1240/x"),
    ({"name": "Old Y", "axis": "y", "formula": "y**2", "mode": "custom_formula"}, "y", "y**2"),
    (equation(formula="c2 = c2/c3"), "c2", "c2/c3"),
])
def test_legacy_modes_and_assignments_normalize(value, target, source):
    normalized = normalize_equation(value)
    assert normalized["target"] == target
    assert normalized["formula"] == source
    assert normalized["mode"] == "column_formula"


@pytest.mark.parametrize("changes", [
    {"formula": "__import__('os')"}, {"formula": "c2[0]"},
    {"formula": "unknown + c2"}, {"target": "../escape"},
    {"formula": "c3 = c2"}, {"formula": ""}, {"name": ""},
])
def test_invalid_equations_never_create_files(tmp_path, changes):
    with pytest.raises(CurveMoleError):
        save_equation(tmp_path, equation(**changes))
    assert not list(tmp_path.iterdir())


def test_one_damaged_library_file_does_not_hide_valid_equations(tmp_path):
    save_equation(tmp_path, equation())
    (tmp_path / f"bad{EQUATION_SUFFIX}").write_text('{"not": "an equation"}')
    (tmp_path / f"unsafe{EQUATION_SUFFIX}").write_text(json.dumps({
        "format": "CurveMole calculator equation", "schema_version": 1,
        "equation": equation(formula="__import__('os')")}))
    values, failures = load_equations(tmp_path)
    assert len(values) == 1 and len(failures) == 2


def test_failed_atomic_replace_preserves_previous_equation(tmp_path, monkeypatch):
    import curvemole.core.calculator_equations as module
    path = save_equation(tmp_path, equation())
    previous = path.read_bytes()
    def fail_replace(*args):
        raise OSError("disk write failed")
    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(OSError):
        save_equation(tmp_path, equation(formula="c2/c3"))
    assert path.read_bytes() == previous
    assert not list(tmp_path.glob("*.tmp"))


def test_unified_mode_and_unique_destinations_follow_current_mapping(app):
    project, curve = project_with_curve(4)
    curve.column_axes = {"x": "c3", "y": "c1"}
    curve._recompute()
    panel = CalculatorPanel()
    panel.set_curves(project, curve.id)
    assert panel.operation.itemText(panel.operation.findData("column_formula")) == "Custom formulas"
    assert panel.operation.findData("custom_formula") == -1
    assert [panel.column_target.itemText(i) for i in range(4)] == [
        "c1 (Y)", "c2", "c3 (X)", "c4"]
    assert panel.column_target.currentData() == "c1"
    panel.deleteLater()


def test_axis_only_curves_have_replayable_column_codes_and_preserve_errors(tmp_path):
    curve = Curve("Legacy", np.arange(1., 4.), np.arange(4., 7.), sigma_y=np.ones(3))
    apply_scalar(curve, "y_multiply", 2)
    apply_column_formula(curve, "c2", "c2 * 3")
    np.testing.assert_allclose(curve.y, [24, 30, 36])
    np.testing.assert_allclose(curve.columns["c2"], curve.y)
    np.testing.assert_allclose(curve.current_sigma_y, 6)
    project = Project()
    project.add_curve(curve)
    loaded = load_project(save_project(project, tmp_path / "legacy.fitproj")).curves[0]
    np.testing.assert_allclose(loaded.y, curve.y)
    loaded.undo_transformation()
    np.testing.assert_allclose(loaded.y, [8, 10, 12])
    assert not loaded.original_columns


def test_legacy_formula_load_maps_axis_to_physical_column(app):
    project, curve = project_with_curve()
    project.custom_formulas = [{"name": "Legacy Y", "axis": "y", "formula": "Y = y*3"}]
    panel = CalculatorPanel()
    panel.set_curves(project, curve.id)
    panel.saved_formula.setCurrentIndex(1)
    assert panel.column_target.currentData() == "c2"
    assert panel.formula.text() == "y*3"
    panel.deleteLater()


def test_unavailable_saved_destination_stays_unselected(app):
    project, curve = project_with_curve()
    project.custom_formulas = [equation(target="c99")]
    panel = CalculatorPanel()
    panel.set_curves(project, curve.id)
    panel.saved_formula.setCurrentIndex(1)
    assert panel.column_target.currentIndex() == -1
    panel.set_curves(project, curve.id)
    assert panel.column_target.currentIndex() == -1
    panel.deleteLater()


def test_save_reuse_across_projects_and_project_precedence(app, tmp_path):
    project, _curve = project_with_curve()
    window = MainWindow(project)
    window.save_custom_formula(equation())
    directory = window.calculator_equations.directory
    assert list(directory.glob(f"*{EQUATION_SUFFIX}"))
    assert project.custom_formulas[0]["formula"] == "c2 / c3**2"
    loaded = load_project(save_project(project, tmp_path / "equation.fitproj"))
    assert loaded.custom_formulas == project.custom_formulas
    fresh, fresh_curve = project_with_curve()
    window.project, window.active_curve_id = fresh, fresh_curve.id
    window.refresh_all()
    panel = window.calculator
    assert panel.saved_formula.count() == 2
    assert "library" in panel.saved_formula.itemText(1)
    panel.saved_formula.setCurrentIndex(1)
    panel._apply()
    np.testing.assert_allclose(fresh_curve.y, fresh_curve.original_y / fresh_curve.columns["c3"]**2)
    window.undo_stack.undo()
    np.testing.assert_allclose(fresh_curve.y, fresh_curve.original_y)
    fresh.custom_formulas = [equation(formula="c2/c3")]
    window.refresh_all()
    assert panel.saved_formula.count() == 2
    assert "project" in panel.saved_formula.itemText(1)
    panel.saved_formula.setCurrentIndex(1)
    assert panel.formula.text() == "c2/c3"
    fresh.dirty = False
    window.close()
    app.processEvents()


def test_save_failure_does_not_mark_equation_as_saved(app, monkeypatch):
    project, _curve = project_with_curve()
    window = MainWindow(project)
    before = list(project.custom_formulas)
    errors = []
    def fail_save(value):
        raise OSError("read-only library")
    monkeypatch.setattr(window.calculator_equations, "save", fail_save)
    monkeypatch.setattr(window, "_show_error", lambda title, exc: errors.append(str(exc)))
    window.save_custom_formula(equation())
    assert errors and project.custom_formulas == before
    project.dirty = False
    window.close()
    app.processEvents()


def test_default_equation_folder_uses_data_root_independently_of_function_override(app, tmp_path):
    window = MainWindow()
    settings = QSettings("CurveMole", "CurveMole")
    settings.remove("custom_equation_directory")
    previous = settings.value("custom_function_directory")
    settings.setValue("custom_function_directory", str(tmp_path / "my_curvemole_functions"))
    assert window.calculator_equations.directory == tmp_path / "curvemole_data/my_curvemole_formulas"
    if previous is None:
        settings.remove("custom_function_directory")
    else:
        settings.setValue("custom_function_directory", previous)
    window.close()
    app.processEvents()


@pytest.mark.parametrize("picker", ["destination", "insert"])
def test_searchable_picker_handles_thousand_columns_and_inserts_at_cursor(app, picker):
    project, curve = project_with_curve(1000)
    panel = CalculatorPanel()
    panel.set_curves(project, curve.id)
    panel.operation.setCurrentIndex(panel.operation.findData("column_formula"))
    panel.show()
    panel.formula.setText("c2 / ()")
    panel.formula.setCursorPosition(6)
    failures = []
    def interact():
        popup = QApplication.activeModalWidget()
        try:
            assert isinstance(popup, QDialog)
            search, view = popup.findChild(QLineEdit), popup.findChild(QListView)
            search.setText("Measurement 987")
            assert view.model().rowCount() == 1
            assert "c987" in view.model().index(0, 0).data()
            QTest.keyClick(search, Qt.Key.Key_Return)
        except Exception as exc:
            failures.append(exc)
            popup.reject()
    QTimer.singleShot(0, interact)
    if picker == "destination":
        panel.column_target.showPopup()
        assert panel.column_target.currentData() == "c987"
        assert panel.formula.text() == "c2 / ()"
    else:
        panel.column_insert.click()
        assert panel.formula.text() == "c2 / (c987)"
        assert panel.column_target.currentData() == "c2"
    assert not failures
    panel.close()
    panel.deleteLater()
    app.processEvents()


def test_popup_cancel_and_no_match_leave_destination_unchanged(app):
    project, curve = project_with_curve()
    panel = CalculatorPanel()
    panel.set_curves(project, curve.id)
    failures = []
    def interact():
        popup = QApplication.activeModalWidget()
        try:
            search, view = popup.findChild(QLineEdit), popup.findChild(QListView)
            search.setText("absent column")
            assert view.model().rowCount() == 0
            QTest.keyClick(search, Qt.Key.Key_Escape)
        except Exception as exc:
            failures.append(exc)
            popup.reject()
    QTimer.singleShot(0, interact)
    assert choose_column(panel.column_target, panel.column_target.model()) is None
    assert panel.column_target.currentData() == "c2"
    assert not failures
    panel.deleteLater()
