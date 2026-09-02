from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QMessageBox

from curvemole import Component, Curve, Project
from curvemole.gui.main_window import MainWindow


def _project_with_functions() -> tuple[Project, Curve, Curve]:
    project = Project("function-selection")
    x = np.linspace(-5.0, 5.0, 101)
    first = Curve("Spectrum A", x, np.exp(-x**2))
    second = Curve("Spectrum B", x, np.exp(-(x - 1.0) ** 2))
    project.add_curve(first)
    project.add_curve(second)
    for curve in (first, second):
        project.model_for(curve.id).add(Component.create("gaussian"))
        project.model_for(curve.id).add(Component.create("lorentzian"))
    project.dirty = False
    return project, first, second


def _select_rows(window: MainWindow, rows: list[int]) -> None:
    panel = window.model_panel
    panel.components.clearSelection()
    for row in rows:
        panel.components.item(row).setSelected(True)
    QApplication.processEvents()


def test_local_function_list_supports_multi_selection_and_batch_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    project, first, _ = _project_with_functions()
    window = MainWindow(project)
    panel = window.model_panel

    assert panel.show_all_functions.isChecked() is False
    assert panel.components.count() == 2
    _select_rows(window, [0, 1])
    assert len(panel.selected_component_refs()) == 2

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    panel._delete()
    assert project.model_for(first.id).components == []

    window.undo_stack.undo()
    assert len(project.model_for(first.id).components) == 2

    project.dirty = False
    window.close()
    app.processEvents()


def test_show_all_functions_identifies_spectrum_and_supports_cross_spectrum_selection() -> None:
    app = QApplication.instance() or QApplication([])
    project, first, second = _project_with_functions()
    window = MainWindow(project)
    panel = window.model_panel

    panel.show_all_functions.setChecked(True)
    app.processEvents()

    assert panel.components.count() == 4
    labels = [panel.components.item(row).text() for row in range(panel.components.count())]
    assert any("Spectrum A  ›" in label for label in labels)
    assert any("Spectrum B  ›" in label for label in labels)

    _select_rows(window, [0, 2])
    refs = panel.selected_component_refs()
    assert len(refs) == 2
    assert {curve_id for curve_id, _ in refs} == {first.id, second.id}

    panel._bulk_fixed(True)
    for curve_id, component_id in refs:
        component = project.model_for(curve_id).component(component_id)
        assert all(parameter.fixed for parameter in component.parameters.values())

    window.undo_stack.undo()
    for curve_id, component_id in refs:
        component = project.model_for(curve_id).component(component_id)
        assert not any(parameter.fixed for parameter in component.parameters.values())

    project.dirty = False
    window.close()
    app.processEvents()


def test_cross_spectrum_batch_delete_is_single_undoable_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    project, first, second = _project_with_functions()
    window = MainWindow(project)
    panel = window.model_panel
    panel.show_all_functions.setChecked(True)
    app.processEvents()

    _select_rows(window, [0, 2])
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    panel._delete()

    assert len(project.model_for(first.id).components) == 1
    assert len(project.model_for(second.id).components) == 1

    window.undo_stack.undo()
    assert len(project.model_for(first.id).components) == 2
    assert len(project.model_for(second.id).components) == 2

    window.undo_stack.redo()
    assert len(project.model_for(first.id).components) == 1
    assert len(project.model_for(second.id).components) == 1

    project.dirty = False
    window.close()
    app.processEvents()
