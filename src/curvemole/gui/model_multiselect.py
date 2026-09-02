"""Multi-selection and cross-spectrum model-function management for the desktop GUI."""

from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMessageBox,
    QWidget,
)

from curvemole.core.models import Model
from curvemole.gui.dialogs import ParameterLinkDialog
from curvemole.gui.main_window import MainWindow
from curvemole.gui.panels import ModelPanel

_CURVE_ROLE = int(Qt.ItemDataRole.UserRole) + 1
_BATCH = "__curvemole_batch_components__"


def _item_ref(item: QListWidgetItem | None) -> tuple[str, str] | None:
    if item is None:
        return None
    component_id = item.data(Qt.ItemDataRole.UserRole)
    curve_id = item.data(_CURVE_ROLE)
    if component_id is None or curve_id is None:
        return None
    return str(curve_id), str(component_id)


def _selected_refs(panel: ModelPanel) -> list[tuple[str, str]]:
    refs = {
        ref
        for item in panel.components.selectedItems()
        if (ref := _item_ref(item)) is not None
    }
    ordered: list[tuple[str, str]] = []
    for row in range(panel.components.count()):
        ref = _item_ref(panel.components.item(row))
        if ref in refs:
            ordered.append(ref)
    return ordered


def _current_ref(panel: ModelPanel) -> tuple[str, str] | None:
    return _item_ref(panel.components.currentItem())


def _find_component_curve(window: MainWindow, component_id: str) -> str | None:
    for curve_id, model in window.project.models.items():
        if any(component.id == component_id for component in model.components):
            return curve_id
    return None


def _refs_for_request(window: MainWindow, component_id: str) -> list[tuple[str, str]]:
    if component_id == _BATCH:
        return list(window.model_panel.selected_component_refs())
    curve_id = _find_component_curve(window, component_id)
    return [(curve_id, component_id)] if curve_id else []


def _restore_models(window: MainWindow, states: dict[str, dict[str, Any]]) -> None:
    for curve_id, state in states.items():
        window.project.models[curve_id] = Model.from_dict(copy.deepcopy(state))


def _push_multi_model_change(
    window: MainWindow,
    text: str,
    refs: list[tuple[str, str]],
    operation: Any,
) -> None:
    curve_ids = list(dict.fromkeys(curve_id for curve_id, _ in refs))
    before = {
        curve_id: window.project.model_for(curve_id).to_dict()
        for curve_id in curve_ids
    }
    operation()
    after = {
        curve_id: window.project.model_for(curve_id).to_dict()
        for curve_id in curve_ids
    }
    _restore_models(window, before)
    if before == after:
        return
    window._push_change(
        text,
        lambda: _restore_models(window, after),
        lambda: _restore_models(window, before),
    )


