import copy

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from curvemole import Component, Curve, Project
from curvemole.core.data import CurveState
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.component_composition import COMPOSITION_ROLE, CalculationOrderDialog


@pytest.fixture
def composition_editor():
    app = QApplication.instance() or QApplication([])
    project = Project()
    x = np.linspace(-4, 4, 201)
    for name in ('Source', 'Target'):
        project.add_curve(Curve(name, x, np.exp(-x*x)))
    first = Component.create('gaussian', name='First peak')
    second = Component.create('gaussian', name='Second peak', initial={'center': 1.})
    for curve in project.curves:
        project.model_for(curve.id).components = [copy.deepcopy(first), copy.deepcopy(second)]
    window = CurveMoleMainWindow(project)
    window.show()
    app.processEvents()
    yield app, window, first, second
    project.dirty = False
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def item_for(panel, curve_id, component_id):
    return next(panel.components.item(row) for row in range(panel.components.count())
                if panel.components.item(row).data(Qt.ItemDataRole.UserRole) == component_id
                and panel.components.item(row).data(int(Qt.ItemDataRole.UserRole) + 1) == curve_id)


def test_inline_composition_menu_changes_only_clicked_spectrum_with_shared_ids(composition_editor):
    app, window, first, _second = composition_editor
    source, target = window.project.curves
    source.state = target.state = CurveState.FITTED
    panel = window.model_panel
    panel.show_all_functions.setChecked(True)
    app.processEvents()
    item = item_for(panel, target.id, first.id)
    assert item.data(COMPOSITION_ROLE) == 'add'
    index = panel.components.indexFromItem(item)
    rect = panel.components.itemDelegate().composition_rect(index)
    QTest.mouseClick(panel.components.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    menu = QApplication.activePopupWidget()
    assert isinstance(menu, QMenu)
    multiply = next(action for action in menu.actions() if action.data() == 'multiply')
    assert multiply.isEnabled()  # A global role has no insertion-predecessor restriction.
    multiply.trigger()
    menu.close()
    assert window.project.model_for(target.id).component(first.id).operator == 'multiply'
    assert window.project.model_for(source.id).component(first.id).operator == 'add'
    assert source.state == CurveState.FITTED
    assert target.state == CurveState.MODIFIED
    assert item_for(panel, target.id, first.id).data(COMPOSITION_ROLE) == 'multiply'
    window.undo_stack.undo()
    assert window.project.model_for(target.id).component(first.id).operator == 'add'
    window.undo_stack.redo()
    assert window.project.model_for(target.id).component(first.id).operator == 'multiply'


def test_calculation_order_dialog_changes_expression_result_and_is_undoable(composition_editor, monkeypatch):
    _, window, _first, _second = composition_editor
    curve = window.project.curves[0]
    model = window.project.model_for(curve.id)
    factor = Component.create('linear', operator='multiply', initial={'intercept': 3., 'slope': .3})
    kernel = Component.create('gaussian', operator='convolve', initial={'sigma': .6})
    model.add(factor)
    model.add(kernel)
    window.refresh_all()
    before = model.evaluate(curve.x)
    old = copy.deepcopy(model.to_dict())
    def choose(dialog):
        assert dialog.model.composition_mode == 'global'
        assert dialog.operations.item(0).data(Qt.ItemDataRole.UserRole) == factor.id
        dialog.operations.setCurrentRow(0)
        dialog._move(1)
        assert dialog.choices()[1] == [kernel.id, factor.id]
        assert 'convolve' in dialog.preview.text()
        return dialog.DialogCode.Accepted
    monkeypatch.setattr(CalculationOrderDialog, 'exec', choose)
    window.model_panel.calculation_order_button.click()
    updated = window.project.model_for(curve.id)
    assert updated.operation_order == [kernel.id, factor.id]
    assert not np.allclose(updated.evaluate(curve.x), before)
    assert 'convolve' in window.model_panel.composition_summary.text()
    window.undo_stack.undo()
    assert window.project.model_for(curve.id).to_dict() == old
    window.undo_stack.redo()
    assert window.project.model_for(curve.id).operation_order == [kernel.id, factor.id]


def test_legacy_conversion_is_explicit_and_cancel_keeps_calculation(composition_editor, monkeypatch):
    _, window, first, _ = composition_editor
    curve = window.project.curves[0]
    model = window.project.model_for(curve.id)
    model.composition_mode = 'ordered'
    old = copy.deepcopy(model.to_dict())
    def cancel(dialog):
        dialog.mode.setCurrentIndex(dialog.mode.findData('global'))
        return dialog.DialogCode.Rejected
    monkeypatch.setattr(CalculationOrderDialog, 'exec', cancel)
    window.edit_calculation_order(curve.id)
    assert window.project.model_for(curve.id).to_dict() == old
    def accept(dialog):
        dialog.mode.setCurrentIndex(dialog.mode.findData('global'))
        return dialog.DialogCode.Accepted
    monkeypatch.setattr(CalculationOrderDialog, 'exec', accept)
    window.edit_calculation_order(curve.id)
    assert window.project.model_for(curve.id).composition_mode == 'global'
    window.set_component_operator(curve.id, first.id, 'multiply')
    assert window.project.model_for(curve.id).component(first.id).operator == 'multiply'
