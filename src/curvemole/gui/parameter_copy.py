"""Copy one parameter from a selected model function to other selected functions."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMessageBox,
    QPushButton,
)

from curvemole.core.errors import ConstraintError
from curvemole.core.models import Model
from curvemole.gui.main_window import MainWindow
from curvemole.gui.panels import ModelPanel


@dataclass(slots=True)
class ParameterCopyResult:
    copied: int
    missing_parameter: list[tuple[str, str]]
    incompatible_bounds: list[tuple[str, str]]


def _component_label(window: MainWindow, ref: tuple[str, str]) -> str:
    curve_id, component_id = ref
    curve = window.project.dataset.curve(curve_id)
    component = window.project.model_for(curve_id).component(component_id)
    return f"{curve.name}  ›  {component.name}"


def _restore_models(window: MainWindow, states: dict[str, dict[str, Any]]) -> None:
    for curve_id, state in states.items():
        window.project.models[curve_id] = Model.from_dict(copy.deepcopy(state))


def copy_parameter_to_refs(
    window: MainWindow,
    source_ref: tuple[str, str],
    target_refs: list[tuple[str, str]],
    parameter_name: str | None,
    *,
    copy_value: bool = False,
    copy_fixed: bool = False,
    copy_bounds: bool = False,
    copy_link: bool = False,
) -> ParameterCopyResult:
    """Copy a named parameter, or all source parameters (None), as one undoable edit.

    Value and constraint fields are copied independently. Fit-derived uncertainties
    are cleared on changed target parameters.
    """
    if not window._ensure_editable():
        return ParameterCopyResult(0, [], [])

    source_curve_id, source_component_id = source_ref
    source_component = window.project.model_for(source_curve_id).component(source_component_id)
    names = list(source_component.parameters) if parameter_name is None else [parameter_name]
    for name in names:
        if name not in source_component.parameters:
            raise KeyError(name)
    if not names:
        return ParameterCopyResult(0, [], [])
    if not any((copy_value, copy_fixed, copy_bounds, copy_link)):
        return ParameterCopyResult(0, [], [])

    unique_targets = [ref for ref in dict.fromkeys(target_refs) if ref != source_ref]
    compatible: list[tuple[str, str]] = []
    missing: list[tuple[str, str]] = []
    incompatible_bounds: list[tuple[str, str]] = []

    for curve_id, component_id in unique_targets:
        component = window.project.model_for(curve_id).component(component_id)
        if any(name not in component.parameters for name in names):
            missing.append((curve_id, component_id))
            continue
        pairs = [(source_component.parameters[name], component.parameters[name]) for name in names]
        if any(
            (copy_value and not copy_bounds and not target.minimum <= source.value <= target.maximum)
            or (copy_bounds and not copy_value and not source.minimum <= target.value <= source.maximum)
            for source, target in pairs
        ):
            incompatible_bounds.append((curve_id, component_id))
            continue
        if copy_fixed or copy_link:
            for name in names:
                source = source_component.parameters[name]
                target = component.parameters[name]
                fixed = source.fixed if copy_fixed else target.fixed
                linked = source if copy_link else target
                if fixed and linked.link and linked.link_relation == "equal":
                    raise ConstraintError(window.tr(
                        "{parameter} cannot be both fixed and controlled by an equality link. "
                        "Remove the link in the Link column first, or clear Fixed before copying the link."
                    ).format(parameter=f"{component.name}.{name}"))
        compatible.append((curve_id, component_id))

    if not compatible:
        return ParameterCopyResult(0, missing, incompatible_bounds)

    curve_ids = list(dict.fromkeys(curve_id for curve_id, _ in compatible))
    before = {
        curve_id: window.project.model_for(curve_id).to_dict()
        for curve_id in curve_ids
    }

    try:
        for curve_id, component_id in compatible:
            target_component = window.project.model_for(curve_id).component(component_id)
            for name in names:
                source = source_component.parameters[name]
                target = target_component.parameters[name]
                if copy_bounds:
                    target.minimum = source.minimum
                    target.maximum = source.maximum
                if copy_value:
                    target.value = source.value
                if copy_fixed:
                    target.fixed = source.fixed
                if copy_link:
                    source_model = window.project.model_for(source_curve_id)
                    target_model = window.project.model_for(curve_id)
                    component_ids = {}
                    for index, item in enumerate(source_model.components):
                        matches = [candidate for candidate in target_model.components if candidate.id == item.id]
                        if not matches:
                            matches = [candidate for candidate in target_model.components
                                       if candidate.name == item.name and candidate.function_id == item.function_id]
                        if len(matches) != 1 and index < len(target_model.components):
                            candidate = target_model.components[index]
                            matches = [candidate] if candidate.function_id == item.function_id else []
                        if len(matches) == 1:
                            component_ids[item.id] = matches[0].id
                    component_ids[source_component_id] = component_id
                    target.link = source.copied_link(source_curve_id, curve_id, component_ids)
                    target.link_scope = source.link_scope
                    target.link_reference_scopes = list(source.link_reference_scopes)
                    target.link_relation = source.link_relation
                    target.link_tolerance = source.link_tolerance
                    target.link_tolerance_mode = source.link_tolerance_mode
                target.standard_error = None
                target.ci_low = None
                target.ci_high = None
                target.validate()
        window._validate_all_links()
        after = {
            curve_id: window.project.model_for(curve_id).to_dict()
            for curve_id in curve_ids
        }
    except Exception:
        _restore_models(window, before)
        raise

    _restore_models(window, before)
    window._push_change(
        window.tr("Copy all parameters to selected functions") if parameter_name is None else window.tr("Copy parameter to selected functions"),
        lambda: _restore_models(window, after),
        lambda: _restore_models(window, before),
        modified_curve_ids=set(curve_ids),
    )
    return ParameterCopyResult(len(compatible), missing, incompatible_bounds)


def __getattr__(name):
    if name == "CopyParameterDialog":
        from curvemole.gui.parameter_copy_redesign import CopyParameterDialog
        return CopyParameterDialog
    raise AttributeError(name)


def _show_copy_result(window: MainWindow, result: ParameterCopyResult, parameter_name: str | None) -> None:
    description = window.tr("all parameters") if parameter_name is None else window.tr("parameter '") + parameter_name + "'"
    message = window.tr("Copied ") + description + window.tr(" to ") + str(result.copied) + window.tr(" selected function(s).")
    skipped = len(result.missing_parameter) + len(result.incompatible_bounds)
    if skipped:
        message += "\n\n" + window.tr("Skipped: ")
        details = []
        if result.missing_parameter:
            details.append(
                str(len(result.missing_parameter)) + " " + (window.tr("without all requested parameters") if parameter_name is None else window.tr("without that parameter"))
            )
        if result.incompatible_bounds:
            details.append(
                str(len(result.incompatible_bounds))
                + " "
                + window.tr("because parameter values and bounds are incompatible")
            )
        message += ", ".join(details) + "."
    QMessageBox.information(window, window.tr("Copy parameter"), message)


def _install_parameter_copy() -> None:
    if getattr(ModelPanel, "_curvemole_parameter_copy", False):
        return

    original_init = ModelPanel.__init__

    def init(panel: ModelPanel, *args: Any, **kwargs: Any) -> None:
        original_init(panel, *args, **kwargs)
        panel._parameter_copy_source_ref = None
        panel._parameter_copy_parameter_name = None
        panel.copy_parameter_button = QPushButton(panel.tr("Select a parameter, then select target functions"))
        panel.copy_parameter_button.setToolTip(
            panel.tr(
                "Workflow: 1) select the source function; 2) click the parameter row you want to copy; "
                "3) Ctrl/Shift-select the target functions; 4) choose which fields to copy."
            )
        )
        single = panel.stack.widget(0)
        index = single.layout().indexOf(panel.parameters)
        single.layout().insertWidget(index, panel.copy_parameter_button)
        panel.copy_parameter_button.clicked.connect(panel._copy_parameter_to_selected)
        panel.components.itemSelectionChanged.connect(panel._update_copy_parameter_button)
        panel.parameters.currentCellChanged.connect(panel._remember_parameter_copy_source)
        panel._update_copy_parameter_button()

    def remember_source(
        panel: ModelPanel,
        row: int,
        column: int,
        previous_row: int,
        previous_column: int,
    ) -> None:
        del column, previous_row, previous_column
        if panel._updating or row < 0:
            return
        refs = panel.selected_component_refs()
        if len(refs) != 1:
            return
        value_item = panel.parameters.item(row, 1)
        metadata = value_item.data(Qt.ItemDataRole.UserRole) if value_item is not None else None
        if not metadata:
            return
        panel._parameter_copy_source_ref = refs[0]
        panel._parameter_copy_parameter_name = str(metadata[1])
        panel._parameter_copy_all_parameters = False
        panel._update_copy_parameter_button()

    def update_button(panel: ModelPanel) -> None:
        from curvemole.gui.parameter_copy_redesign import _update_button
        _update_button(panel)

    def copy_selected(panel: ModelPanel) -> None:
        from curvemole.gui.parameter_copy_redesign import _copy_selected
        _copy_selected(panel)

    ModelPanel.__init__ = init
    ModelPanel._remember_parameter_copy_source = remember_source
    ModelPanel._update_copy_parameter_button = update_button
    ModelPanel._copy_parameter_to_selected = copy_selected
    ModelPanel._curvemole_parameter_copy = True


_install_parameter_copy()
