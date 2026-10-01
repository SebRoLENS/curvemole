from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QMessageBox

from curvemole import Component, Curve, Project, Series
from curvemole.core.expressions import SafeExpression
from curvemole.core.models import component_height
from curvemole.core.registry import default_registry
from curvemole.core.reorder import reorder_component_names
from curvemole.gui.dialogs import ParameterLinkDialog
from curvemole.gui.main_window import MainWindow


@pytest.fixture
def gui(monkeypatch):
    app = QApplication.instance() or QApplication([])
    widgets = []

    def unexpected_warning(*args):
        pytest.fail(f"Unexpected parameter-link warning: {args[-1]}")

    monkeypatch.setattr(QMessageBox, "warning", unexpected_warning)
    monkeypatch.setattr(MainWindow, "_show_error", unexpected_warning)

    def create(widget_type, *args, **kwargs):
        widget = widget_type(*args, **kwargs)
        widgets.append(widget)
        return widget

    yield create
    for widget in reversed(widgets):
        if isinstance(widget, MainWindow):
            widget.project.dirty = False
        widget.close()
    app.processEvents()


def _project():
    project = Project()
    curves = [Curve(name, [0., 1., 2.], [0., 1., 0.])
              for name in ("Spectrum 20", "Spectrum 2", "Reference")]
    project.add_series(Series("Pressure scan", curves[:2]))
    project.add_series(Series("Calibration", curves[2:]))
    for index, curve in enumerate(curves):
        for number in range(1, 6):
            project.model_for(curve.id).add(Component.create(
                "gaussian", name=f"Gaussian{number}", initial={"center": index * 10 + number}))
    return project, curves


def _reference(curve, component, parameter="center"):
    return f"${{{curve.id}.{component.id}.{parameter}}}"


def _choose(dialog, component, *, curve=None, parameter="center"):
    if curve is not None:
        dialog.source_curve.setCurrentIndex(dialog.source_curve.findData(curve.id))
    dialog.source_component.setCurrentIndex(dialog.source_component.findData(component.id))
    dialog.source_parameter.setCurrentIndex(dialog.source_parameter.findData(parameter))


def _advanced(dialog):
    dialog.mode.setCurrentIndex(dialog.mode.findData("advanced"))


def _apply(window, dialog, curve, component):
    dialog._accept()
    window.apply_parameter_link(
        curve.id, component.id, "center", dialog.selected_link(), dialog.selected_link_scope(),
        reference_scopes=dialog.selected_reference_scopes(), relation=dialog.selected_relation(),
        tolerance=dialog.selected_tolerance(), tolerance_mode=dialog.selected_tolerance_mode(),
    )


def test_add_builds_readable_mean_with_canonical_parameter_identities(gui):
    project, (curve, _, _) = _project()
    target, second, third, *_ = project.model_for(curve.id).components
    dialog = gui(ParameterLinkDialog, project, curve.id, target.id, "center")
    _advanced(dialog)
    dialog.advanced.insertPlainText("(")
    _choose(dialog, second)
    dialog.add_parameter.click()
    dialog.advanced.insertPlainText(" + ")
    _choose(dialog, third)
    dialog.add_parameter.click()
    dialog.advanced.insertPlainText(") / 2")

    assert dialog.advanced.text() == "(${Gaussian2.center} + ${Gaussian3.center}) / 2"
    expected = f"({_reference(curve, second)} + {_reference(curve, third)}) / 2"
    assert dialog.link_expression() == expected
    assert curve.id not in dialog.advanced.text()
    assert dialog.preview.text() == "Gaussian1.center = (Gaussian2.center + Gaussian3.center) / 2"
    dialog._accept()
    assert dialog.selected_link() == expected
    assert dialog.selected_reference_scopes() == ["relative", "relative"]
    assert SafeExpression.compile(dialog.selected_link()).evaluate(
        references=project.resolved_parameter_values()) == 2.5


