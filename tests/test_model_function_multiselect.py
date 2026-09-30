from __future__ import annotations

import sys

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
    from PySide6.QtCore import Qt

    functions = [panel.components.item(i) for i in range(panel.components.count())
                 if panel.components.item(i).data(Qt.ItemDataRole.UserRole)]
    for row in rows:
        functions[row].setSelected(True)
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

    assert panel.components.count() == 7
    labels = [panel.components.item(row).text() for row in range(panel.components.count())]
    assert any("Spectrum A" in label for label in labels)
    assert any("Spectrum B" in label for label in labels)

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


@pytest.mark.parametrize("target_count", [0, 1, 3, 5])
@pytest.mark.parametrize("navigation", ["plot", "tree"])
def test_spectrum_navigation_preserves_function_position(target_count, navigation):
    app = QApplication.instance() or QApplication([])
    project = Project("function-position")
    curves = [Curve(name, np.arange(5.0), np.ones(5)) for name in ("first", "second")]
    for curve, count in zip(curves, (4, target_count), strict=True):
        project.add_curve(curve)
        for index in range(count):
            component = Component.create("constant", initial={"offset": float(index + 10)})
            component.name = f"Function {count - index}"
            project.model_for(curve.id).add(component)
    window = MainWindow(project)
    panel = window.model_panel
    panel.components.setCurrentRow(3)
    assert panel.selected_component_id() == project.model_for(curves[0].id).components[3].id

    if navigation == "plot":
        window._set_active_curve(curves[1].id)
    else:
        window.curve_tree.setCurrentItem(window.curve_tree.topLevelItem(0).child(1))
    expected = min(3, target_count - 1)
    if target_count:
        component = project.model_for(curves[1].id).components[expected]
        assert panel.components.currentRow() == expected
        assert panel.selected_component_id() == component.id
        assert window.selected_component_id == component.id
        assert float(panel.parameters.item(0, 1).text()) == component.parameters["offset"].value
        window.refresh_all()
        assert panel.selected_component_id() == component.id
        window._set_active_curve(curves[0].id)
        assert panel.components.currentRow() == expected
    else:
        assert panel.components.count() == 0
        assert panel.parameters.rowCount() == 0
        assert window.selected_component_id is None
    project.dirty = False
    window.close()
    app.processEvents()


@pytest.mark.parametrize("show_all", [False, True])
def test_bulk_selection_buttons_preserve_model_state_and_exclude_backgrounds(show_all):
    app = QApplication.instance() or QApplication([])
    project, first, second = _project_with_functions()
    backgrounds = set()
    for curve in (first, second):
        components = project.model_for(curve.id).components
        components[0].is_background = True
        components[1].enabled = False
        backgrounds.add((curve.id, components[0].id))
    expected_curves = (first, second) if show_all else (first,)
    expected = {
        (curve.id, component.id)
        for curve in expected_curves
        for component in project.model_for(curve.id).components
    }
    window = MainWindow(project)
    panel = window.model_panel
    panel.show_all_functions.setChecked(show_all)
    initial_models = {
        curve.id: project.model_for(curve.id).to_dict()
        for curve in (first, second)
    }

    panel.select_all_functions_button.click()
    assert set(panel.selected_component_refs()) == expected
    assert len(panel.components.selectedItems()) == len(expected)

    panel.select_non_background_functions_button.click()
    assert set(panel.selected_component_refs()) == expected - backgrounds
    assert len(panel.components.selectedItems()) == len(expected - backgrounds)
    for curve in (first, second):
        assert project.model_for(curve.id).to_dict() == initial_models[curve.id]
    assert window.undo_stack.count() == 0

    project.dirty = False
    window.close()
    app.processEvents()


def test_excluding_backgrounds_selects_single_function_on_another_spectrum_without_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("background-selection")
    first = Curve("Background only", [0.0, 1.0, 2.0], [1.0, 1.0, 1.0])
    second = Curve("Peak only", [0.0, 1.0, 2.0], [0.0, 1.0, 0.0])
    for curve in (first, second):
        project.add_curve(curve)
    background = Component.create("constant")
    background.is_background = True
    peak = Component.create("gaussian")
    project.model_for(first.id).add(background)
    project.model_for(second.id).add(peak)
    window = MainWindow(project)
    panel = window.model_panel
    panel.show_all_functions.setChecked(True)
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))

    panel.select_non_background_functions_button.click()
    app.processEvents()

    assert errors == []
    assert panel.selected_component_refs() == [(second.id, peak.id)]
    assert panel.selected_component_curve_id() == second.id
    assert panel.selected_component_id() == peak.id
    assert window.selected_component_id == peak.id
    assert panel.parameters.rowCount() == len(peak.parameters)

    project.dirty = False
    window.close()
    app.processEvents()


def test_local_bulk_selection_navigation_preserves_selected_non_background_position():
    app = QApplication.instance() or QApplication([])
    project, first, second = _project_with_functions()
    for curve in (first, second):
        project.model_for(curve.id).components[0].is_background = True
    window = MainWindow(project)
    panel = window.model_panel

    panel.select_all_functions_button.click()
    panel.select_non_background_functions_button.click()
    assert panel.selected_component_refs() == [
        (first.id, project.model_for(first.id).components[1].id)
    ]
    window._set_active_curve(second.id)
    assert panel.selected_component_refs() == [
        (second.id, project.model_for(second.id).components[1].id)
    ]
    assert panel.components.currentRow() == 1

    project.dirty = False
    window.close()
    app.processEvents()
