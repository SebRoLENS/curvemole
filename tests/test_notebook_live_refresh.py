from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QDialog, QTreeWidgetItem

from curvemole import Curve, Project, Series
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

    def accept_with_description(dialog: DescriptionDialog) -> QDialog.DialogCode:
        dialog.editor.setPlainText("Added while the notebook is already open")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(DescriptionDialog, "exec", accept_with_description)
    window.describe_series(series.id)

    assert window._notebook_widget is panel
    assert panel.tree.topLevelItemCount() == 1
    labels: list[str] = []
    for index in range(panel.tree.topLevelItemCount()):
        labels.extend(_labels(panel.tree.topLevelItem(index)))
    assert "Series description" in labels
    assert "Added while the notebook is already open" in project.notebook.ordered_descriptions()[0].text

    project.dirty = False
    window.close()
    app.processEvents()
