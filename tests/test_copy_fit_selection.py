import copy

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from curvemole import Component, Curve, Project
from curvemole.core.errors import ConstraintError
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.dialogs import CopyFitDialog


def example():
    project = Project()
    for name in ('Source', 'Target', 'Other target'):
        project.add_curve(Curve(name, [0., 1., 2.], [1., 2., 3.]))
    for curve in project.curves:
        model = project.model_for(curve.id)
        for index in range(3):
            model.add(Component.create('gaussian', name=f'Peak {index}', initial={'area': index + 1.}))
    return project


def test_structure_copy_includes_only_chosen_functions_and_preserves_global_order():
    project = example()
    source, target, _ = project.curves
    model = project.model_for(source.id)
    first, second, third = model.components
    model.set_component_operator(third.id, 'multiply')
    model.operation_order = [third.id]
    project.copy_fit(source.id, [target.id], component_ids=[first.id, third.id])
    copied = project.model_for(target.id)
    assert [c.id for c in copied.components] == [first.id, third.id]
    assert second.id not in [c.id for c in copied.components]
    assert copied.composition_mode == 'global'
    assert copied.operation_order == [third.id]
    assert copied.component(third.id).operator == 'multiply'
    assert [c.id for c in model.components] == [first.id, second.id, third.id]


def test_values_only_selection_keeps_original_corresponding_positions():
    project = example()
    source, target, _ = project.curves
    sources = project.model_for(source.id).components
    targets = project.model_for(target.id).components
    sources[1].parameters['area'].value = 25
    before = [copy.deepcopy(c.to_dict()) for c in targets]
    project.copy_fit(source.id, [target.id], structure=False, component_ids=[sources[1].id])
    copied = project.model_for(target.id).components
    assert copied[0].to_dict() == before[0]
    assert copied[1].parameters['area'].value == 25
    assert copied[2].to_dict() == before[2]


def test_missing_relative_link_dependency_rolls_back_every_target_and_data():
    project = example()
    source, target, other = project.curves
    first, second, _ = project.model_for(source.id).components
    second.parameters['center'].link = f'${{{source.id}.{first.id}.center}}'
    source.fit_ranges = [(0., 1.)]
    source.masks[source.active_mask].excluded[0] = True
    old_models = {curve.id: copy.deepcopy(project.model_for(curve.id).to_dict()) for curve in (target, other)}
    old_revision = project.revision
    with pytest.raises(ConstraintError, match='Include the referenced functions'):
        project.copy_fit(source.id, [target.id, other.id], component_ids=[second.id], masks=True, fit_ranges=True)
    assert project.revision == old_revision
    for curve in (target, other):
        assert project.model_for(curve.id).to_dict() == old_models[curve.id]
        assert not curve.fit_ranges
        assert not np.any(curve.masks[curve.active_mask].excluded)
    project.copy_fit(source.id, [target.id], component_ids=[second.id], links=False)
    assert project.model_for(target.id).components[0].parameters['center'].link is None


def test_dialog_selects_functions_and_background_filter_preserves_choices():
    app = QApplication.instance() or QApplication([])
    project = example()
    source, target, _ = project.curves
    component = project.model_for(source.id).components[0]
    component.is_background = True
    dialog = CopyFitDialog(project, source.id, next_curve_id=target.id)
    assert len(dialog.choices()[1]['component_ids']) == 3
    dialog.functions.item(1).setCheckState(Qt.CheckState.Unchecked)
    dialog.background.setChecked(False)
    assert dialog.choices()[1]['component_ids'] == [project.model_for(source.id).components[2].id]
    dialog.background.setChecked(True)
    assert component.id in dialog.choices()[1]['component_ids']
    dialog.clear_functions_button.click()
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.masks.setChecked(True)
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.close()
    app.processEvents()


def test_gui_copy_selection_masks_ranges_and_single_undo(monkeypatch):
    app = QApplication.instance() or QApplication([])
    project = example()
    source, target, _ = project.curves
    source.fit_ranges = [(0., 1.)]
    source.masks[source.active_mask].excluded[0] = True
    window = CurveMoleMainWindow(project)
    before = copy.deepcopy(project.model_for(target.id).to_dict())
    selected = project.model_for(source.id).components[1].id
    def choose(dialog):
        dialog.functions.item(0).setCheckState(Qt.CheckState.Unchecked)
        dialog.functions.item(2).setCheckState(Qt.CheckState.Unchecked)
        for row in range(dialog.targets.count()):
            item = dialog.targets.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == target.id:
                item.setCheckState(Qt.CheckState.Checked)
        dialog.masks.setChecked(True)
        dialog.ranges.setChecked(True)
        return dialog.DialogCode.Accepted
    monkeypatch.setattr(CopyFitDialog, 'exec', choose)
    window.copy_fit()
    assert [c.id for c in project.model_for(target.id).components] == [selected]
    assert target.fit_ranges == [(0., 1.)]
    assert target.masks[target.active_mask].excluded[0]
    assert window.undo_stack.count() == 1
    window.undo_stack.undo()
    assert project.model_for(target.id).to_dict() == before
    assert not target.fit_ranges
    assert not np.any(target.masks[target.active_mask].excluded)
    window.undo_stack.redo()
    assert [c.id for c in project.model_for(target.id).components] == [selected]
    assert target.fit_ranges == [(0., 1.)]
    assert target.masks[target.active_mask].excluded[0]
    project.dirty = False
    window.close()
    app.processEvents()