def _install_model_panel() -> None:
    if getattr(ModelPanel, "_curvemole_multiselect_functions", False):
        return

    original_init = ModelPanel.__init__
    original_refresh_parameters = ModelPanel.refresh_parameters

    def init(panel: ModelPanel, *args: Any, **kwargs: Any) -> None:
        original_init(panel, *args, **kwargs)
        panel.components.setSelectionMode(panel.components.SelectionMode.ExtendedSelection)

        panel.show_all_functions = QCheckBox(panel.tr("Show all functions"))
        panel.show_all_functions.setToolTip(
            panel.tr(
                "Show model functions from every spectrum. Each row keeps its spectrum association, "
                "and Ctrl/Shift multi-selection works across spectra."
            )
        )
        panel.function_selection_summary = QLabel()
        panel.function_selection_summary.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        row = QWidget(panel)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(panel.show_all_functions)
        row_layout.addStretch(1)
        row_layout.addWidget(panel.function_selection_summary)

        single = panel.stack.widget(0)
        single.layout().insertWidget(1, row)
        panel.show_all_functions.toggled.connect(lambda *_: panel.refresh())
        panel.components.itemSelectionChanged.connect(panel._multi_selection_changed)

    def set_context(
        panel: ModelPanel,
        project: Any,
        curve_id: str | None,
        selected_count: int,
        component_id: str | None = None,
    ) -> None:
        panel.project = project
        panel.curve_id = curve_id
        # Curve selection and function selection are independent. Keep the model
        # editor available even when several spectra are selected in the curve tree.
        panel.stack.setCurrentIndex(0)
        panel.refresh(component_id)

    def refresh(panel: ModelPanel, selected_component_id: str | None = None) -> None:
        previous = set(panel.selected_component_refs())
        panel._updating = True
        try:
            panel.components.clear()
            panel.parameters.setRowCount(0)
            panel.derived.clear()
            project = panel.project
            show_all = bool(panel.show_all_functions.isChecked())

            if project is None:
                panel.title.setText(panel.tr("No active curve"))
                panel._update_function_selection_summary()
                return

            entries: list[tuple[Any, Any]] = []
            if show_all:
                for curve in project.curves:
                    model = project.model_for(curve.id)
                    entries.extend((curve, component) for component in model.components)
                panel.title.setText(
                    panel.tr("<b>All functions</b><br>")
                    + panel.tr("Every spectrum in the project")
                )
            elif panel.curve_id is not None:
                curve = project.dataset.curve(panel.curve_id)
                model = project.model_for(panel.curve_id)
                entries = [(curve, component) for component in model.components]
                panel.title.setText(f"<b>{curve.name}</b><br>{model.name}")
            else:
                panel.title.setText(panel.tr("No active curve"))
                panel._update_function_selection_summary()
                return

            preferred_row: int | None = None
            first_preserved_row: int | None = None
            for row_index, (curve, component) in enumerate(entries):
                label = component.name
                if component.is_background:
                    label += panel.tr("  ·  Background")
                if show_all:
                    label = f"{curve.name}  ›  {label}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, component.id)
                item.setData(_CURVE_ROLE, curve.id)
                item.setToolTip(
                    panel.tr("Spectrum: ")
                    + curve.name
                    + "\n"
                    + panel.tr("Function: ")
                    + component.name
                    + "\n"
                    + panel.tr("Type: ")
                    + component.function_id
                )
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked if component.enabled else Qt.CheckState.Unchecked
                )
                if component.is_background:
                    from PySide6.QtGui import QColor

                    item.setForeground(QColor("#666666"))
                panel.components.addItem(item)

                ref = (str(curve.id), str(component.id))
                if ref in previous:
                    item.setSelected(True)
                    if first_preserved_row is None:
                        first_preserved_row = row_index
                if component.id == selected_component_id:
                    preferred_row = row_index

            if first_preserved_row is not None:
                panel.components.setCurrentRow(
                    first_preserved_row,
                    QItemSelectionModel.SelectionFlag.NoUpdate,
                )
            elif preferred_row is not None:
                panel.components.setCurrentRow(preferred_row)
            elif panel.components.count():
                panel.components.setCurrentRow(0)
        finally:
            panel._updating = False

        panel._update_function_selection_summary()
        panel.refresh_parameters()

    def selected_component_refs(panel: ModelPanel) -> list[tuple[str, str]]:
        return _selected_refs(panel)

    def selected_component_ids(panel: ModelPanel) -> list[str]:
        return [component_id for _, component_id in panel.selected_component_refs()]

    def selected_component_id(panel: ModelPanel) -> str | None:
        ref = _current_ref(panel)
        return ref[1] if ref else None

    def selected_component_curve_id(panel: ModelPanel) -> str | None:
        ref = _current_ref(panel)
        return ref[0] if ref else None

    def update_summary(panel: ModelPanel) -> None:
        count = len(panel.selected_component_refs())
        if count == 0:
            text = ""
        elif count == 1:
            text = panel.tr("1 function selected")
        else:
            text = f"{count} " + panel.tr("functions selected")
        panel.function_selection_summary.setText(text)

    def multi_selection_changed(panel: ModelPanel) -> None:
        if panel._updating:
            return
        panel._update_function_selection_summary()
        panel.refresh_parameters()

    def refresh_parameters(panel: ModelPanel) -> None:
        refs = panel.selected_component_refs()
        if len(refs) <= 1:
            panel.background_toggle.blockSignals(True)
            panel.background_toggle.setTristate(False)
            panel.background_toggle.blockSignals(False)
            if refs:
                original_curve_id = panel.curve_id
                panel.curve_id = refs[0][0]
                try:
                    original_refresh_parameters(panel)
                finally:
                    panel.curve_id = original_curve_id
            else:
                original_refresh_parameters(panel)
            return

        panel._updating = True
        try:
            panel.parameters.setRowCount(0)
            panel.derived.setText(
                f"{len(refs)} "
                + panel.tr(
                    "functions selected. Delete, duplicate, move, enable/disable, background, "
                    "Lock all and Unlock all apply to the complete selection."
                )
            )
            states = []
            if panel.project is not None:
                for curve_id, component_id in refs:
                    states.append(
                        panel.project.model_for(curve_id).component(component_id).is_background
                    )
            panel.background_toggle.blockSignals(True)
            panel.background_toggle.setEnabled(bool(states))
            panel.background_toggle.setTristate(True)
            if states and all(states):
                state = Qt.CheckState.Checked
            elif states and not any(states):
                state = Qt.CheckState.Unchecked
            else:
                state = Qt.CheckState.PartiallyChecked
            panel.background_toggle.setCheckState(state)
            panel.background_toggle.blockSignals(False)
        finally:
            panel._updating = False

    def component_selected(
        panel: ModelPanel,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        if panel._updating or current is None:
            return
        panel._update_function_selection_summary()
        panel.refresh_parameters()
        ref = _item_ref(current)
        if ref is not None:
            panel.componentSelected.emit(ref[1])

    def component_enabled(panel: ModelPanel, item: QListWidgetItem) -> None:
        if panel._updating:
            return
        enabled = item.checkState() == Qt.CheckState.Checked
        refs = panel.selected_component_refs()
        ref = _item_ref(item)
        if ref is not None and len(refs) > 1 and ref in refs:
            panel.enabledRequested.emit(_BATCH, enabled)
        elif ref is not None:
            panel.enabledRequested.emit(ref[1], enabled)

    def background_toggled(panel: ModelPanel, marked: bool) -> None:
        if panel._updating:
            return
        refs = panel.selected_component_refs()
        if len(refs) > 1:
            panel.backgroundRequested.emit(_BATCH, marked)
        elif refs:
            panel.backgroundRequested.emit(refs[0][1], marked)

    def bulk_fixed(panel: ModelPanel, fixed: bool) -> None:
        refs = panel.selected_component_refs()
        if len(refs) > 1:
            panel.bulkFixedRequested.emit(_BATCH, fixed)
        elif refs:
            panel.bulkFixedRequested.emit(refs[0][1], fixed)

    def duplicate(panel: ModelPanel) -> None:
        refs = panel.selected_component_refs()
        if len(refs) > 1:
            panel.duplicateRequested.emit(_BATCH)
        elif refs:
            panel.duplicateRequested.emit(refs[0][1])

    def delete(panel: ModelPanel) -> None:
        refs = panel.selected_component_refs()
        if len(refs) > 1:
            panel.deleteRequested.emit(_BATCH)
        elif refs:
            panel.deleteRequested.emit(refs[0][1])

    def move(panel: ModelPanel, delta: int) -> None:
        refs = panel.selected_component_refs()
        if len(refs) > 1:
            panel.moveRequested.emit(_BATCH, delta)
        elif refs:
            panel.moveRequested.emit(refs[0][1], delta)

    ModelPanel.__init__ = init
    ModelPanel.set_context = set_context
    ModelPanel.refresh = refresh
    ModelPanel.selected_component_refs = selected_component_refs
    ModelPanel.selected_component_ids = selected_component_ids
    ModelPanel.selected_component_id = selected_component_id
    ModelPanel.selected_component_curve_id = selected_component_curve_id
    ModelPanel._update_function_selection_summary = update_summary
    ModelPanel._multi_selection_changed = multi_selection_changed
    ModelPanel.refresh_parameters = refresh_parameters
    ModelPanel._component_selected = component_selected
    ModelPanel._component_enabled = component_enabled
    ModelPanel._background_toggled = background_toggled
    ModelPanel._bulk_fixed = bulk_fixed
    ModelPanel._duplicate = duplicate
    ModelPanel._delete = delete
    ModelPanel._move = move
    ModelPanel._curvemole_multiselect_functions = True


def _install_main_window() -> None:
    if getattr(MainWindow, "_curvemole_multiselect_functions", False):
        return

    def set_component(window: MainWindow, component_id: str) -> None:
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

    def duplicate_component(window: MainWindow, component_id: str) -> None:
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
        _push_multi_model_change(window, text, refs, operation)
        if created:
            window.selected_component_id = created[-1]

    def delete_component(window: MainWindow, component_id: str) -> None:
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
        if (
            QMessageBox.question(window, window.tr("Delete component"), question)
            != QMessageBox.StandardButton.Yes
        ):
            return

        def operation() -> None:
            for curve_id, selected_id in refs:
                model = window.project.model_for(curve_id)
                if any(component.id == selected_id for component in model.components):
                    model.remove(selected_id)

        _push_multi_model_change(
            window,
            window.tr("Delete components") if count > 1 else window.tr("Delete component"),
            refs,
            operation,
        )
        window.selected_component_id = None

    def move_component(window: MainWindow, component_id: str, delta: int) -> None:
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
                components = window.project.model_for(curve_id).components
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

    def enable_component(window: MainWindow, component_id: str, enabled: bool) -> None:
        if not window._ensure_editable():
            return
        refs = _refs_for_request(window, component_id)
        changes = []
        for curve_id, selected_id in refs:
            component = window.project.model_for(curve_id).component(selected_id)
            if component.enabled != bool(enabled):
                changes.append((component, component.enabled, bool(enabled)))
        if not changes:
            return

        def restore(use_new: bool) -> None:
            for component, old, new in changes:
                component.enabled = new if use_new else old

        window._push_change(
            window.tr("Enable/disable components")
            if len(changes) > 1
            else window.tr("Enable/disable component"),
            lambda: restore(True),
            lambda: restore(False),
        )

    def set_component_background(window: MainWindow, component_id: str, marked: bool) -> None:
        if not window._ensure_editable():
            return
        refs = _refs_for_request(window, component_id)
        changes = []
        for curve_id, selected_id in refs:
            component = window.project.model_for(curve_id).component(selected_id)
            if component.is_background != bool(marked):
                changes.append((component, component.is_background, bool(marked)))
        if not changes:
            return

        def restore(use_new: bool) -> None:
            for component, old, new in changes:
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
        window._push_change(text, lambda: restore(True), lambda: restore(False))

    def set_component_fixed(window: MainWindow, component_id: str, fixed: bool) -> None:
        if not window._ensure_editable():
            return
        refs = _refs_for_request(window, component_id)
        changes: list[tuple[Any, dict[str, bool], dict[str, bool]]] = []
        for curve_id, selected_id in refs:
            component = window.project.model_for(curve_id).component(selected_id)
            before = {
                name: parameter.fixed
                for name, parameter in component.parameters.items()
            }
            after = {name: bool(fixed) for name in component.parameters}
            if before != after:
                changes.append((component, before, after))
        if not changes:
            return

        def restore(which: int) -> None:
            for component, before, after in changes:
                values = after if which else before
                for name, value in values.items():
                    component.parameters[name].fixed = value

        text = (
            window.tr("Lock all parameters in selected functions")
            if fixed
            else window.tr("Unlock all parameters in selected functions")
        )
        window._push_change(text, lambda: restore(1), lambda: restore(0))

    def change_parameter(
        window: MainWindow,
        component_id: str,
        name: str,
        field: str,
        value: Any,
    ) -> None:
        curve_id = _find_component_curve(window, component_id)
        if curve_id is None:
            return
        parameter = window.project.model_for(curve_id).component(component_id).parameters[name]
        old = getattr(parameter, field)
        try:
            setattr(parameter, field, value)
            parameter.validate()
            window._validate_all_links()
            setattr(parameter, field, old)
        except Exception as exc:
            setattr(parameter, field, old)
            window._show_error(window.tr("Parameter constraint"), exc)
            window.model_panel.refresh_parameters()
            return
        window._push_change(
            window.tr("Edit parameter"),
            lambda: setattr(parameter, field, value),
            lambda: setattr(parameter, field, old),
        )

    def edit_parameter_link(window: MainWindow, component_id: str, name: str) -> None:
        curve_id = _find_component_curve(window, component_id)
        if curve_id is None:
            return
        parameter = window.project.model_for(curve_id).component(component_id).parameters[name]
        dialog = ParameterLinkDialog(
            window.project,
            curve_id,
            component_id,
            name,
            parameter.link,
            window,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        window.change_parameter(component_id, name, "link", dialog.selected_link())

    MainWindow._set_component = set_component
    MainWindow.duplicate_component = duplicate_component
    MainWindow.delete_component = delete_component
    MainWindow.move_component = move_component
    MainWindow.enable_component = enable_component
    MainWindow.set_component_background = set_component_background
    MainWindow.set_component_fixed = set_component_fixed
    MainWindow.change_parameter = change_parameter
    MainWindow.edit_parameter_link = edit_parameter_link
    MainWindow._curvemole_multiselect_functions = True


def install_model_multiselect_support() -> None:
    """Install function multi-selection and project-wide function browsing."""
    _install_model_panel()
    _install_main_window()


install_model_multiselect_support()
