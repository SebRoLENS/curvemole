from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.gui.main_window import MainWindow
from curvemole.gui.parameter_copy import CopyParameterDialog, copy_parameter_to_refs


def _window_with_two_curves() -> tuple[QApplication, MainWindow, Curve, Curve, Component, Component, Component]:
    app = QApplication.instance() or QApplication([])
    project = Project("parameter-copy")
    x = np.linspace(-5.0, 5.0, 101)
    first = Curve("first", x, np.exp(-x**2))
    second = Curve("second", x, np.exp(-(x - 1.0) ** 2))
    project.add_curve(first)
    project.add_curve(second)

    source = Component.create("gaussian")
    anchor = Component.create("gaussian")
    target = Component.create("gaussian")
    project.model_for(first.id).add(source)
    project.model_for(first.id).add(anchor)
    project.model_for(second.id).add(target)
    project.dirty = False
    window = MainWindow(project)
    return app, window, first, second, source, anchor, target


def _select_parameter_row(window: MainWindow, parameter_name: str) -> None:
    table = window.model_panel.parameters
    for row in range(table.rowCount()):
        value_item = table.item(row, 1)
        metadata = value_item.data(Qt.ItemDataRole.UserRole) if value_item is not None else None
        if metadata and metadata[1] == parameter_name:
            table.setCurrentCell(row, 0)
            QApplication.processEvents()
            return
    raise AssertionError(f"Parameter row not found: {parameter_name}")


def _target_item(dialog: CopyParameterDialog, ref: tuple[str, str]):
    for row in range(dialog.targets.count()):
        item = dialog.targets.item(row)
        value = item.data(Qt.ItemDataRole.UserRole)
        if value is not None and (str(value[0]), str(value[1])) == ref:
            return item
    raise AssertionError(f"Target not found: {ref}")


def test_value_only_copy_preserves_target_constraints_and_is_undoable() -> None:
    app, window, first, second, source, _anchor, target = _window_with_two_curves()
    source_parameter = window.project.model_for(first.id).component(source.id).parameters["center"]
    target_parameter = window.project.model_for(second.id).component(target.id).parameters["center"]
    source_parameter.value = 1.25
    target_parameter.value = -0.25
    target_parameter.minimum = -2.0
    target_parameter.maximum = 2.0
    target_parameter.fixed = True

    result = copy_parameter_to_refs(
        window,
        (first.id, source.id),
        [(second.id, target.id)],
        "center",
    )

    copied = window.project.model_for(second.id).component(target.id).parameters["center"]
    assert result.copied == 1
    assert copied.value == pytest.approx(1.25)
    assert copied.minimum == pytest.approx(-2.0)
    assert copied.maximum == pytest.approx(2.0)
    assert copied.fixed is True

    window.undo_stack.undo()
    restored = window.project.model_for(second.id).component(target.id).parameters["center"]
    assert restored.value == pytest.approx(-0.25)
    window.undo_stack.redo()
    redone = window.project.model_for(second.id).component(target.id).parameters["center"]
    assert redone.value == pytest.approx(1.25)

    window.project.dirty = False
    window.close()
    app.processEvents()


def test_copy_can_include_fixed_bounds_and_relation_across_spectra() -> None:
    app, window, first, second, source, anchor, target = _window_with_two_curves()
    source_parameter = window.project.model_for(first.id).component(source.id).parameters["center"]
    anchor_parameter = window.project.model_for(first.id).component(anchor.id).parameters["center"]
    target_parameter = window.project.model_for(second.id).component(target.id).parameters["center"]

    anchor_parameter.value = 1.0
    source_parameter.value = 1.25
    source_parameter.minimum = 0.5
    source_parameter.maximum = 2.0
    source_parameter.fixed = True
    source_parameter.link = f"${{{first.id}.{anchor.id}.center}}"
    source_parameter.validate()

    target_parameter.value = -1.0
    target_parameter.minimum = -10.0
    target_parameter.maximum = 10.0
    target_parameter.fixed = False
    target_parameter.link = None

    result = copy_parameter_to_refs(
        window,
        (first.id, source.id),
        [(second.id, target.id)],
        "center",
        copy_fixed=True,
        copy_bounds=True,
        copy_link=True,
    )

    copied = window.project.model_for(second.id).component(target.id).parameters["center"]
    assert result.copied == 1
    assert copied.value == pytest.approx(1.25)
    assert copied.minimum == pytest.approx(0.5)
    assert copied.maximum == pytest.approx(2.0)
    assert copied.fixed is True
    assert copied.link == source_parameter.link

    window.project.dirty = False
    window.close()
    app.processEvents()


