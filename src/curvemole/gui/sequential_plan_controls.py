"""Sequential-propagation controls of the Fit dialog.

Builds and reads the "Sequential propagation" and "Model propagation options"
groups of FitPlanDialog. FitPlanDialog calls these functions itself; they used
to be installed by replacing its methods from two separate modules.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
)

from curvemole.core.fitting import FitMode
from curvemole.core.sequential_fit import SequentialFitPlan
from curvemole.gui.app_settings import settings_for


def _checked_curve_ids(dialog: Any) -> list[str]:
    result: list[str] = []
    for row in range(dialog.curves.rowCount()):
        item = dialog.curves.item(row, 0)
        if not dialog.curves.isRowHidden(row) and item.data(Qt.ItemDataRole.UserRole) and item.checkState() == Qt.CheckState.Checked:
            result.append(str(item.data(Qt.ItemDataRole.UserRole)))
    return result


def _ignored_component_ids(dialog: Any, widget_name: str = "sequential_ignored_functions") -> tuple[str, ...]:
    result: list[str] = []
    widget = getattr(dialog, widget_name, None)
    if widget is None:
        return ()
    for row in range(widget.count()):
        item = widget.item(row)
        if item.checkState() == Qt.CheckState.Checked:
            value = item.data(Qt.ItemDataRole.UserRole)
            if value is not None:
                result.append(str(value))
    return tuple(result)


def _refresh_ignored_functions(dialog: Any) -> None:
    widget = getattr(dialog, "sequential_ignored_functions", None)
    source = getattr(dialog, "sequential_source", None)
    if widget is None or source is None:
        return
    widget.clear()
    excluded_widget = getattr(dialog, "sequential_excluded_copy_functions", None)
    if excluded_widget is not None:
        excluded_widget.clear()
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
                "sequential refinement should pause. Copy exclusions are configured separately."
            )
        )
        widget.addItem(item)
        if excluded_widget is not None:
            excluded = QListWidgetItem(f"{component.name}  ({component.function_id})")
            excluded.setData(Qt.ItemDataRole.UserRole, component.id)
            excluded.setFlags(excluded.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            excluded.setCheckState(
                Qt.CheckState.Checked if component.is_background else Qt.CheckState.Unchecked
            )
            excluded.setToolTip(dialog.tr(
                "Checked: do not copy this function to subsequent spectra. "
                "Background functions are excluded by default; uncheck to include one. "
                "Functions already present on each target are retained."
            ))
            excluded_widget.addItem(excluded)


def _save_settings(dialog: Any) -> None:
    settings = settings_for(dialog)
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


def build_sequential_controls(dialog: Any) -> None:
    """Sequential-propagation source, monitors and thresholds."""
    settings = settings_for(dialog)

    dialog.sequential_box = QGroupBox(dialog.tr("Sequential propagation"))
    box_layout = QVBoxLayout(dialog.sequential_box)
    explanation = QLabel(
        dialog.tr(
            "The initial spectrum is the approved source and is not re-fitted. Selected "
            "functions are added to the next spectrum without overwriting existing functions, fitted there, then that result "
            "becomes the source for the following spectrum. Checked spectra before the source "
            "are not part of the sequence."
        )
    )
    explanation.setWordWrap(True)
    box_layout.addWidget(explanation)

    form = QFormLayout()
    dialog.sequential_source = QComboBox()
    def refresh_sources():
        from curvemole.gui.series_groups import style_heading

        combo = dialog.sequential_source
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for series in dialog.project.dataset.series:
            if not dialog.all_series.isChecked() and series.id != dialog.scope_series_id:
                continue
            combo.addItem(series.name)
            style_heading(combo.model().item(combo.count() - 1), combo)
            for curve in series.curves:
                combo.addItem("    " + curve.name, curve.id)
        index = combo.findData(previous) if previous else -1
        if index < 0:
            index = next((i for i in range(combo.count()) if combo.itemData(i)), -1)
        combo.setCurrentIndex(index)
        combo.blockSignals(False)
        if previous != combo.currentData():
            combo.currentIndexChanged.emit(index)

    dialog._refresh_sources = refresh_sources
    refresh_sources()
    selected = _checked_curve_ids(dialog)
    if selected:
        index = dialog.sequential_source.findData(selected[0])
        dialog.sequential_source.setCurrentIndex(max(0, index))
    form.addRow(dialog.tr("Initial source spectrum"), dialog.sequential_source)

    dialog.sequential_monitor_residuals = QCheckBox(
        dialog.tr("Pause when normalized residuals worsen strongly")
    )
    dialog.sequential_monitor_residuals.setChecked(
        settings.value("sequential/monitor_residuals", True, type=bool)
    )
    dialog.sequential_residual_ratio = QDoubleSpinBox()
    dialog.sequential_residual_ratio.setRange(1.01, 1000.0)
    dialog.sequential_residual_ratio.setDecimals(2)
    dialog.sequential_residual_ratio.setSingleStep(0.25)
    dialog.sequential_residual_ratio.setValue(
        float(settings.value("sequential/residual_ratio", 2.5))
    )
    dialog.sequential_residual_delta = QDoubleSpinBox()
    dialog.sequential_residual_delta.setRange(0.0, 100.0)
    dialog.sequential_residual_delta.setDecimals(2)
    dialog.sequential_residual_delta.setSuffix(" %")
    dialog.sequential_residual_delta.setValue(
        float(settings.value("sequential/residual_delta_percent", 2.0))
    )
    form.addRow("", dialog.sequential_monitor_residuals)
    form.addRow(dialog.tr("Residual worsening factor"), dialog.sequential_residual_ratio)
    form.addRow(
        dialog.tr("Minimum normalized RMSE increase"),
        dialog.sequential_residual_delta,
    )

    dialog.sequential_monitor_parameters = QCheckBox(
        dialog.tr("Pause when a free parameter changes strongly")
    )
    dialog.sequential_monitor_parameters.setChecked(
        settings.value("sequential/monitor_parameters", True, type=bool)
    )
    dialog.sequential_parameter_change = QDoubleSpinBox()
    dialog.sequential_parameter_change.setRange(1.0, 1000.0)
    dialog.sequential_parameter_change.setDecimals(1)
    dialog.sequential_parameter_change.setSuffix(" %")
    dialog.sequential_parameter_change.setValue(
        float(settings.value("sequential/parameter_change_percent", 75.0))
    )
    form.addRow("", dialog.sequential_monitor_parameters)
    form.addRow(
        dialog.tr("Maximum normalized parameter change"),
        dialog.sequential_parameter_change,
    )
    box_layout.addLayout(form)

    defaults = QLabel(
        dialog.tr(
            "Initial defaults are intentionally conservative: residual RMSE must worsen by "
            "2.5× and by at least 2% of the signal scale, or a free parameter must jump by "
            "about 75% on its normalized scale. Disable either monitor if it is unsuitable "
            "for a particular series."
        )
    )
    defaults.setWordWrap(True)
    box_layout.addWidget(defaults)

    layout = dialog.layout()
    layout.insertWidget(max(0, layout.count() - 2), dialog.sequential_box)

    dialog.mode.currentIndexChanged.connect(dialog._update_sequential_controls)
    dialog.sequential_source.currentIndexChanged.connect(dialog._sequential_source_changed)
    dialog.sequential_monitor_residuals.toggled.connect(dialog._update_sequential_controls)
    dialog.sequential_monitor_parameters.toggled.connect(dialog._update_sequential_controls)
    dialog._update_sequential_controls()


def sequential_source_changed(dialog: Any) -> None:
    if dialog.mode.currentData() != FitMode.SEQUENTIAL:
        return
    source_id = str(dialog.sequential_source.currentData())
    found_source = False
    for row in range(dialog.curves.rowCount()):
        item = dialog.curves.item(row, 0)
        if dialog.curves.isRowHidden(row) or not item.data(Qt.ItemDataRole.UserRole):
            continue
        curve_id = str(item.data(Qt.ItemDataRole.UserRole))
        if curve_id == source_id:
            found_source = True
            item.setCheckState(Qt.CheckState.Checked)
        elif not found_source:
            item.setCheckState(Qt.CheckState.Unchecked)


def update_sequential_controls(dialog: Any) -> None:
    sequential = dialog.mode.currentData() == FitMode.SEQUENTIAL
    dialog.sequential_box.setVisible(sequential)
    if sequential and len(_checked_curve_ids(dialog)) < 2:
        source_id = str(dialog.sequential_source.currentData())
        include = False
        for row in range(dialog.curves.rowCount()):
            item = dialog.curves.item(row, 0)
            if dialog.curves.isRowHidden(row) or not item.data(Qt.ItemDataRole.UserRole):
                continue
            if str(item.data(Qt.ItemDataRole.UserRole)) == source_id:
                include = True
            if include:
                item.setCheckState(Qt.CheckState.Checked)
    residual_enabled = sequential and dialog.sequential_monitor_residuals.isChecked()
    dialog.sequential_residual_ratio.setEnabled(residual_enabled)
    dialog.sequential_residual_delta.setEnabled(residual_enabled)
    parameter_enabled = sequential and dialog.sequential_monitor_parameters.isChecked()
    dialog.sequential_parameter_change.setEnabled(parameter_enabled)


def sequential_plan(dialog: Any, base: Any) -> Any:
    if base.mode != FitMode.SEQUENTIAL:
        return base

    source_id = str(dialog.sequential_source.currentData())
    ordered_selected = [
        curve.id for curve in dialog.project.curves if curve.id in set(base.curve_ids)
    ]
    if source_id in ordered_selected:
        start = ordered_selected.index(source_id)
        ordered_selected = ordered_selected[start:]
    else:
        ordered_selected = []
    weights = {
        curve_id: base.spectrum_weights.get(curve_id, 1.0)
        for curve_id in ordered_selected
    }
    return SequentialFitPlan(
        curve_ids=ordered_selected,
        mode=FitMode.SEQUENTIAL,
        settings=base.settings,
        spectrum_weights=weights,
        equal_contribution=base.equal_contribution,
        monitor_residuals=dialog.sequential_monitor_residuals.isChecked(),
        residual_ratio_limit=dialog.sequential_residual_ratio.value(),
        residual_nrmse_delta=dialog.sequential_residual_delta.value() / 100.0,
        monitor_parameters=dialog.sequential_monitor_parameters.isChecked(),
        parameter_change_limit=dialog.sequential_parameter_change.value() / 100.0,
    )


def sequential_accept_check(dialog: Any) -> bool:
    """Validate a sequential plan and remember its settings; False keeps the dialog open."""
    try:
        candidate = dialog.plan()
        if candidate.mode == FitMode.SEQUENTIAL:
            if len(candidate.curve_ids) < 2:
                raise ValueError(
                    dialog.tr(
                        "Sequential propagation needs an initial source spectrum and at least "
                        "one subsequent spectrum."
                    )
                )
            source_model = dialog.project.model_for(candidate.curve_ids[0])
            if not source_model.components:
                raise ValueError(
                    dialog.tr(
                        "The initial source spectrum has no model functions. Prepare its fit "
                        "first; subsequent spectra do not need functions in advance."
                    )
                )
            candidate.validate()
    except Exception as exc:
        QMessageBox.warning(dialog, dialog.tr("Fit plan"), str(exc))
        return False

    if candidate.mode == FitMode.SEQUENTIAL:
        settings = settings_for(dialog)
        settings.setValue(
            "sequential/monitor_residuals",
            dialog.sequential_monitor_residuals.isChecked(),
        )
        settings.setValue(
            "sequential/residual_ratio",
            dialog.sequential_residual_ratio.value(),
        )
        settings.setValue(
            "sequential/residual_delta_percent",
            dialog.sequential_residual_delta.value(),
        )
        settings.setValue(
            "sequential/monitor_parameters",
            dialog.sequential_monitor_parameters.isChecked(),
        )
        settings.setValue(
            "sequential/parameter_change_percent",
            dialog.sequential_parameter_change.value(),
        )
    return True


def build_propagation_controls(dialog: Any) -> None:
    """Which constraints and functions accompany propagated models."""
    settings = settings_for(dialog)

    dialog.sequential_propagation_options = QGroupBox(
        dialog.tr("Model propagation options")
    )
    layout = QVBoxLayout(dialog.sequential_propagation_options)
    intro = QLabel(
        dialog.tr(
            "Selected source functions are added to the next spectrum. Existing target functions "
            "are never overwritten by copying and retain their fixed/free state for fitting. "
            "Choose which constraints and states accompany newly copied functions."
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

    copy_title = QLabel(dialog.tr("Functions excluded from copying (check to exclude)"))
    copy_title.setWordWrap(True)
    layout.addWidget(copy_title)
    dialog.sequential_excluded_copy_functions = QListWidget()
    dialog.sequential_excluded_copy_functions.setMinimumHeight(90)
    dialog.sequential_excluded_copy_functions.setToolTip(dialog.tr(
        "Checked functions are not copied. All functions already on each target are kept. "
        "This choice is independent of the parameter-change pause monitor."
    ))
    layout.addWidget(dialog.sequential_excluded_copy_functions)

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
            "Large changes in checked functions will not pause the sequence. This does not "
            "change which functions are copied. Residual-based monitoring remains active."
        )
    )
    layout.addWidget(dialog.sequential_ignored_functions)

    note = QLabel(
        dialog.tr(
            "The residual monitor evaluates the complete target model, including retained local functions. "
            "A strong deterioration of the overall fit can still pause the sequence."
        )
    )
    note.setWordWrap(True)
    layout.addWidget(note)

    parent_layout = dialog.sequential_box.layout()
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(dialog.sequential_propagation_options)
    scroll.setMinimumHeight(200)
    scroll.setMaximumHeight(350)
    parent_layout.insertWidget(
        max(1, parent_layout.count() - 1),
        scroll,
    )
    dialog.sequential_source.currentIndexChanged.connect(
        lambda *_: _refresh_ignored_functions(dialog)
    )
    dialog.accepted.connect(lambda: _save_settings(dialog))
    _refresh_ignored_functions(dialog)
    dialog._update_sequential_controls()


def propagation_plan(dialog: Any, result: Any) -> Any:
    if not isinstance(result, SequentialFitPlan):
        return result
    result.propagate_bounds = dialog.sequential_propagate_bounds.isChecked()
    result.propagate_fixed = dialog.sequential_propagate_fixed.isChecked()
    result.propagate_links = dialog.sequential_propagate_links.isChecked()
    result.propagate_background = dialog.sequential_propagate_background.isChecked()
    result.propagate_enabled = dialog.sequential_propagate_enabled.isChecked()
    result.propagate_composition = dialog.sequential_propagate_composition.isChecked()
    result.ignored_component_ids = _ignored_component_ids(dialog)
    result.excluded_copy_component_ids = _ignored_component_ids(dialog, "sequential_excluded_copy_functions")
    source_model = dialog.project.model_for(str(dialog.sequential_source.currentData()))
    result.copied_component_ids = tuple(
        component.id for component in source_model.components
        if component.id not in result.excluded_copy_component_ids
    )
    return result


def update_propagation_controls(dialog: Any) -> None:
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
