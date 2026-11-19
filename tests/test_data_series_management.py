from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox

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


def test_context_menu_selected_palette_across_series(monkeypatch: pytest.MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Palette context menu")
    first_series = Series("First", [
        Curve("First A", [0., 1.], [1., 2.]),
        Curve("First B", [0., 1.], [2., 3.]),
    ])
    second_series = Series("Second", [
        Curve("Second A", [0., 1.], [3., 4.]),
        Curve("Second B", [0., 1.], [4., 5.]),
    ])
    project.add_series(first_series)
    project.add_series(second_series)
    window = MainWindow(project)
    window.show()
    tree = window.curve_tree
    tree.expandAll()
    app.processEvents()

    first_item = tree.topLevelItem(0).child(0)
    last_item = tree.topLevelItem(1).child(1)
    first_item.setSelected(True)
    last_item.setSelected(True)
    ids = [first_series.curves[0].id, second_series.curves[1].id]
    assert tree.ordered_selected_curve_ids() == ids
    before_other = (first_series.curves[1].colour, second_series.curves[0].colour)
    menus_seen = []

    def fake_exec(menu, *_args):
        palette_actions = [
            action for action in menu.actions()
            if action.menu() is not None and action.text() == "Selected spectra palette"
        ]
        assert len(palette_actions) == 1
        selected_palette = palette_actions[0].menu()
        assert selected_palette.isEnabled()
        menus_seen.append(selected_palette)
        next(action for action in selected_palette.actions() if action.text() == "Ocean").trigger()

    monkeypatch.setattr(QMenu, "exec", fake_exec)
    tree._show_context_menu(tree.visualItemRect(first_item).center())

    from curvemole.gui.colours import SERIES_PALETTES

    assert len(menus_seen) == 1
    assert [first_series.curves[0].colour, second_series.curves[1].colour] == list(
        SERIES_PALETTES["Ocean"][:2]
    )
    assert (first_series.curves[1].colour, second_series.curves[0].colour) == before_other
    assert window.undo_stack.count() == 1
    window.undo_stack.undo()
    assert all(curve.colour == "#0072B2" for curve in project.curves)
    project.dirty = False
    window.close()
    app.processEvents()


def test_context_menu_single_spectrum_has_no_palette_submenu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    project, _, _, first, _ = _project()
    window = MainWindow(project)
    window.show()
    tree = window.curve_tree
    tree.expandAll()
    app.processEvents()
    item = tree.topLevelItem(0).child(0)
    item.setSelected(True)

    def fake_exec(menu, *_args):
        assert not any(action.text() == "Selected spectra palette" for action in menu.actions())

    monkeypatch.setattr(QMenu, "exec", fake_exec)
    tree._show_context_menu(tree.visualItemRect(item).center())
    assert first.colour == "#0072B2"
    project.dirty = False
    window.close()
    app.processEvents()
