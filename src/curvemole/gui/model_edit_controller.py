"""Model editing commands for the Model panel, as one controller.

Duplicating, deleting, reordering, enabling, marking as background, locking
and editing the links of model functions used to be installed on MainWindow at
import time by model_multiselect. They now live here: MainWindow owns one
ModelEditController (window.model_edit) and its historical methods
delegate to it. Every command accepts either one function id or the batch
marker _BATCH for the current multi-selection, possibly across spectra,
and records a single undo step.

This module must not import curvemole.gui.main_window.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox

from curvemole.core.errors import ConstraintError
from curvemole.core.expressions import SafeExpression
from curvemole.gui.dialogs import ParameterLinkDialog
from curvemole.gui.model_selection import _BATCH, _find_component_curve, _restore_models
from curvemole.gui.windowing import transient_widget


def _refs_for_request(window: Any, component_id: str) -> list[tuple[str, str]]:
    if component_id == _BATCH:
        return list(window.model_panel.selected_component_refs())
    curve_id = _find_component_curve(window, component_id)
    return [(curve_id, component_id)] if curve_id else []


def _push_multi_model_change(
    window: Any,
    text: str,
    refs: list[tuple[str, str]],
    operation: Any,
) -> bool:
    curve_ids = list(dict.fromkeys(curve_id for curve_id, _ in refs))
    before = {
        curve_id: window.project.model_for(curve_id).to_dict()
        for curve_id in curve_ids
    }
    try:
        operation()
        after = {
            curve_id: window.project.model_for(curve_id).to_dict()
            for curve_id in curve_ids
        }
    except Exception as exc:
        _restore_models(window, before)
        window._show_error(text, exc)
        return False
    _restore_models(window, before)
    if before == after:
        return False
    window._push_change(
        text,
        lambda: _restore_models(window, after),
        lambda: _restore_models(window, before),
        modified_curve_ids=set(curve_ids),
    )
    return True



class ModelEditController(QObject):
    """Undoable model-function edits requested by the Model panel."""

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window

    def set_component(self, component_id: str) -> None:
        window = self.window
        editor = getattr(window, "_function_point_editor", None)
        if editor is not None and editor.active and component_id != editor.draft.id:
            window.plot_workspace.cancel_placement()
        window.selected_component_id = component_id
        window.model_panel.refresh_parameters()
        curve_id = _find_component_curve(window, component_id)
        plot_component_id = component_id if curve_id == window.active_curve_id else None
        window.plot_workspace.set_context(
            window.project,
            window.active_curve_id,
            window.curve_tree.selected_curve_ids(),
            plot_component_id,
        )

    def duplicate_component(self, component_id: str) -> None:
        window = self.window
        if not window._ensure_editable():
            return
        refs = _refs_for_request(window, component_id)
        if not refs:
            return

        created: list[str] = []

        def operation() -> None:
            for curve_id, selected_id in refs:
                model = window.project.model_for(curve_id)
                if not any(component.id == selected_id for component in model.components):
                    continue
                duplicate = model.duplicate(selected_id)
                window._assign_component_name(
                    duplicate,
                    model,
                    exclude_component_id=duplicate.id,
                )
                created.append(duplicate.id)

        text = (
            window.tr("Duplicate components")
            if len(refs) > 1
            else window.tr("Duplicate component")
        )
        changed = _push_multi_model_change(window, text, refs, operation)
        if changed and created:
            window.selected_component_id = created[-1]

    def delete_component(self, component_id: str) -> None:
        window = self.window
        if not window._ensure_editable():
            return
        refs = _refs_for_request(window, component_id)
        if not refs:
            return
        count = len(refs)
        question = (
            window.tr("Delete the selected component? This action can be undone.")
            if count == 1
            else window.tr("Delete the selected components? This action can be undone.")
        )
        grouped: dict[str, set[str]] = defaultdict(set)
        for curve_id, selected_id in refs:
            grouped[curve_id].add(selected_id)
        if (
            QMessageBox.question(window, window.tr("Delete component"), question)
            != QMessageBox.StandardButton.Yes
        ):
            return

        def operation() -> None:
            removed_paths = {
                path for curve_id, component_ids in grouped.items()
                for path in window.project.model_for(curve_id).parameter_map(curve_id)
                if path.split(".", 2)[1] in component_ids
            }
            dependents = []
            for path, parameter in window.project.parameter_map().items():
                if (path not in removed_paths and parameter.link
                        and removed_paths.intersection(SafeExpression.compile(parameter.link).references)):
                    curve_id, selected_id, name = path.split(".", 2)
                    curve = window.project.dataset.curve(curve_id)
                    component = window.project.model_for(curve_id).component(selected_id)
                    dependents.append(f"{curve.name} / {component.name}.{name}")
            if dependents:
                raise ConstraintError(window.tr(
                    "Cannot delete these functions because remaining parameters reference them. "
                    "Remove the following links or constraints first:"
                ) + "\n" + "\n".join(dependents))
            for curve_id, component_ids in grouped.items():
                model = window.project.model_for(curve_id)
                model.delete_components(component_ids)
            window._validate_all_links()

        changed = _push_multi_model_change(
            window,
            window.tr("Delete components") if count > 1 else window.tr("Delete component"),
            refs,
            operation,
        )
        if changed:
            window.selected_component_id = None

    def move_component(self, component_id: str, delta: int) -> None:
        window = self.window
        if not window._ensure_editable() or delta not in {-1, 1}:
            return
        refs = _refs_for_request(window, component_id)
        if not refs:
            return
        grouped: dict[str, set[str]] = defaultdict(set)
        for curve_id, selected_id in refs:
            grouped[curve_id].add(selected_id)

        def operation() -> None:
            for curve_id, selected_ids in grouped.items():
                model = window.project.model_for(curve_id)
                components = model.components
                model.display_order = []
                if delta < 0:
                    for index in range(1, len(components)):
                        if (
                            components[index].id in selected_ids
                            and components[index - 1].id not in selected_ids
                        ):
                            components[index - 1], components[index] = (
                                components[index],
                                components[index - 1],
                            )
                else:
                    for index in range(len(components) - 2, -1, -1):
                        if (
                            components[index].id in selected_ids
                            and components[index + 1].id not in selected_ids
                        ):
                            components[index], components[index + 1] = (
                                components[index + 1],
                                components[index],
                            )

        _push_multi_model_change(window, window.tr("Reorder components"), refs, operation)

    def enable_component(self, component_id: str, enabled: bool) -> None:
        window = self.window
        if not window._ensure_editable():
            return
        refs = _refs_for_request(window, component_id)
        changes = []
        for curve_id, selected_id in refs:
            component = window.project.model_for(curve_id).component(selected_id)
            if component.enabled != bool(enabled):
                changes.append((curve_id, selected_id, component.enabled, bool(enabled)))
        if not changes:
            return

        def restore(use_new: bool) -> None:
            for curve_id, selected_id, old, new in changes:
                component = window.project.model_for(curve_id).component(selected_id)
                component.enabled = new if use_new else old

        window._push_change(
            window.tr("Enable/disable components")
            if len(changes) > 1
            else window.tr("Enable/disable component"),
            lambda: restore(True),
            lambda: restore(False),
            modified_curve_ids={curve_id for curve_id, *_ in changes},
        )

    def set_component_background(self, component_id: str, marked: bool) -> None:
        window = self.window
        if not window._ensure_editable():
            return
        refs = _refs_for_request(window, component_id)
        changes = []
        for curve_id, selected_id in refs:
            component = window.project.model_for(curve_id).component(selected_id)
            if component.is_background != bool(marked):
                changes.append((curve_id, selected_id, component.is_background, bool(marked)))
        if not changes:
            return

        def restore(use_new: bool) -> None:
            for curve_id, selected_id, old, new in changes:
                component = window.project.model_for(curve_id).component(selected_id)
                component.is_background = new if use_new else old

        text = (
            window.tr("Mark backgrounds")
            if marked and len(changes) > 1
            else window.tr("Unmark backgrounds")
            if len(changes) > 1
            else window.tr("Mark background")
            if marked
            else window.tr("Unmark background")
        )
        window._push_change(text, lambda: restore(True), lambda: restore(False),
                            modified_curve_ids={curve_id for curve_id, *_ in changes})

    def set_component_fixed(self, component_id: str, fixed: bool) -> None:
        window = self.window
        if not window._ensure_editable():
            return
        refs = _refs_for_request(window, component_id)
        if fixed:
            for curve_id, selected_id in refs:
                component = window.project.model_for(curve_id).component(selected_id)
                if any(not window._can_fix_parameter(curve_id, selected_id, name)
                       for name in component.parameters):
                    return
        changes: list[tuple[str, str, dict[str, bool], dict[str, bool]]] = []
        for curve_id, selected_id in refs:
            component = window.project.model_for(curve_id).component(selected_id)
            before = {
                name: parameter.fixed
                for name, parameter in component.parameters.items()
            }
            after = {name: bool(fixed) for name in component.parameters}
            if before != after:
                changes.append((curve_id, selected_id, before, after))
        if not changes:
            return

        def restore(which: int) -> None:
            for curve_id, selected_id, before, after in changes:
                component = window.project.model_for(curve_id).component(selected_id)
                values = after if which else before
                for name, value in values.items():
                    component.parameters[name].fixed = value

        text = (
            window.tr("Lock all parameters in selected functions")
            if fixed
            else window.tr("Unlock all parameters in selected functions")
        )
        window._push_change(text, lambda: restore(1), lambda: restore(0),
                            modified_curve_ids={curve_id for curve_id, *_ in changes})

    def change_parameter(self, component_id: str, name: str, field: str, value: Any) -> None:
        window = self.window
        curve_id = _find_component_curve(window, component_id)
        if curve_id is None:
            return
        window._change_parameter_for_curve(curve_id, component_id, name, field, value)

    def edit_parameter_link(self, component_id: str, name: str) -> None:
        window = self.window
        curve_id = _find_component_curve(window, component_id)
        if curve_id is None:
            return
        parameter = window.project.model_for(curve_id).component(component_id).parameters[name]
        with transient_widget(ParameterLinkDialog(
            window.project,
            curve_id,
            component_id,
            name,
            parameter.link,
            window,
            current_scope=parameter.link_scope,
            current_reference_scopes=parameter.link_reference_scopes,
            current_relation=parameter.link_relation,
            current_tolerance=parameter.link_tolerance,
            current_tolerance_mode=parameter.link_tolerance_mode,
        )) as dialog:
            if dialog.exec() != dialog.DialogCode.Accepted:
                return
            window.apply_parameter_link(curve_id, component_id, name,
                                        dialog.selected_link(), dialog.selected_link_scope(),
                                        reference_scopes=dialog.selected_reference_scopes(),
                                        relation=dialog.selected_relation(), tolerance=dialog.selected_tolerance(),
                                        tolerance_mode=dialog.selected_tolerance_mode())

    def copy_parameter(self) -> None:
        """Copy-parameter dialog for the panel's single selected source function."""
        # Resolved through the modules so tests and plugins can substitute them.
        from curvemole.gui import parameter_copy, parameter_copy_redesign

        window = self.window
        panel = window.model_panel
        refs = panel.selected_component_refs()
        if len(refs) != 1 or not window._ensure_editable():
            return
        source_ref = refs[0]
        remembered = panel._parameter_copy_source_ref == source_ref
        parameter_hint = panel._parameter_copy_parameter_name if remembered else None
        dialog_type = parameter_copy_redesign.CopyParameterDialog
        with transient_widget(dialog_type(window, source_ref, current_parameter=parameter_hint)) as dialog:
            if remembered and panel._parameter_copy_all_parameters:
                dialog.parameter.setCurrentIndex(dialog.parameter.findData(None))
            if dialog.exec() != dialog.DialogCode.Accepted:
                return
            try:
                result = parameter_copy.copy_parameter_to_refs(
                    window,
                    dialog.source_ref(),
                    dialog.target_refs(),
                    dialog.parameter_name(),
                    copy_value=dialog.copy_value.isChecked(),
                    copy_fixed=dialog.copy_fixed.isChecked(),
                    copy_bounds=dialog.copy_bounds.isChecked(),
                    copy_link=dialog.copy_link.isChecked(),
                )
            except Exception as exc:
                window._show_error(window.tr("Copy parameter"), exc)
                return
            panel.remember_parameter_copy(source_ref, dialog.parameter_name())
            parameter_copy._show_copy_result(window, result, dialog.parameter_name())
