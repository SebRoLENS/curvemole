import copy

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

from curvemole import Component, Curve, Project
from curvemole.core.errors import ConstraintError
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.parameter_copy import copy_parameter_to_refs


@pytest.fixture
def editor(monkeypatch):
    app = QApplication.instance() or QApplication([])
    project = Project()
    x = np.linspace(-3., 3., 51)
    for name in ("Source spectrum", "Target spectrum"):
        project.add_curve(Curve(name, x, np.exp(-x*x)))
    first = Component.create("pseudo_voigt", name="PseudoVoigt1")
    second = Component.create("pseudo_voigt", name="PseudoVoigt2")
    for curve in project.curves:
        project.model_for(curve.id).components = copy.deepcopy([first, second])
    window = CurveMoleMainWindow(project)
    errors = []
    monkeypatch.setattr(window, "_show_error", lambda title, error: errors.append((title, str(error))))
    window.show()
    app.processEvents()
    yield app, window, first.id, second.id, errors
    project.dirty = False
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def show_component(window, curve_id, component_id):
    panel = window.model_panel
    panel.show_all_functions.setChecked(True)
    item = next(panel.components.item(row) for row in range(panel.components.count())
                if panel.components.item(row).data(Qt.ItemDataRole.UserRole) == component_id
                and panel.components.item(row).data(int(Qt.ItemDataRole.UserRole) + 1) == curve_id)
    panel.components.clearSelection()
    panel.components.setCurrentItem(item)
    item.setSelected(True)
    QApplication.processEvents()


def project_state(project):
    return copy.deepcopy((
        {curve_id: model.to_dict() for curve_id, model in project.models.items()},
        project.dirty,
        {curve.id: curve.state for curve in project.curves},
    ))