def test_add_builds_complex_rational_expression_with_repeated_references(gui):
    project, (curve, _, _) = _project()
    target, second, _, _, fifth = project.model_for(curve.id).components
    dialog = gui(ParameterLinkDialog, project, curve.id, target.id, "center")
    _advanced(dialog)
    dialog.advanced.insertPlainText("3 * ")
    _choose(dialog, second)
    dialog.add_parameter.click()
    dialog.advanced.insertPlainText(" * ")
    _choose(dialog, fifth)
    dialog.add_parameter.click()
    dialog.advanced.insertPlainText(" / (4 * ")
    dialog.add_parameter.click()
    dialog.advanced.insertPlainText(" - ")
    _choose(dialog, second)
    dialog.add_parameter.click()
    dialog.advanced.insertPlainText(")")

    a, b = _reference(curve, second), _reference(curve, fifth)
    expected = f"3 * {a} * {b} / (4 * {b} - {a})"
    assert dialog.link_expression() == expected
    assert dialog.advanced.text().count("${Gaussian5.center}") == 2
    dialog._accept()
    assert dialog.selected_reference_scopes() == ["relative"] * 4
    expression = SafeExpression.compile(dialog.selected_link())
    assert expression.evaluate(references=project.resolved_parameter_values()) == pytest.approx(5 / 3)


def test_changing_picker_preserves_existing_reference_expression_and_scope(gui):
    project, (first, second, _) = _project()
    target, anchor, third, *_ = project.model_for(first.id).components
    other = project.model_for(second.id).components[-1]
    dialog = gui(ParameterLinkDialog, project, first.id, target.id, "center")
    _advanced(dialog)
    _choose(dialog, anchor)
    dialog.add_parameter.click()
    before = dialog.advanced.text()
    canonical = dialog.link_expression()
    _choose(dialog, other, curve=second, parameter="sigma")
    assert dialog.advanced.text() == before
    assert dialog.link_expression() == canonical
    dialog.source_curve.setCurrentIndex(dialog.source_curve.findData("self"))
    _choose(dialog, third)
    assert dialog.advanced.text() == before
    assert dialog.link_expression() == canonical
    dialog._accept()
    assert dialog.selected_reference_scopes() == ["relative"]
    assert dialog.selected_link_scope() == "relative"


def test_source_placeholder_binds_once_instead_of_following_picker(gui):
    project, (curve, _, _) = _project()
    target, second, third, *_ = project.model_for(curve.id).components
    dialog = gui(ParameterLinkDialog, project, curve.id, target.id, "center")
    _advanced(dialog)
    _choose(dialog, second)
    dialog.advanced.setText("2 * ${source} + 1")
    _choose(dialog, third)
    assert dialog.link_expression() == f"2 * {_reference(curve, second)} + 1"
    dialog._accept()
    assert dialog.selected_reference_scopes() == ["relative"]


def test_add_uses_expression_cursor_and_replaces_selected_text(gui):
    project, (curve, _, _) = _project()
    target, second, third, *_ = project.model_for(curve.id).components
    dialog = gui(ParameterLinkDialog, project, curve.id, target.id, "center")
    _advanced(dialog)
    dialog.advanced.setText("1 +  / 2")
    cursor = dialog.advanced.textCursor()
    cursor.setPosition(4)
    dialog.advanced.setTextCursor(cursor)
    _choose(dialog, second)
    dialog.add_parameter.click()
    assert dialog.advanced.text() == "1 + ${Gaussian2.center} / 2"

    cursor.setPosition(4)
    cursor.setPosition(4 + len("${Gaussian2.center}"), QTextCursor.MoveMode.KeepAnchor)
    dialog.advanced.setTextCursor(cursor)
    _choose(dialog, third)
    dialog.add_parameter.click()
    assert dialog.advanced.text() == "1 + ${Gaussian3.center} / 2"
    dialog._accept()
    assert dialog.selected_link() == f"1 + {_reference(curve, third)} / 2"
    assert dialog.selected_reference_scopes() == ["relative"]


def test_grouped_spectra_and_source_functions_follow_display_order_only(gui):
    project, (curve, _, _) = _project()
    model = project.model_for(curve.id)
    target = model.components[0]
    mathematical_ids = [component.id for component in model.components]
    x = np.linspace(0, 6, 20)
    for index, component in enumerate(model.components):
        component.parameters["center"].value = 5 - index
    before = model.evaluate(x)
    reorder_component_names(model, default_registry(), {})
    dialog = gui(ParameterLinkDialog, project, curve.id, target.id, "center")
    assert dialog.source_curve.currentData() == "self"
    assert dialog.source_curve.currentText() == "Same spectrum as this parameter"
    assert [dialog.source_curve.itemData(row) for row in range(dialog.source_curve.count())
            if dialog.source_curve.itemData(row) not in (None, "self")] == [
        spectrum.id for spectrum in project.curves
    ]
    heading_rows = [row for row in range(dialog.source_curve.count())
                    if dialog.source_curve.itemText(row) in ("Pressure scan", "Calibration")]
    assert len(heading_rows) == 2
    assert all(not dialog.source_curve.model().item(row).flags() & Qt.ItemFlag.ItemIsSelectable
               for row in heading_rows)
    assert [dialog.source_component.itemData(row) for row in range(dialog.source_component.count())] == [
        component.id for component in model.display_components
    ]
    assert [component.id for component in model.components] == mathematical_ids
    assert np.array_equal(model.evaluate(x), before)


