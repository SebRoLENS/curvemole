from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

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
