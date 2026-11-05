from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QInputDialog

from curvemole import Curve, Project
from curvemole.gui.data_directories import (
    LIBRARY_FOLDERS,
    data_directory,
    default_library_directory,
    library_directory,
    prepare_library_directory,
)
from curvemole.gui.main_window import MainWindow


@pytest.fixture
def clean_settings(tmp_path):
    settings = QSettings(str(tmp_path / "folders.ini"), QSettings.Format.IniFormat)
    settings.setValue("data_directory", str(tmp_path / "curvemole_data"))
    return settings


def test_default_layout_is_lowercase_and_created_together_on_first_write(clean_settings):
    root = data_directory(clean_settings)
    assert not root.exists()
    assert library_directory(clean_settings, "functions") == root / "my_curvemole_functions"
    assert library_directory(clean_settings, "equations") == root / "my_curvemole_formulas"
    assert library_directory(clean_settings, "plugins") == root / "curvemole_plugins"
    assert not root.exists()
    prepare_library_directory(clean_settings, "equations")
    assert {path.name for path in root.iterdir()} == set(LIBRARY_FOLDERS.values())


def test_unconfigured_root_uses_documents_folder(clean_settings, monkeypatch, tmp_path):
    from curvemole.gui import data_directories
    clean_settings.remove("data_directory")
    monkeypatch.setattr(data_directories.QStandardPaths, "writableLocation", lambda kind: str(tmp_path))
    assert data_directory(clean_settings) == tmp_path / "curvemole_data"


@pytest.mark.parametrize("kind,key", [
    ("functions", "custom_function_directory"),
    ("equations", "custom_equation_directory"),
    ("plugins", "plugin_directory"),
])
def test_existing_configured_folders_are_preserved(clean_settings, tmp_path, kind, key):
    chosen = tmp_path / f"other-{kind}"
    chosen.mkdir()
    original = chosen / "existing.json"
    original.write_text('{"original": true}')
    clean_settings.setValue(key, str(chosen))
    assert library_directory(clean_settings, kind) == chosen
    assert prepare_library_directory(clean_settings, kind) == chosen
    assert original.read_text() == '{"original": true}'
    assert not data_directory(clean_settings).exists()


def test_community_and_plugin_manager_preferences_keep_their_precedence(clean_settings, tmp_path):
    clean_settings.setValue("plugin_directory", str(tmp_path / "manager"))
    clean_settings.setValue("community_plugins/folder", str(tmp_path / "community"))
    assert library_directory(clean_settings, "plugins") == tmp_path / "manager"
    assert library_directory(clean_settings, "plugins", community=True) == tmp_path / "community"


def test_default_function_library_is_available_without_an_initial_folder_prompt(tmp_path):
    from curvemole.gui.quick_function_library import _choose_library_directory
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    previous = window.settings.value("custom_function_directory")
    window.settings.remove("custom_function_directory")
    try:
        directory = _choose_library_directory(window)
        assert directory == tmp_path / "curvemole_data/my_curvemole_functions"
        assert directory.is_dir()
        assert default_library_directory(window.settings, "equations").is_dir()
        assert default_library_directory(window.settings, "plugins").is_dir()
    finally:
        if previous is not None:
            window.settings.setValue("custom_function_directory", previous)
        window.close()
        app.processEvents()


def test_save_formula_is_visible_without_expanding_load_and_asks_for_name(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    project = Project()
    curve = Curve("Example", [1., 2., 3.], [2., 4., 6.])
    project.add_curve(curve)
    window = MainWindow(project)
    panel = window.calculator
    panel.operation.setCurrentIndex(panel.operation.findData("column_formula"))
    panel.formula.setText("c2 / c1")
    assert panel.saved_formulas_toggle.text() == "Load formula"
    assert panel.save_formula_button.text() == "Save formula"
    assert not panel.saved_formulas_toggle.isChecked()
    assert panel.operation_form.isRowVisible(panel.formula_actions)
    assert not panel.operation_form.isRowVisible(panel.saved_formulas_body)
    panel.formula_actions.resize(260, 32)
    panel.formula_actions.layout().activate()
    assert panel.saved_formulas_toggle.geometry().right() < panel.save_formula_button.geometry().left()
    observed = []
    def name_dialog(*args, **kwargs):
        observed.append(kwargs.get("text"))
        return "Ratio", True
    monkeypatch.setattr(QInputDialog, "getText", name_dialog)
    panel.save_formula_button.click()
    assert observed == [""]
    assert project.custom_formulas[0]["name"] == "Ratio"
    assert list(window.calculator_equations.directory.glob("*.curvemole-equation.json"))
    panel.saved_formulas_toggle.click()
    assert panel.operation_form.isRowVisible(panel.saved_formulas_body)
    panel.saved_formula.setCurrentIndex(1)
    panel.save_formula_button.click()
    assert observed[-1] == "Ratio"
    assert len(project.custom_formulas) == 1
    project.dirty = False
    window.close()
    app.processEvents()


def test_cancelling_formula_name_does_not_save(monkeypatch):
    app = QApplication.instance() or QApplication([])
    project = Project()
    project.add_curve(Curve("Example", [1., 2.], [2., 3.]))
    window = MainWindow(project)
    panel = window.calculator
    panel.operation.setCurrentIndex(panel.operation.findData("column_formula"))
    panel.formula.setText("c2*2")
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Cancelled", False))
    panel.save_formula_button.click()
    assert not project.custom_formulas
    assert not window.calculator_equations.directory.exists()
    project.dirty = False
    window.close()
    app.processEvents()
