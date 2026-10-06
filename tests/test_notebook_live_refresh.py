from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QTreeWidgetItem

from curvemole import Component, Curve, Project, Series
from curvemole.core.notebook import description_key
from curvemole.core.serialization import load_project, save_project
from curvemole.gui.main_window import MainWindow
from curvemole.gui.notebook import DescriptionDialog


def _labels(item: QTreeWidgetItem) -> list[str]:
    values = [item.text(0)]
    for index in range(item.childCount()):
        values.extend(_labels(item.child(index)))
    return values


@pytest.mark.parametrize("dock_state", ["active", "background", "hidden"])
@pytest.mark.parametrize("read_only", [False, True])
def test_saved_notebook_tab_restores_contents_without_toggling(
    tmp_path, monkeypatch, dock_state, read_only,
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    project = Project("Saved notebook")
    series = Series("Experiment", [Curve("Data", [0., 1.], [1., 2.])])
    project.add_series(series)
    project.notebook.notes = "Saved experimental observations"
    project.notebook.set_description(project, "series", series.id, "Saved series details")
    path = save_project(project, tmp_path / "notebook.fitproj")

    window = MainWindow(project)
    window.show()
    window.open_notebook()
    if dock_state == "background":
        window.activate_tool_dock(window.model_dock)
    elif dock_state == "hidden":
        window.notebook_dock.hide()
    app.processEvents()
    window.close()
    app.processEvents()

    restored = load_project(path)
    restored.read_only = read_only
    revision = restored.revision
    other = MainWindow(restored)
    try:
        other.show()
        app.processEvents()
        assert other.notebook_dock.isHidden() == (dock_state == "hidden")
        if dock_state == "hidden":
            assert other._notebook_widget is None
            assert other.notebook_dock.widget() is other._notebook_placeholder
            # Also exercise the dock's own toggle action, without open_notebook().
            other.notebook_dock.toggleViewAction().trigger()
            app.processEvents()
        panel = other._notebook_widget
        assert panel is not None
        assert other.notebook_dock.widget() is panel
        assert panel.notes.toPlainText() == restored.notebook.notes
        assert panel.notes.isReadOnly() == read_only
        assert panel.tree.topLevelItemCount() == 1
        assert "Series description" in _labels(panel.tree.topLevelItem(0))
        if dock_state == "background":
            assert not other.model_dock.visibleRegion().isEmpty()
            assert other.notebook_dock.visibleRegion().isEmpty()
        assert not restored.dirty
        assert restored.revision == revision
    finally:
        other.project.dirty = False
        other.close()
        app.processEvents()


def test_open_project_updates_restored_notebook_and_new_project_clears_it(
    tmp_path, monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    project = Project("Loaded after startup")
    series = Series("Experiment", [Curve("Data", [0., 1.], [1., 2.])])
    project.add_series(series)
    project.notebook.notes = "Notes from the file"
    project.notebook.set_description(project, "series", series.id, "File description")
    path = save_project(project, tmp_path / "notebook.fitproj")
    window = MainWindow()
    try:
        window.show()
        window.open_notebook()
        old_panel = window._notebook_widget
        window.open_project(path)
        app.processEvents()
        panel = window._notebook_widget
        assert panel is not old_panel
        assert panel.project is window.project
        assert panel.notes.toPlainText() == "Notes from the file"
        assert panel.tree.topLevelItemCount() == 1
        assert not window.project.dirty
        window.new_project()
        app.processEvents()
        assert window._notebook_widget.project is window.project
        assert window._notebook_widget.notes.toPlainText() == ""
        assert window._notebook_widget.tree.topLevelItemCount() == 0
    finally:
        window.project.dirty = False
        window.close()
        app.processEvents()


def test_external_description_appears_immediately_in_open_notebook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Notebook refresh")
    series = Series("Experiment")
    series.add(Curve("Data 1", [0.0, 1.0], [1.0, 2.0]))
    project.add_series(series)
    project.dirty = False

    window = MainWindow(project)
    window.open_notebook()
    panel = window._notebook_widget
    assert panel is not None
    assert panel.tree.topLevelItemCount() == 0
    panel.tabs.setCurrentIndex(1)

    def accept_with_description(dialog: DescriptionDialog) -> QDialog.DialogCode:
        dialog.editor.setPlainText("Added while the notebook is already open")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(DescriptionDialog, "exec", accept_with_description)
    window.describe_series(series.id)

    assert window._notebook_widget is panel
    assert panel.tree.topLevelItemCount() == 1
    assert panel.current_key == description_key("series", series.id)
    assert panel.description.toPlainText() == "Added while the notebook is already open"
    labels: list[str] = []
    for index in range(panel.tree.topLevelItemCount()):
        labels.extend(_labels(panel.tree.topLevelItem(index)))
    assert "Series description" in labels
    assert "Added while the notebook is already open" in project.notebook.ordered_descriptions()[0].text

    project.dirty = False
    window.close()
    app.processEvents()


def test_clicking_described_objects_navigates_open_notebook() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Context navigation")
    series = Series("Experiment")
    curve = Curve("Data 1", [0.0, 1.0], [1.0, 2.0])
    series.add(curve)
    project.add_series(series)
    component = Component.create("constant")
    project.add_component(curve.id, component)
    project.notebook.set_description(project, "series", series.id, "Series details")
    project.notebook.set_description(project, "spectrum", curve.id, "Data details")
    project.notebook.set_description(
        project, "function", component.id, "Function details", curve.id
    )
    project.dirty = False

    window = MainWindow(project)
    window.open_notebook()
    panel = window._notebook_widget
    assert panel is not None
    panel.tabs.setCurrentIndex(1)

    series_item = window.curve_tree.topLevelItem(0)
    data_item = series_item.child(0)

    window.curve_tree.setCurrentItem(series_item)
    app.processEvents()
    assert panel.current_key == description_key("series", series.id)
    assert panel.description.toPlainText() == "Series details"

    window.curve_tree.setCurrentItem(data_item)
    app.processEvents()
    assert panel.current_key == description_key("spectrum", curve.id)
    assert panel.description.toPlainText() == "Data details"

    window.model_panel.componentSelected.emit(component.id)
    app.processEvents()
    assert panel.current_key == description_key("function", component.id, curve.id)
    assert panel.description.toPlainText() == "Function details"

    # Project notes remain under the user's control: object clicks do not switch or
    # drive description selection when the descriptions tab is not active.
    panel.tabs.setCurrentIndex(0)
    previous_key = panel.current_key
    window.curve_tree.setCurrentItem(series_item)
    app.processEvents()
    assert panel.tabs.currentIndex() == 0
    assert panel.current_key == previous_key

    project.dirty = False
    window.close()
    app.processEvents()
