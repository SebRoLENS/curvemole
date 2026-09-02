"""Copy one parameter from a selected model function to other selected functions."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from curvemole.core.models import Model
from curvemole.gui.main_window import MainWindow
from curvemole.gui.model_multiselect import _current_ref
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
    parameter_name: str,
    *,
    copy_fixed: bool = False,
    copy_bounds: bool = False,
    copy_link: bool = False,
) -> ParameterCopyResult:
    """Copy one named parameter to compatible targets as one undoable edit.

    The numerical value is always copied exactly. Optional constraint fields are
    copied independently. Fit-derived uncertainties are cleared on changed target
    parameters because they no longer describe the edited model state.
    """
    if not window._ensure_editable():
        return ParameterCopyResult(0, [], [])

    source_curve_id, source_component_id = source_ref
    source_component = window.project.model_for(source_curve_id).component(source_component_id)
    if parameter_name not in source_component.parameters:
        raise KeyError(parameter_name)
    source = source_component.parameters[parameter_name]

    unique_targets = [ref for ref in dict.fromkeys(target_refs) if ref != source_ref]
    compatible: list[tuple[str, str]] = []
    missing: list[tuple[str, str]] = []
    incompatible_bounds: list[tuple[str, str]] = []

    for curve_id, component_id in unique_targets:
        component = window.project.model_for(curve_id).component(component_id)
        target = component.parameters.get(parameter_name)
        if target is None:
            missing.append((curve_id, component_id))
            continue
        if not copy_bounds and not target.minimum <= source.value <= target.maximum:
            incompatible_bounds.append((curve_id, component_id))
            continue
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
            target = window.project.model_for(curve_id).component(component_id).parameters[parameter_name]
            if copy_bounds:
                target.minimum = source.minimum
                target.maximum = source.maximum
            target.value = source.value
            if copy_fixed:
                target.fixed = source.fixed
            if copy_link:
                target.link = source.link
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
        window.tr("Copy parameter to selected functions"),
        lambda: _restore_models(window, after),
        lambda: _restore_models(window, before),
    )
    return ParameterCopyResult(len(compatible), missing, incompatible_bounds)


class CopyParameterDialog(QDialog):
    def __init__(
        self,
        window: MainWindow,
        refs: list[tuple[str, str]],
        current_ref: tuple[str, str] | None,
        current_parameter: str | None = None,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.refs = list(refs)
        self.setWindowTitle(self.tr("Copy parameter to selected functions"))
        self.resize(600, 520)

        layout = QVBoxLayout(self)
        intro = QLabel(
            self.tr(
                "Copy one parameter from one source function to the selected target functions. "
                "Follow the four numbered steps below."
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.source = QComboBox()
        for ref in self.refs:
            self.source.addItem(_component_label(window, ref), ref)
        if current_ref in self.refs:
            self.source.setCurrentIndex(self.refs.index(current_ref))
        self.parameter = QComboBox()
        form.addRow(self.tr("1. Source function"), self.source)
        form.addRow(self.tr("2. Parameter to copy"), self.parameter)
        layout.addLayout(form)

        targets_label = QLabel(self.tr("3. Target functions — uncheck any function you do not want to modify"))
        targets_label.setWordWrap(True)
        layout.addWidget(targets_label)
        self.targets = QListWidget()
        self.targets.setMinimumHeight(120)
        layout.addWidget(self.targets)

        options_label = QLabel(self.tr("4. Choose what is copied"))
        layout.addWidget(options_label)
        value_note = QLabel(self.tr("✓ Numerical value (always copied)"))
        layout.addWidget(value_note)
        self.copy_fixed = QCheckBox(self.tr("Also copy fixed/free state"))
        self.copy_bounds = QCheckBox(self.tr("Also copy lower and upper bounds"))
        self.copy_link = QCheckBox(self.tr("Also copy link / relation"))
        self.copy_fixed.setChecked(False)
        self.copy_bounds.setChecked(False)
        self.copy_link.setChecked(False)
        layout.addWidget(self.copy_fixed)
        layout.addWidget(self.copy_bounds)
        layout.addWidget(self.copy_link)

        note = QLabel(
            self.tr(
                "Value-only mode preserves each target's existing constraints and relations. "
                "Targets without the chosen parameter are skipped. If the source value lies outside "
                "a target's existing bounds, that target is skipped unless bounds are also copied."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.copy_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.copy_button.setText(self.tr("Copy parameter"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.source.currentIndexChanged.connect(self._source_changed)
        self.parameter.currentIndexChanged.connect(self._refresh_summary)
        self.copy_bounds.toggled.connect(self._refresh_summary)
        self.targets.itemChanged.connect(lambda *_: self._refresh_summary())
        self._refresh_parameters()
        if current_parameter:
            index = self.parameter.findData(current_parameter)
            if index >= 0:
                self.parameter.setCurrentIndex(index)
        self._refresh_targets()
        self._refresh_summary()

    def source_ref(self) -> tuple[str, str]:
        value = self.source.currentData()
        return str(value[0]), str(value[1])

    def parameter_name(self) -> str:
        return str(self.parameter.currentData())

    def target_refs(self) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for row in range(self.targets.count()):
            item = self.targets.item(row)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            value = item.data(Qt.ItemDataRole.UserRole)
            if value is not None:
                result.append((str(value[0]), str(value[1])))
        return result

    def _source_changed(self) -> None:
        self._refresh_parameters()
        self._refresh_targets()
        self._refresh_summary()

    def _refresh_parameters(self) -> None:
        previous = self.parameter.currentData()
        self.parameter.clear()
        if not self.refs:
            return
        curve_id, component_id = self.source_ref()
        component = self.window.project.model_for(curve_id).component(component_id)
        for name in component.parameters:
            self.parameter.addItem(name, name)
        if previous is not None:
            index = self.parameter.findData(previous)
            if index >= 0:
                self.parameter.setCurrentIndex(index)

    def _refresh_targets(self) -> None:
        self.targets.blockSignals(True)
        try:
            self.targets.clear()
            source = self.source_ref()
            for ref in self.refs:
                if ref == source:
                    continue
                item = QListWidgetItem(_component_label(self.window, ref))
                item.setData(Qt.ItemDataRole.UserRole, ref)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                self.targets.addItem(item)
        finally:
            self.targets.blockSignals(False)

    def _refresh_summary(self) -> None:
        if self.parameter.count() == 0:
            self.summary.clear()
            self.copy_button.setEnabled(False)
            return
        name = self.parameter_name()
        source_curve_id, source_component_id = self.source_ref()
        value = self.window.project.model_for(source_curve_id).component(source_component_id).parameters[name].value
        compatible = 0
        missing = 0
        bound_conflicts = 0
        targets = self.target_refs()
        for curve_id, component_id in targets:
            component = self.window.project.model_for(curve_id).component(component_id)
            target = component.parameters.get(name)
            if target is None:
                missing += 1
            elif not self.copy_bounds.isChecked() and not target.minimum <= value <= target.maximum:
                bound_conflicts += 1
            else:
                compatible += 1
        parts = [f"{compatible} " + self.tr("compatible target(s)")]
        if missing:
            parts.append(f"{missing} " + self.tr("without this parameter"))
        if bound_conflicts:
            parts.append(f"{bound_conflicts} " + self.tr("outside existing bounds"))
        self.summary.setText(" · ".join(parts))
        self.copy_button.setEnabled(bool(targets))
        self.copy_button.setText(
            self.tr("Copy '") + name + self.tr("' to ") + str(len(targets)) + self.tr(" target(s)")
        )


def _show_copy_result(window: MainWindow, result: ParameterCopyResult, parameter_name: str) -> None:
    message = (
        window.tr("Copied parameter '")
        + parameter_name
        + window.tr("' to ")
        + str(result.copied)
        + window.tr(" selected function(s).")
    )
    skipped = len(result.missing_parameter) + len(result.incompatible_bounds)
    if skipped:
        message += "\n\n" + window.tr("Skipped: ")
        details = []
        if result.missing_parameter:
            details.append(
                str(len(result.missing_parameter)) + " " + window.tr("without that parameter")
            )
        if result.incompatible_bounds:
            details.append(
                str(len(result.incompatible_bounds))
                + " "
                + window.tr("because the value is outside existing bounds")
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
                "3) Ctrl/Shift-select the target functions; 4) press this button. The value is copied "
                "by default; fixed state, bounds and relations are optional."
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
        panel._update_copy_parameter_button()

    def update_button(panel: ModelPanel) -> None:
        button = getattr(panel, "copy_parameter_button", None)
        if button is None:
            return
        refs = panel.selected_component_refs()
        source_ref = getattr(panel, "_parameter_copy_source_ref", None)
        parameter_name = getattr(panel, "_parameter_copy_parameter_name", None)
        if len(refs) < 2:
            button.setEnabled(False)
            if parameter_name and source_ref in refs:
                button.setText(
                    panel.tr("Parameter '")
                    + parameter_name
                    + panel.tr("' selected — Ctrl/Shift-select target functions")
                )
            else:
                button.setText(panel.tr("Select a parameter, then select target functions"))
            return

        button.setEnabled(True)
        if source_ref in refs and parameter_name:
            targets = len(refs) - 1
            button.setText(
                panel.tr("Copy '")
                + parameter_name
                + panel.tr("' to ")
                + str(targets)
                + panel.tr(" selected function(s)…")
            )
        else:
            button.setText(panel.tr("Choose source parameter and copy to selected functions…"))

    def copy_selected(panel: ModelPanel) -> None:
        refs = panel.selected_component_refs()
        if len(refs) < 2:
            QMessageBox.information(
                panel,
                panel.tr("Copy parameter"),
                panel.tr(
                    "First select the source function and parameter, then Ctrl/Shift-select at least one target function."
                ),
            )
            return
        window = panel.window()
        if not isinstance(window, MainWindow):
            return
        remembered_source = getattr(panel, "_parameter_copy_source_ref", None)
        remembered_parameter = getattr(panel, "_parameter_copy_parameter_name", None)
        source_hint = remembered_source if remembered_source in refs else _current_ref(panel)
        parameter_hint = remembered_parameter if source_hint == remembered_source else None
        dialog = CopyParameterDialog(window, refs, source_hint, parameter_hint)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            result = copy_parameter_to_refs(
                window,
                dialog.source_ref(),
                dialog.target_refs(),
                dialog.parameter_name(),
                copy_fixed=dialog.copy_fixed.isChecked(),
                copy_bounds=dialog.copy_bounds.isChecked(),
                copy_link=dialog.copy_link.isChecked(),
            )
        except Exception as exc:
            window._show_error(window.tr("Copy parameter"), exc)
            return
        _show_copy_result(window, result, dialog.parameter_name())

    ModelPanel.__init__ = init
    ModelPanel._remember_parameter_copy_source = remember_source
    ModelPanel._update_copy_parameter_button = update_button
    ModelPanel._copy_parameter_to_selected = copy_selected
    ModelPanel._curvemole_parameter_copy = True


_install_parameter_copy()