@pytest.mark.parametrize("mode,operator", [("equal", "="), ("lower", "≥"), ("upper", "≤"), ("similar", "≈")])
def test_quick_relationships_show_explicit_target_and_read_only_expression(gui, mode, operator):
    project, (curve, _, _) = _project()
    target, second, *_ = project.model_for(curve.id).components
    dialog = gui(ParameterLinkDialog, project, curve.id, target.id, "center")
    _choose(dialog, second)
    dialog.mode.setCurrentIndex(dialog.mode.findData(mode))
    assert dialog.advanced_label.text() == f"center {operator}"
    assert dialog.advanced.isReadOnly()
    assert dialog.advanced.text() == "${Gaussian2.center}"
    assert "Gaussian1.center" in dialog.preview.text()
    assert "Gaussian2.center" in dialog.preview.text()
    assert dialog.add_parameter.isHidden()
    _advanced(dialog)
    assert dialog.advanced_label.text() == "center ="
    assert not dialog.advanced.isReadOnly()
    assert not dialog.add_parameter.isHidden()
    dialog.advanced.setText("1 + 2")
    assert dialog.link_expression() == "1 + 2"


@pytest.mark.parametrize("relation,tolerance,tolerance_mode,operator", [
    ("equal", 0, "absolute", "="),
    ("lower", 0, "absolute", "≥"),
    ("upper", 0, "absolute", "≤"),
    ("similar", 2, "absolute", "≈"),
    ("similar", 5, "percent", "≈"),
])
def test_existing_quick_relation_reopens_with_source_scope_and_tolerance(gui, relation, tolerance, tolerance_mode, operator):
    project, (curve, _, _) = _project()
    target, source, *_ = project.model_for(curve.id).components
    expression = _reference(curve, source)
    dialog = gui(ParameterLinkDialog, project, curve.id, target.id, "center", expression,
                 current_scope="absolute", current_reference_scopes=["absolute"],
                 current_relation=relation, current_tolerance=tolerance,
                 current_tolerance_mode=tolerance_mode)
    assert dialog.mode.currentData() == relation
    assert dialog.source_curve.currentData() == curve.id
    assert dialog.advanced_label.text() == f"center {operator}"
    assert "Pressure scan / Spectrum 20 / Gaussian2.center" in dialog.advanced.text()
    if relation == "similar":
        assert dialog.tolerance.value() == tolerance
        assert dialog.tolerance_mode.currentData() == tolerance_mode
        assert "Gaussian1.center" in dialog.preview.text()
        assert "≤" in dialog.preview.text()
        assert str(tolerance) in dialog.preview.text()
        if tolerance_mode == "percent":
            assert "%" in dialog.preview.text()
            assert "|" in dialog.preview.text()
            assert dialog.tolerance.maximum() < 100
    dialog._accept()
    assert dialog.selected_link() == expression
    assert dialog.selected_relation() == relation
    assert dialog.selected_link_scope() == "absolute"
    assert dialog.selected_reference_scopes() == ["absolute"]
    assert dialog.selected_tolerance() == tolerance
    assert dialog.selected_tolerance_mode() == tolerance_mode


@pytest.mark.parametrize("scope", ["relative", "absolute"])
def test_legacy_expression_reopens_every_repeated_reference_without_rebinding(gui, scope):
    project, (curve, second_curve, _) = _project()
    target, second, third, _, fifth = project.model_for(curve.id).components
    a, b = _reference(curve, second), _reference(curve, fifth)
    expression = f"3 * {a} * {b} / (4 * {b} - {a})"
    dialog = gui(ParameterLinkDialog, project, curve.id, target.id, "center", expression,
                 current_scope=scope)
    assert dialog.mode.currentData() == "advanced"
    assert curve.id not in dialog.advanced.text()
    assert dialog.link_expression() == expression
    _choose(dialog, third)
    _choose(dialog, project.model_for(second_curve.id).components[-1], curve=second_curve)
    assert dialog.link_expression() == expression
    dialog._accept()
    assert dialog.selected_link() == expression
    assert dialog.selected_reference_scopes() == [scope] * 4


