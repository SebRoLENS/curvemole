"""Copy one parameter from a selected model function to other selected functions."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
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
    ) -> None:
        super().__init__(window)
        self.window = window
        self.refs = list(refs)
        self.setWindowTitle(self.tr("Copy parameter to selected functions"))
        self.resize(520, 300)

        layout = QVBoxLayout(self)
        intro = QLabel(
            self.tr(
                "Choose the source function and parameter. The numerical value is always copied "
                "to the other selected functions that contain a parameter with the same name."
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
        self.source.currentIndexChanged.connect(self._refresh_parameters)
        form.addRow(self.tr("Source function"), self.source)
        form.addRow(self.tr("Parameter"), self.parameter)
        layout.addLayout(form)

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
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.tr("Copy"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.parameter.currentIndexChanged.connect(self._refresh_summary)
        self.copy_bounds.toggled.connect(self._refresh_summary)
        self._refresh_parameters()

    def source_ref(self) -> tuple[str, str]:
        value = self.source.currentData()
        return str(value[0]), str(value[1])

    def parameter_name(self) -> str:
        return str(self.parameter.currentData())

    def target_refs(self) -> list[tuple[str, str]]:
        source = self.source_ref()
        return [ref for ref in self.refs if ref != source]

    def _refresh_parameters(self) -> None:
        self.parameter.clear()
        if not self.refs:
            return
        curve_id, component_id = self.source_ref()
        component = self.window.project.model_for(curve_id).component(component_id)
        for name in component.parameters:
            self.parameter.addItem(name, name)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        if self.parameter.count() == 0:
            self.summary.clear()
            return
        name = self.parameter_name()
        source_curve_id, source_component_id = self.source_ref()
        value = self.window.project.model_for(source_curve_id).component(source_component_id).parameters[name].value
        compatible = 0
        missing = 0
        bound_conflicts = 0
        for curve_id, component_id in self.target_refs():
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
        panel.copy_parameter_button = QPushButton(panel.tr("Copy parameter to selected…"))
        panel.copy_parameter_button.setToolTip(
            panel.tr(
                "Copy one parameter from a source function to all other selected functions. "
                "The value is copied by default; fixed state, bounds and relations are optional."
            )
        )
        single = panel.stack.widget(0)
        index = single.layout().indexOf(panel.parameters)
        single.layout().insertWidget(index, panel.copy_parameter_button)
        panel.copy_parameter_button.clicked.connect(panel._copy_parameter_to_selected)
        panel.components.itemSelectionChanged.connect(panel._update_copy_parameter_button)
        panel._update_copy_parameter_button()

    def update_button(panel: ModelPanel) -> None:
        button = getattr(panel, "copy_parameter_button", None)
        if button is not None:
            button.setEnabled(len(panel.selected_component_refs()) >= 2)

    def copy_selected(panel: ModelPanel) -> None:
        refs = panel.selected_component_refs()
        if len(refs) < 2:
            QMessageBox.information(
                panel,
                panel.tr("Copy parameter"),
                panel.tr("Select at least two functions first."),
            )
            return
        window = panel.window()
        if not isinstance(window, MainWindow):
            return
        dialog = CopyParameterDialog(window, refs, _current_ref(panel))
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
    ModelPanel._update_copy_parameter_button = update_button
    ModelPanel._copy_parameter_to_selected = copy_selected
    ModelPanel._curvemole_parameter_copy = True


_install_parameter_copy()
