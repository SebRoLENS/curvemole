from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import QItemSelectionModel, QPoint
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog

from curvemole import Curve, Project
from curvemole.core.data import CurveState, Series
from curvemole.gui.main_window import MainWindow


def _project() -> tuple[Project, Series, Series, list[Curve]]:
    project = Project("series")
    first = Series("A")
    second = Series("B")
    curves = [
        Curve("a1", [0.0, 1.0], [0.0, 1.0]),
        Curve("a2", [0.0, 1.0], [1.0, 2.0]),
        Curve("a3", [0.0, 1.0], [2.0, 3.0]),
        Curve("b1", [0.0, 1.0], [3.0, 4.0]),
    ]
    for curve in curves[:3]:
        curve.state = CurveState.FITTED
        first.add(curve)
    curves[3].state = CurveState.FITTED
    second.add(curves[3])
    project.add_series(first)
    project.add_series(second)
    project.dirty = False
    return project, first, second, curves


def test_create_empty_series_is_undoable(monkeypatch: pytest.MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    project, _, _, _ = _project()
    window = MainWindow(project)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("New group", True))
    window.create_series()
    assert [series.name for series in project.dataset.series] == ["A", "B", "New group"]
    assert project.dataset.series[-1].curves == []
    window.undo_stack.undo()
    assert [series.name for series in project.dataset.series] == ["A", "B"]
    window.undo_stack.redo()
    assert [series.name for series in project.dataset.series] == ["A", "B", "New group"]
    project.dirty = False
    window.close()
    app.processEvents()


def test_move_spectra_between_series_preserves_models_states_and_undo() -> None:
    app = QApplication.instance() or QApplication([])
    project, first, second, curves = _project()
    model_ids = set(project.models)
    window = MainWindow(project)
    window.move_curves_to_series([curves[1].id, curves[2].id], second.id)
    assert [curve.name for curve in first.curves] == ["a1"]
    assert [curve.name for curve in second.curves] == ["b1", "a2", "a3"]
    assert set(project.models) == model_ids
    assert all(curve.state == CurveState.FITTED for curve in curves)
    window.undo_stack.undo()
    assert [curve.name for curve in first.curves] == ["a1", "a2", "a3"]
    assert [curve.name for curve in second.curves] == ["b1"]
    window.undo_stack.redo()
    assert [curve.name for curve in second.curves] == ["b1", "a2", "a3"]
    project.dirty = False
    window.close()
    app.processEvents()


def test_merge_series_appends_curves_and_is_undoable() -> None:
    app = QApplication.instance() or QApplication([])
    project, first, second, curves = _project()
    window = MainWindow(project)
    window.merge_series(first.id, second.id)
    assert [series.name for series in project.dataset.series] == ["B"]
    assert [curve.name for curve in project.dataset.series[0].curves] == ["b1", "a1", "a2", "a3"]
    assert all(curve.state == CurveState.FITTED for curve in curves)
    window.undo_stack.undo()
    assert [series.name for series in project.dataset.series] == ["A", "B"]
    assert [curve.name for curve in project.dataset.series[0].curves] == ["a1", "a2", "a3"]
    window.undo_stack.redo()
    assert [series.name for series in project.dataset.series] == ["B"]
    project.dirty = False
    window.close()
    app.processEvents()


def test_reorder_multiple_spectra_as_stable_group_and_undo() -> None:
    app = QApplication.instance() or QApplication([])
    project, first, _, curves = _project()
    window = MainWindow(project)
    window.reorder_curves([curves[1].id, curves[2].id], -1)
    assert [curve.name for curve in first.curves] == ["a2", "a3", "a1"]
    assert all(curve.state == CurveState.FITTED for curve in curves)
    window.undo_stack.undo()
    assert [curve.name for curve in first.curves] == ["a1", "a2", "a3"]
    window.reorder_curves([curves[0].id, curves[1].id], 1)
    assert [curve.name for curve in first.curves] == ["a3", "a1", "a2"]
    project.dirty = False
    window.close()
    app.processEvents()


def test_series_rename_from_tree_is_persisted() -> None:
    app = QApplication.instance() or QApplication([])
    project, first, _, _ = _project()
    window = MainWindow(project)
    window._rename_series(first.id, "Renamed")
    assert first.name == "Renamed"
    project.dirty = False
    window.close()
    app.processEvents()