def test_constant_expression_is_accepted_without_any_source_parameter(gui):
    project = Project()
    curve = Curve("Constant", [0., 1.], [1., 1.])
    project.add_curve(curve)
    target = Component.create("constant")
    project.model_for(curve.id).add(target)
    dialog = gui(ParameterLinkDialog, project, curve.id, target.id, "offset")
    assert dialog.source_parameter.count() == 0
    _advanced(dialog)
    dialog.advanced.setText("6.25 / 2")
    dialog._accept()
    assert dialog.selected_link() == "6.25 / 2"
    assert dialog.selected_reference_scopes() == []
    assert SafeExpression.compile(dialog.selected_link()).evaluate() == 3.125


def test_mixed_copy_scopes_for_identical_path_survive_apply_reopen_and_copy_chain(gui):
    project, (first, second, third) = _project()
    target, source, *_ = project.model_for(first.id).components
    window = gui(MainWindow, project)
    dialog = gui(ParameterLinkDialog, project, first.id, target.id, "center")
    _advanced(dialog)
    dialog.advanced.insertPlainText("(")
    _choose(dialog, source)
    dialog.add_parameter.click()
    dialog.advanced.insertPlainText(" + ")
    _choose(dialog, source, curve=first)
    dialog.add_parameter.click()
    dialog.advanced.insertPlainText(") / 2")
    expression = f"({_reference(first, source)} + {_reference(first, source)}) / 2"
    assert "${Gaussian2.center}" in dialog.advanced.text()
    assert "${Pressure scan / Spectrum 20 / Gaussian2.center}" in dialog.advanced.text()
    before = target.parameters["center"].to_dict()
    _apply(window, dialog, first, target)
    parameter = target.parameters["center"]
    after = parameter.to_dict()
    assert parameter.link == expression
    assert parameter.link_reference_scopes == ["relative", "absolute"]
    assert parameter.link_scope == "relative"
    window.undo_stack.undo()
    assert parameter.to_dict() == before
    window.undo_stack.redo()
    assert parameter.to_dict() == after

    reopened = gui(ParameterLinkDialog, project, first.id, target.id, "center", parameter.link,
                   current_scope=parameter.link_scope,
                   current_reference_scopes=parameter.link_reference_scopes)
    reopened._accept()
    assert reopened.selected_link() == expression
    assert reopened.selected_reference_scopes() == ["relative", "absolute"]
    project.copy_fit(first.id, [second.id], structure=False)
    project.copy_fit(second.id, [third.id], structure=False)
    for curve, center in ((second, 12), (third, 22)):
        copied_target, copied_source, *_ = project.model_for(curve.id).components
        copied_source.parameters["center"].value = center
        copied = copied_target.parameters["center"]
        assert copied.link == f"({_reference(curve, copied_source)} + {_reference(first, source)}) / 2"
        assert copied.link_reference_scopes == ["relative", "absolute"]
    assert project.resolved_parameter_values()[f"{third.id}.{project.model_for(third.id).components[0].id}.center"] == 12