def test_targets_without_parameter_or_with_incompatible_bounds_are_skipped() -> None:
    app, window, first, second, source, _anchor, target = _window_with_two_curves()
    source_parameter = window.project.model_for(first.id).component(source.id).parameters["center"]
    source_parameter.value = 3.0

    target_parameter = window.project.model_for(second.id).component(target.id).parameters["center"]
    target_parameter.minimum = -1.0
    target_parameter.maximum = 1.0
    target_parameter.value = 0.0

    linear = Component.create("linear")
    window.project.model_for(second.id).add(linear)

    result = copy_parameter_to_refs(
        window,
        (first.id, source.id),
        [(second.id, target.id), (second.id, linear.id)],
        "center",
    )

    assert result.copied == 0
    assert result.incompatible_bounds == [(second.id, target.id)]
    assert result.missing_parameter == [(second.id, linear.id)]
    unchanged = window.project.model_for(second.id).component(target.id).parameters["center"]
    assert unchanged.value == pytest.approx(0.0)

    window.project.dirty = False
    window.close()
    app.processEvents()


def test_single_source_enables_copy_and_dialog_lists_project_targets() -> None:
    app, window, first, second, source, anchor, target = _window_with_two_curves()
    panel = window.model_panel

    assert panel.selected_component_refs() == [(first.id, source.id)]
    assert panel.copy_parameter_button.isEnabled()
    assert source.name in panel.copy_parameter_button.text()

    _select_parameter_row(window, "center")
    assert panel._parameter_copy_source_ref == (first.id, source.id)
    assert panel._parameter_copy_parameter_name == "center"
    assert "center" in panel.copy_parameter_button.text()

    source_parameter = window.project.model_for(first.id).component(source.id).parameters["center"]
    source_parameter.value = 1.2345
    dialog = CopyParameterDialog(
        window,
        (first.id, source.id),
        current_parameter="center",
    )
    assert dialog.source_ref() == (first.id, source.id)
    assert dialog.parameter_name() == "center"
    assert dialog.targets.count() == 2
    assert dialog.target_refs() == []
    assert "center" in dialog.source_summary.text()
    assert source.name in dialog.source_summary.text()
    assert "1.2345" in dialog.source_summary.text()

    anchor_item = _target_item(dialog, (first.id, anchor.id))
    target_item = _target_item(dialog, (second.id, target.id))
    anchor_item.setCheckState(Qt.CheckState.Checked)
    target_item.setCheckState(Qt.CheckState.Checked)
    app.processEvents()
    assert dialog.target_refs() == [(first.id, anchor.id), (second.id, target.id)]
    assert dialog.copy_button.isEnabled()
    assert "2" in dialog.copy_button.text()
    dialog.close()

    window.project.dirty = False
    window.close()
    app.processEvents()


def test_copy_button_requires_exactly_one_source_function() -> None:
    app, window, first, _second, _source, anchor, _target = _window_with_two_curves()
    panel = window.model_panel

    assert panel.copy_parameter_button.isEnabled()

    panel.components.clearSelection()
    app.processEvents()
    assert not panel.copy_parameter_button.isEnabled()
    assert panel.copy_parameter_button.text() == "First select a function"

    panel.components.item(0).setSelected(True)
    panel.components.item(1).setSelected(True)
    app.processEvents()
    assert panel.selected_component_refs()[1] == (first.id, anchor.id)
    assert not panel.copy_parameter_button.isEnabled()
    assert panel.copy_parameter_button.text() == "Select a single source function"

    window.project.dirty = False
    window.close()
    app.processEvents()
