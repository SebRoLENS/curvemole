from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox

from curvemole import Curve, Project
from curvemole.core.data import Series, Transformation
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


def _invoke_data_action(monkeypatch, tree, clicked, label):
    class NonBlockingMenu(QMenu):
        def exec(self, *_args):
            next(action for action in self.actions() if action.text() == label).trigger()

    monkeypatch.setattr("curvemole.gui.data_series_management.QMenu", NonBlockingMenu)
    tree._show_context_menu(tree.visualItemRect(clicked).center())


def test_remove_selected_series_confirms_once_and_restores_the_group(monkeypatch):
    app = QApplication.instance() or QApplication([])
    project, loaded, empty, first, _ = _project()
    unaffected = Series("Unaffected")
    project.add_series(unaffected)
    window = MainWindow(project)
    window.show()
    app.processEvents()
    tree = window.curve_tree
    for row, modifier in ((0, Qt.KeyboardModifier.NoModifier), (1, Qt.KeyboardModifier.ControlModifier)):
        index = tree.indexFromItem(tree.topLevelItem(row), 1)
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, modifier, tree.visualRect(index).center())
    assert set(tree.selected_series_ids()) == {loaded.id, empty.id}
    confirmations = []
    answers = iter((QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes))

    def confirm(_window, _title, message, _buttons, default):
        confirmations.append(message)
        assert default == QMessageBox.StandardButton.No
        return next(answers)

    monkeypatch.setattr(QMessageBox, "question", confirm)
    try:
        window.remove_curves_button.click()
        assert project.dataset.series == [loaded, empty, unaffected]
        assert window.undo_stack.count() == 0
        window.remove_curves_button.click()
        assert project.dataset.series == [unaffected]
        assert len(confirmations) == 2
        assert "2 selected series" in confirmations[-1]
        assert window.undo_stack.count() == 1
        window.undo_stack.undo()
        assert project.dataset.series == [loaded, empty, unaffected]
        assert project.results[first.id] == {"fit": "first"}
        assert first.id in project.models
        window.undo_stack.redo()
        assert project.dataset.series == [unaffected]
    finally:
        project.dirty = False
        window.close()
        app.processEvents()


@pytest.mark.parametrize("create", [False, True])
def test_move_dialog_moves_selection_across_series_in_one_undo(monkeypatch, create):
    from curvemole.gui.data_series_management import MoveToSeriesDialog

    app = QApplication.instance() or QApplication([])
    project, loaded, empty, first, second = _project()
    third = Curve("outside", [0., 1.], [3., 4.])
    project.add_curve(third, empty)
    destination = Series("Destination")
    project.add_series(destination)
    window = MainWindow(project)
    window.show()
    tree = window.curve_tree
    first_item = tree.topLevelItem(0).child(0)
    first_item.setSelected(True)
    tree.topLevelItem(1).child(0).setSelected(True)
    app.processEvents()
    seen = []

    def accept():
        dialog = app.activeModalWidget()
        if not isinstance(dialog, MoveToSeriesDialog):
            if dialog is not None:
                dialog.reject()
            return
        seen.append(True)
        if create:
            dialog.name.setText("New destination")
        else:
            dialog.destination.setCurrentIndex(dialog.destination.findData(destination.id))
        dialog.accept()

    try:
        QTimer.singleShot(0, accept)
        _invoke_data_action(monkeypatch, tree, first_item, "Move to series…")
        assert seen == [True]
        moved = project.dataset.series[-1]
        assert moved.name == ("New destination" if create else destination.name)
        assert moved.curves == [first, third]
        assert loaded.curves == [second] and not empty.curves
        assert project.results[first.id] == {"fit": "first"}
        assert window.undo_stack.count() == 1
        window.undo_stack.undo()
        assert project.dataset.series == [loaded, empty, destination]
        assert loaded.curves == [first, second] and empty.curves == [third]
        window.undo_stack.redo()
        assert project.dataset.series[-1].curves == [first, third]
    finally:
        project.dirty = False
        window.close()
        app.processEvents()