def test_drag_series_and_spectra_uses_visible_insertions_and_supports_undo() -> None:
    app = QApplication.instance() or QApplication([])
    project, first, second, curves = _project()
    window = MainWindow(project)
    tree = window.curve_tree
    tree.resize(400, 360)
    first_item, second_item = tree.topLevelItem(0), tree.topLevelItem(1)
    source = tree.indexFromItem(first_item, 1)
    last_row = tree.visualItemRect(second_item.child(0))
    drop = tree._row_drop_at(source, last_row.center())
    assert drop is not None and drop.y == last_row.bottom() + 1
    tree._request_row_move(source, drop)
    assert project.dataset.series == [second, first]
    window.undo_stack.undo()
    assert project.dataset.series == [first, second]

    first_item, second_item = tree.topLevelItem(0), tree.topLevelItem(1)
    source = tree.indexFromItem(first_item.child(0), 1)
    target_row = tree.visualItemRect(first_item.child(2))
    drop = tree._row_drop_at(source, QPoint(target_row.center().x(), target_row.bottom()))
    assert drop is not None and drop.y == target_row.bottom() + 1
    tree._request_row_move(source, drop)
    assert first.curves == [curves[1], curves[2], curves[0]]

    first_item, second_item = tree.topLevelItem(0), tree.topLevelItem(1)
    second_item.setExpanded(False)
    source = tree.indexFromItem(first_item.child(2), 1)
    heading = tree.visualItemRect(second_item)
    drop = tree._row_drop_at(source, heading.center())
    assert drop is not None and drop.y == heading.bottom() + 1
    tree._request_row_move(source, drop)
    assert second.curves == [curves[0], curves[3]]
    assert tree.topLevelItem(1).isExpanded()
    assert curves[0].state == CurveState.FITTED
    window.undo_stack.undo()
    assert first.curves == [curves[1], curves[2], curves[0]]
    window.undo_stack.redo()
    assert second.curves == [curves[0], curves[3]]
    project.dirty = False
    window.close()
    app.processEvents()


def test_active_spectrum_marker_follows_selection_focus_and_scrolling() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project()
    for index in range(70):
        project.add_curve(Curve(f"Spectrum {index}", [0., 1.], [0., 1.]))
    window = MainWindow(project)
    window.resize(1050, 650)
    window.show()
    tree = window.curve_tree
    header = window.offscreen_active_spectrum
    QTest.qWait(30)
    series = tree.topLevelItem(0)
    first, second = series.child(0), series.child(1)
    try:
        assert not first.font(1).bold()
        first.setSelected(True)
        tree.setCurrentItem(second, 1, QItemSelectionModel.SelectionFlag.Select)
        QTest.qWait(30)
        assert window.active_curve_id == project.curves[1].id
        assert tree.selected_curve_ids() == {curve.id for curve in project.curves[:2]}
        assert second.font(1).bold() and not first.font(1).bold()
        assert tree.columnWidth(1) >= tree.sizeHintForIndex(tree.indexFromItem(second, 1)).width()
        assert header.isHidden()

        window.plot_workspace.graphics.setFocus()
        row = tree.visualItemRect(second)
        image = tree.viewport().grab().toImage()
        scale = image.devicePixelRatio()
        base = tree.palette().color(QPalette.ColorRole.Base)
        assert image.pixelColor(round(3 * scale), round(row.center().y() * scale)).name() == (
            "#ffd166" if base.lightness() < 128 else "#995000"
        )

        scrollbar = tree.verticalScrollBar()
        assert scrollbar.maximum() > 0
        scrollbar.setValue(scrollbar.maximum())
        QTest.qWait(30)
        assert header.isVisible() and "Spectrum 1" in header.text()
        scrollbar.setValue(0)
        QTest.qWait(30)
        assert header.isHidden()

        series.setExpanded(False)
        QTest.qWait(30)
        assert header.isVisible() and "Spectrum 1" in header.text()
        series.setExpanded(True)
        tree.setCurrentItem(first, 1, QItemSelectionModel.SelectionFlag.NoUpdate)
        QTest.qWait(30)
        assert first.font(1).bold() and not second.font(1).bold()
        assert header.isHidden()
        tree.clearSelection()
        QTest.qWait(30)
        assert not first.font(1).bold()
        assert header.isHidden()
    finally:
        project.dirty = False
        window.close()
        app.processEvents()