@pytest.mark.parametrize("relation,tolerance,tolerance_mode,value,expected", [
    ("lower", 0, "absolute", 1, 2),
    ("upper", 0, "absolute", 10, 2),
    ("similar", 1, "absolute", 10, 3),
    ("similar", 10, "percent", 10, 2.2),
])
def test_apply_bound_relation_clamps_current_value_and_undo_restores_all_metadata(gui, relation, tolerance, tolerance_mode, value, expected):
    project, (curve, _, _) = _project()
    target, source, *_ = project.model_for(curve.id).components
    parameter = target.parameters["center"]
    parameter.value = value
    parameter.minimum, parameter.maximum = 0, 20
    before = parameter.to_dict()
    window = gui(MainWindow, project)
    dialog = gui(ParameterLinkDialog, project, curve.id, target.id, "center")
    _choose(dialog, source, curve=curve)
    dialog.mode.setCurrentIndex(dialog.mode.findData(relation))
    if relation == "similar":
        dialog.tolerance_mode.setCurrentIndex(dialog.tolerance_mode.findData(tolerance_mode))
        dialog.tolerance.setValue(tolerance)
    _apply(window, dialog, curve, target)
    after = parameter.to_dict()
    assert parameter.value == pytest.approx(expected)
    assert parameter.link == _reference(curve, source)
    assert parameter.link_scope == "absolute"
    assert parameter.link_reference_scopes == ["absolute"]
    assert parameter.link_relation == relation
    assert parameter.link_tolerance == tolerance
    assert parameter.link_tolerance_mode == tolerance_mode
    assert parameter.is_free
    assert (parameter.minimum, parameter.maximum) == (0, 20)
    window.undo_stack.undo()
    assert parameter.to_dict() == before
    window.undo_stack.redo()
    assert parameter.to_dict() == after


def test_peak_drag_respects_dynamic_and_static_bounds_and_remains_undoable(gui):
    project, (curve, _, _) = _project()
    target, source, *_ = project.model_for(curve.id).components
    parameter = target.parameters["center"]
    parameter.value = 3
    parameter.minimum, parameter.maximum = 0, 4
    window = gui(MainWindow, project)
    window.apply_parameter_link(
        curve.id, target.id, "center", _reference(curve, source), "relative",
        reference_scopes=["relative"], relation="lower",
    )
    assert parameter.is_free
    before = parameter.to_dict()
    window.drag_peak(target.id, 100, component_height(target, registry=window.registry), False)
    assert parameter.value == 4
    assert parameter.link == before["link"]
    assert parameter.link_relation == "lower"
    assert parameter.link_reference_scopes == ["relative"]
    assert project.resolved_parameter_values()[f"{curve.id}.{target.id}.center"] == 4
    window.undo_stack.undo()
    assert parameter.to_dict() == before
    window.undo_stack.redo()
    assert parameter.value == 4
    window.drag_peak(target.id, -100, component_height(target, registry=window.registry), False)
    assert parameter.value == source.parameters["center"].value == 2


def test_width_drag_remains_free_with_similarity_and_intersects_static_bounds(gui):
    project, (curve, _, _) = _project()
    target, source, *_ = project.model_for(curve.id).components
    parameter = target.parameters["sigma"]
    parameter.minimum, parameter.maximum = 0.8, 1.05
    window = gui(MainWindow, project)
    window.apply_parameter_link(
        curve.id, target.id, "sigma", _reference(curve, source, "sigma"), "relative",
        reference_scopes=["relative"], relation="similar", tolerance=0.1,
    )
    before = parameter.to_dict()
    assert parameter.is_free
    window.drag_width(target.id, 2 * 2.354820045, False)
    assert parameter.value == 1.05
    assert parameter.link_relation == "similar"
    assert parameter.link_tolerance == 0.1
    window.undo_stack.undo()
    assert parameter.to_dict() == before
    window.undo_stack.redo()
    assert parameter.value == 1.05


@pytest.mark.parametrize("parameter_name,relation", [("center", "lower"), ("sigma", "upper")])
def test_dragging_source_that_invalidates_dependent_relation_rolls_back_graph(gui, monkeypatch, parameter_name, relation):
    project, (curve, _, _) = _project()
    target, source, *_ = project.model_for(curve.id).components
    window = gui(MainWindow, project)
    window.apply_parameter_link(
        curve.id, target.id, parameter_name, _reference(curve, source, parameter_name), "relative",
        reference_scopes=["relative"], relation=relation,
    )
    model = project.model_for(curve.id)
    before = model.to_dict()
    undo_count = window.undo_stack.count()
    errors = []
    monkeypatch.setattr(window, "_show_error", lambda title, error: errors.append((title, str(error))))
    if parameter_name == "center":
        window.drag_peak(source.id, 3, component_height(source, registry=window.registry), False)
    else:
        window.drag_width(source.id, 0.5, False)
    assert len(errors) == 1
    assert "dynamic source bounds" in errors[0][1]
    assert model.to_dict() == before
    assert window.undo_stack.count() == undo_count
    assert project.resolved_parameter_values()[f"{curve.id}.{target.id}.{parameter_name}"] == (
        target.parameters[parameter_name].value
    )
