from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from curvemole import Curve, Project
from curvemole.core.data import Series
from curvemole.gui.main_window import MainWindow


def _project() -> tuple[Project, Series, Series, Curve, Curve]:
    project = Project("data management")
    populated = Series("Loaded data")
    first = Curve("dataset 1", [0.0, 1.0], [1.0, 2.0])
    second = Curve("dataset 2", [0.0, 1.0], [2.0, 3.0])
    populated.add(first)
    populated.add(second)
    empty = Series("Empty")
    project.add_series(populated)
    project.add_series(empty)
    project.results[first.id] = {"fit": "first"}
    project.results[second.id] = {"fit": "second"}
    project.dirty = False
    return project, populated, empty, first, second


def test_explicit_data_rename_uses_generic_terminology(monkeypatch: pytest.MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    project, _, _, first, _ = _project()
    window = MainWindow(project)
    captured: dict[str, str] = {}

    def rename_dialog(_parent, title, label, **kwargs):
        captured["title"] = title
        captured["label"] = label
        captured["current"] = kwargs["text"]
        return "pressure point 10", True

    monkeypatch.setattr(QInputDialog, "getText", rename_dialog)
    window.rename_data(first.id)

    assert captured == {
        "title": "Rename data",
        "label": "Data name:",
        "current": "dataset 1",
    }
    assert first.name == "pressure point 10"

    project.dirty = False
    window.close()
    app.processEvents()


def test_empty_series_deletes_without_confirmation_and_is_undoable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    project, _, empty, _, _ = _project()
    window = MainWindow(project)

    def unexpected_question(*args, **kwargs):
        raise AssertionError("Empty series must not ask for confirmation")

    monkeypatch.setattr(QMessageBox, "question", unexpected_question)
    window.delete_series(empty.id)
    assert [series.name for series in project.dataset.series] == ["Loaded data"]

    window.undo_stack.undo()
    assert [series.name for series in project.dataset.series] == ["Loaded data", "Empty"]
    window.undo_stack.redo()
    assert [series.name for series in project.dataset.series] == ["Loaded data"]

    project.dirty = False
    window.close()
    app.processEvents()


def test_populated_series_warns_unloads_data_and_undo_restores_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    project, populated, _, first, second = _project()
    window = MainWindow(project)
    original_models = {curve_id: project.models[curve_id] for curve_id in (first.id, second.id)}
    original_results = {curve_id: project.results[curve_id] for curve_id in (first.id, second.id)}
    messages: list[str] = []

    def confirm(_parent, title, message, *args, **kwargs):
        assert title == "Delete series"
        messages.append(message)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    window.delete_series(populated.id)

    assert messages and "unload all data in this series" in messages[0]
    assert [series.name for series in project.dataset.series] == ["Empty"]
    assert first.id not in project.models and second.id not in project.models
    assert first.id not in project.results and second.id not in project.results

    window.undo_stack.undo()
    assert [series.name for series in project.dataset.series] == ["Loaded data", "Empty"]
    assert [curve.name for curve in project.dataset.series[0].curves] == ["dataset 1", "dataset 2"]
    assert project.models[first.id] is original_models[first.id]
    assert project.models[second.id] is original_models[second.id]
    assert project.results[first.id] is original_results[first.id]
    assert project.results[second.id] is original_results[second.id]

    project.dirty = False
    window.close()
    app.processEvents()


def test_populated_series_confirmation_can_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    project, populated, _, first, second = _project()
    window = MainWindow(project)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    window.delete_series(populated.id)

    assert [series.name for series in project.dataset.series] == ["Loaded data", "Empty"]
    assert first.id in project.models and second.id in project.models
    assert window.undo_stack.count() == 0

    project.dirty = False
    window.close()
    app.processEvents()
