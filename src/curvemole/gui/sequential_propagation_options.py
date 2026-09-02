"""Advanced model-propagation controls for sequential refinement."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from curvemole.core.fitting import FitMode
from curvemole.core.sequential_fit import SequentialFitPlan
from curvemole.gui.dialogs import FitPlanDialog


def _ignored_component_ids(dialog: FitPlanDialog) -> tuple[str, ...]:
    result: list[str] = []
    widget = getattr(dialog, "sequential_ignored_functions", None)
    if widget is None:
        return ()
    for row in range(widget.count()):
        item = widget.item(row)
        if item.checkState() == Qt.CheckState.Checked:
            value = item.data(Qt.ItemDataRole.UserRole)
            if value is not None:
                result.append(str(value))
    return tuple(result)


def _refresh_ignored_functions(dialog: FitPlanDialog) -> None:
    widget = getattr(dialog, "sequential_ignored_functions", None)
    source = getattr(dialog, "sequential_source", None)
    if widget is None or source is None:
        return
    widget.clear()
    source_id = str(source.currentData() or "")
    if not source_id:
        return
    try:
        model = dialog.project.model_for(source_id)
    except (KeyError, AttributeError):
        return
    for component in model.components:
        item = QListWidgetItem(f"{component.name}  ({component.function_id})")
        item.setData(Qt.ItemDataRole.UserRole, component.id)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked)
        item.setToolTip(
            dialog.tr(
                "Check this function to ignore its parameter changes when deciding whether the "
                "sequential refinement should pause. The function is still copied and fitted normally."
            )
        )
        widget.addItem(item)


def _save_settings(dialog: FitPlanDialog) -> None:
    settings = QSettings("CurveMole", "CurveMole")
    for name in (
        "bounds",
        "fixed",
        "links",
        "background",
        "enabled",
        "composition",
    ):
        control = getattr(dialog, f"sequential_propagate_{name}", None)
        if control is not None:
            settings.setValue(f"sequential/propagate_{name}", control.isChecked())


def _install_sequential_propagation_options() -> None:
    if getattr(FitPlanDialog, "_curvemole_sequential_propagation_options", False):
        return

    original_init = FitPlanDialog.__init__
    original_plan = FitPlanDialog.plan
    original_update = FitPlanDialog._update_sequential_controls

    def init(dialog: FitPlanDialog, *args: Any, **kwargs: Any) -> None:
        original_init(dialog, *args, **kwargs)
        settings = QSettings("CurveMole", "CurveMole")

        dialog.sequential_propagation_options = QGroupBox(
            dialog.tr("Model propagation options")
        )
        layout = QVBoxLayout(dialog.sequential_propagation_options)
        intro = QLabel(
            dialog.tr(
                "Parameter values and the function structure are always copied from the current "
                "source spectrum. Choose which additional fit constraints and component states "
                "should also be propagated to the next spectrum."
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        definitions = (
            (
                "bounds",
                dialog.tr("Preserve parameter bounds"),
                dialog.tr("Copy lower and upper parameter limits from the source spectrum."),
            ),
            (
                "fixed",
                dialog.tr("Preserve fixed/free state"),
                dialog.tr("Keep parameters fixed or free exactly as in the source spectrum."),
            ),
            (
                "links",
                dialog.tr("Preserve parameter links / relations"),
                dialog.tr(
                    "Copy parameter relations. Links internal to the source spectrum are remapped "
                    "to the corresponding parameters of the target spectrum."
                ),
            ),
            (
                "background",
                dialog.tr("Preserve background tags"),
                dialog.tr("Keep functions marked as background in the propagated model."),
            ),
            (
                "enabled",
                dialog.tr("Preserve enabled / disabled state"),
                dialog.tr("Keep disabled functions disabled in the propagated model."),
            ),
            (
                "composition",
                dialog.tr("Preserve composition and grouping"),
                dialog.tr("Keep add/subtract/multiply/divide/convolve composition and group state."),
            ),
        )
        for name, text, tooltip in definitions:
            control = QCheckBox(text)
            control.setToolTip(tooltip)
            control.setChecked(
                settings.value(f"sequential/propagate_{name}", True, type=bool)
            )
            setattr(dialog, f"sequential_propagate_{name}", control)
            layout.addWidget(control)

        structural = QLabel(
            dialog.tr(
                "Function metadata required to define the function itself (for example spline nodes "
                "or custom-function metadata) is always retained."
            )
        )
        structural.setWordWrap(True)
        layout.addWidget(structural)

        ignore_title = QLabel(
            dialog.tr(
                "Functions ignored by the parameter-change pause trigger "
                "(check one or more to ignore)"
            )
        )
        ignore_title.setWordWrap(True)
        layout.addWidget(ignore_title)
        dialog.sequential_ignored_functions = QListWidget()
        dialog.sequential_ignored_functions.setMinimumHeight(90)
        dialog.sequential_ignored_functions.setToolTip(
            dialog.tr(
                "Checked functions are still copied and fitted, but large changes in their "
                "parameters will not pause the sequence. Residual-based monitoring remains active."
            )
        )
        layout.addWidget(dialog.sequential_ignored_functions)

        note = QLabel(
            dialog.tr(
                "Ignored functions affect only the parameter-jump monitor. They still contribute "
                "to the total residual, so a strong deterioration of the overall fit can still pause the sequence."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        parent_layout = dialog.sequential_box.layout()
        parent_layout.insertWidget(
            max(1, parent_layout.count() - 1),
            dialog.sequential_propagation_options,
        )
        dialog.sequential_source.currentIndexChanged.connect(
            lambda *_: _refresh_ignored_functions(dialog)
        )
        dialog.accepted.connect(lambda: _save_settings(dialog))
        _refresh_ignored_functions(dialog)
        dialog._update_sequential_controls()

    def plan(dialog: FitPlanDialog) -> Any:
        result = original_plan(dialog)
        if not isinstance(result, SequentialFitPlan):
            return result
        result.propagate_bounds = dialog.sequential_propagate_bounds.isChecked()
        result.propagate_fixed = dialog.sequential_propagate_fixed.isChecked()
        result.propagate_links = dialog.sequential_propagate_links.isChecked()
        result.propagate_background = dialog.sequential_propagate_background.isChecked()
        result.propagate_enabled = dialog.sequential_propagate_enabled.isChecked()
        result.propagate_composition = dialog.sequential_propagate_composition.isChecked()
        result.ignored_component_ids = _ignored_component_ids(dialog)
        return result

    def update_controls(dialog: FitPlanDialog) -> None:
        original_update(dialog)
        options = getattr(dialog, "sequential_propagation_options", None)
        if options is None:
            return
        sequential = dialog.mode.currentData() == FitMode.SEQUENTIAL
        options.setEnabled(sequential)
        ignored = getattr(dialog, "sequential_ignored_functions", None)
        if ignored is not None:
            ignored.setEnabled(
                sequential and dialog.sequential_monitor_parameters.isChecked()
            )

    FitPlanDialog.__init__ = init
    FitPlanDialog.plan = plan
    FitPlanDialog._update_sequential_controls = update_controls
    FitPlanDialog._curvemole_sequential_propagation_options = True


_install_sequential_propagation_options()