@pytest.mark.parametrize("stored_fixed", [False, True])
def test_fixed_checkbox_explains_equality_link_without_mutating_project(editor, stored_fixed):
    app, window, first_id, second_id, errors = editor
    source, target = window.project.curves
    model = window.project.model_for(target.id)
    parameter = model.component(first_id).parameters["center"]
    parameter.link = f"${{{model.parameter_path(target.id, second_id, 'center')}}}"
    parameter.fixed = stored_fixed
    window.refresh_all()
    show_component(window, target.id, first_id)
    before = project_state(window.project)
    undo_count = window.undo_stack.count()
    panel = window.model_panel
    row = list(model.component(first_id).parameters).index("center")
    item = panel.parameters.item(row, 4)
    assert item.text() == "Linked"
    assert item.checkState() == Qt.CheckState.Unchecked
    assert not item.flags() & Qt.ItemFlag.ItemIsEditable
    assert "Remove the link in the Link column first" in item.toolTip()
    option = QStyleOptionViewItem()
    option.initFrom(panel.parameters)
    option.rect = panel.parameters.visualItemRect(item)
    index = panel.parameters.indexFromItem(item)
    panel.parameters.itemDelegate().initStyleOption(option, index)
    rect = panel.parameters.style().subElementRect(
        QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, panel.parameters)
    QTest.mouseClick(panel.parameters.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    app.processEvents()
    assert len(errors) == 1
    assert "PseudoVoigt1.center" in errors[0][1]
    assert "Remove the link in the Link column first" in errors[0][1]
    assert project_state(window.project) == before
    assert window.undo_stack.count() == undo_count
    assert panel.parameters.item(row, 4).checkState() == Qt.CheckState.Unchecked
    assert not window.project.model_for(source.id).component(first_id).parameters["center"].fixed


def test_lock_all_rejects_selected_functions_atomically(editor):
    _, window, first_id, second_id, errors = editor
    curve = window.project.curves[0]
    model = window.project.model_for(curve.id)
    parameter = model.component(second_id).parameters["center"]
    parameter.link = f"${{{model.parameter_path(curve.id, first_id, 'center')}}}"
    window.refresh_all()
    show_component(window, curve.id, first_id)
    panel = window.model_panel
    for row in range(panel.components.count()):
        item = panel.components.item(row)
        if item.data(int(Qt.ItemDataRole.UserRole) + 1) == curve.id:
            item.setSelected(True)
    before = project_state(window.project)
    undo_count = window.undo_stack.count()
    panel._bulk_fixed(True)
    assert len(errors) == 1
    assert "PseudoVoigt2.center" in errors[0][1]
    assert project_state(window.project) == before
    assert window.undo_stack.count() == undo_count


def test_removing_equality_link_allows_fixing_and_undo_restores_link(editor):
    _, window, first_id, second_id, errors = editor
    curve = window.project.curves[0]
    model = window.project.model_for(curve.id)
    parameter = model.component(first_id).parameters["center"]
    link = f"${{{model.parameter_path(curve.id, second_id, 'center')}}}"
    parameter.link = link
    window.refresh_all()
    show_component(window, curve.id, first_id)
    window.apply_parameter_link(curve.id, first_id, "center", None, "relative")
    window.change_parameter(first_id, "center", "value", .4)
    window.change_parameter(first_id, "center", "fixed", True)
    assert not errors
    assert parameter.fixed and parameter.value == .4 and parameter.link is None
    window.undo_stack.undo()
    window.undo_stack.undo()
    window.undo_stack.undo()
    assert parameter.link == link and not parameter.fixed
    window.undo_stack.redo()
    window.undo_stack.redo()
    window.undo_stack.redo()
    assert parameter.fixed and parameter.value == .4 and parameter.link is None


def test_equality_link_cannot_be_added_to_fixed_parameter(editor):
    _, window, first_id, second_id, errors = editor
    curve = window.project.curves[0]
    model = window.project.model_for(curve.id)
    parameter = model.component(first_id).parameters["center"]
    parameter.fixed = True
    link = f"${{{model.parameter_path(curve.id, second_id, 'center')}}}"
    undo_count = window.undo_stack.count()
    window.apply_parameter_link(curve.id, first_id, "center", link, "relative")
    assert len(errors) == 1
    assert "Clear Fixed before adding an equality link" in errors[0][1]
    assert parameter.fixed and parameter.link is None
    assert window.undo_stack.count() == undo_count


@pytest.mark.parametrize("copy_fixed,copy_link", [(True, False), (False, True), (True, True)])
def test_parameter_copy_cannot_create_fixed_equality_link_on_any_target(editor, copy_fixed, copy_link):
    _, window, first_id, second_id, _ = editor
    source_curve, target_curve = window.project.curves
    source_model = window.project.model_for(source_curve.id)
    target_model = window.project.model_for(target_curve.id)
    source = source_model.component(first_id).parameters["center"]
    target = target_model.component(first_id).parameters["center"]
    source.fixed = copy_fixed
    target.fixed = not copy_fixed
    if copy_link:
        source.link = f"${{{source_model.parameter_path(source_curve.id, second_id, 'center')}}}"
    else:
        target.link = f"${{{target_model.parameter_path(target_curve.id, second_id, 'center')}}}"
    before = project_state(window.project)
    undo_count = window.undo_stack.count()
    with pytest.raises(ConstraintError, match="Remove the link in the Link column first"):
        copy_parameter_to_refs(
            window, (source_curve.id, first_id),
            [(target_curve.id, second_id), (target_curve.id, first_id)], "center",
            copy_fixed=copy_fixed, copy_link=copy_link,
        )
    assert project_state(window.project) == before
    assert window.undo_stack.count() == undo_count


@pytest.mark.parametrize("relation", [None, "lower", "upper", "similar"])
def test_static_and_dynamic_bounds_remain_compatible_with_fixed(editor, relation):
    _, window, first_id, second_id, errors = editor
    curve = window.project.curves[0]
    model = window.project.model_for(curve.id)
    parameter = model.component(first_id).parameters["center"]
    parameter.minimum, parameter.maximum = -2., 2.
    if relation:
        parameter.link = f"${{{model.parameter_path(curve.id, second_id, 'center')}}}"
        parameter.link_relation = relation
        parameter.link_tolerance = 1.
    window.refresh_all()
    show_component(window, curve.id, first_id)
    window.change_parameter(first_id, "center", "fixed", True)
    assert not errors
    assert parameter.fixed
    window.undo_stack.undo()
    assert not parameter.fixed
