from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QDialog, QTreeWidgetItem

from curvemole import Component, Curve, Project, Series
from curvemole.core.notebook import description_key
from curvemole.gui.main_window import MainWindow
from curvemole.gui.notebook import DescriptionDialog


def _labels(item: QTreeWidgetItem) -> list[str]:
    values = [item.text(0)]
    for index in range(item.childCount()):
        values.extend(_labels(item.child(index)))
    return values


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