def test_curve_duplicate_has_independent_raw_or_processed_data():
    original = Curve("source", [0., 1., 2.], [2., 3., 4.], sigma_y=[1., 1., 1.])
    original.mask_point(1.)
    transform = Transformation("y_multiply", {"value": 3.})
    original.apply_transformation(transform)
    original.delete_points([0])

    raw = original.duplicate("raw", raw=True)
    processed = original.duplicate("processed")
    np.testing.assert_array_equal(raw.x, original.original_x)
    np.testing.assert_array_equal(raw.y, original.original_y)
    np.testing.assert_array_equal(processed.y, original.y)
    np.testing.assert_array_equal(processed.current_sigma_y, original.current_sigma_y)
    np.testing.assert_array_equal(processed.effective_mask, original.effective_mask)
    assert not raw.effective_mask.any()
    assert not raw.transformations
    assert original.id != raw.id != processed.id
    assert not np.shares_memory(processed.original_y, original.original_y)
    assert processed.transformations[0] is not transform
    processed.restore_original()
    assert len(processed) == 3 and len(original) == 2


@pytest.mark.parametrize("copy_series", [False, True])
def test_duplicate_selected_data_and_series_are_inserted_next_to_sources(monkeypatch, copy_series):
    app = QApplication.instance() or QApplication([])
    project, series, other, first, second = _project()
    third = Curve("third", [0., 1.], [4., 5.])
    project.add_curve(third, other)
    window = MainWindow(project)
    window.show()
    tree = window.curve_tree
    source_node = tree.topLevelItem(0)
    if copy_series:
        clicked = source_node
        action = "Duplicate series…"
    else:
        clicked = source_node.child(0)
        tree.topLevelItem(1).child(0).setSelected(True)
        action = "Duplicate data…"
    clicked.setSelected(True)
    project.dataset.curve(first.id).apply_transformation(Transformation("y_add", {"value": 4.}))
    app.processEvents()
    monkeypatch.setattr(QInputDialog, "getItem", lambda *_args: ("Processed data with applied operations", True))

    try:
        _invoke_data_action(monkeypatch, tree, clicked, action)
        if copy_series:
            copied_series = project.dataset.series[1]
            assert project.dataset.series == [series, copied_series, other]
            assert copied_series.name == "Loaded data (copy)"
            duplicate = copied_series.curves[0]
        else:
            duplicate = series.curves[1]
            assert series.curves == [first, duplicate, second]
            assert other.curves[1].name == "third (copy)"
        np.testing.assert_array_equal(duplicate.y, first.y)
        assert duplicate.id != first.id
        assert not project.model_for(duplicate.id).components
        assert duplicate.id not in project.results
        assert window.undo_stack.count() == 1
        window.undo_stack.undo()
        assert project.dataset.series == [series, other]
        assert series.curves == [first, second] and other.curves == [third]
        window.undo_stack.redo()
        assert project.dataset.curve(duplicate.id) is duplicate
    finally:
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

    class NonBlockingMenu(QMenu):
        def exec(self, *_args):
            return fake_exec(self, *_args)

    # Patch the factory: Qt can bypass a class-level exec monkeypatch on macOS.
    monkeypatch.setattr("curvemole.gui.data_series_management.QMenu", NonBlockingMenu)
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

    class NonBlockingMenu(QMenu):
        def exec(self, *_args):
            return fake_exec(self, *_args)

    # Patch the factory: Qt can bypass a class-level exec monkeypatch on macOS.
    monkeypatch.setattr("curvemole.gui.data_series_management.QMenu", NonBlockingMenu)
    tree._show_context_menu(tree.visualItemRect(item).center())
    assert first.colour == "#0072B2"
    project.dirty = False
    window.close()
    app.processEvents()
