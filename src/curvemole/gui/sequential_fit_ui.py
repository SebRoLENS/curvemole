"""Desktop controls and durable pause/resume state for propagating sequential fits."""

from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from curvemole.core.fitting import FitMode
from curvemole.core.sequential_fit import SequentialFitPlan
from curvemole.gui.dialogs import FitPlanDialog
from curvemole.gui.main_window import MainWindow


def _checked_curve_ids(dialog: FitPlanDialog) -> list[str]:
    result: list[str] = []
    for row in range(dialog.curves.rowCount()):
        item = dialog.curves.item(row, 0)
        if item.checkState() == Qt.CheckState.Checked:
            result.append(str(item.data(Qt.ItemDataRole.UserRole)))
    return result


def _install_fit_plan_dialog() -> None:
    if getattr(FitPlanDialog, "_curvemole_propagating_sequence_ui", False):
        return

    original_init = FitPlanDialog.__init__
    original_plan = FitPlanDialog.plan
    original_accept = FitPlanDialog._accept

    def init(dialog: FitPlanDialog, *args: Any, **kwargs: Any) -> None:
        original_init(dialog, *args, **kwargs)
        settings = QSettings("CurveMole", "CurveMole")

        dialog.sequential_box = QGroupBox(dialog.tr("Sequential propagation"))
        box_layout = QVBoxLayout(dialog.sequential_box)
        explanation = QLabel(
            dialog.tr(
                "The initial spectrum is the approved source and is not re-fitted. Its complete "
                "model is copied to the next selected spectrum, fitted there, then that result "
                "becomes the source for the following spectrum. Checked spectra before the source "
                "are not part of the sequence."
            )
        )
        explanation.setWordWrap(True)
        box_layout.addWidget(explanation)

        form = QFormLayout()
        dialog.sequential_source = QComboBox()
        for curve in dialog.project.curves:
            dialog.sequential_source.addItem(curve.name, curve.id)
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

    def source_changed(dialog: FitPlanDialog) -> None:
        if dialog.mode.currentData() != FitMode.SEQUENTIAL:
            return
        source_id = str(dialog.sequential_source.currentData())
        found_source = False
        for row in range(dialog.curves.rowCount()):
            item = dialog.curves.item(row, 0)
            curve_id = str(item.data(Qt.ItemDataRole.UserRole))
            if curve_id == source_id:
                found_source = True
                item.setCheckState(Qt.CheckState.Checked)
            elif not found_source:
                item.setCheckState(Qt.CheckState.Unchecked)

    def update_controls(dialog: FitPlanDialog) -> None:
        sequential = dialog.mode.currentData() == FitMode.SEQUENTIAL
        dialog.sequential_box.setVisible(sequential)
        if sequential and len(_checked_curve_ids(dialog)) < 2:
            source_id = str(dialog.sequential_source.currentData())
            include = False
            for row in range(dialog.curves.rowCount()):
                item = dialog.curves.item(row, 0)
                if str(item.data(Qt.ItemDataRole.UserRole)) == source_id:
                    include = True
                if include:
                    item.setCheckState(Qt.CheckState.Checked)
        residual_enabled = sequential and dialog.sequential_monitor_residuals.isChecked()
        dialog.sequential_residual_ratio.setEnabled(residual_enabled)
        dialog.sequential_residual_delta.setEnabled(residual_enabled)
        parameter_enabled = sequential and dialog.sequential_monitor_parameters.isChecked()
        dialog.sequential_parameter_change.setEnabled(parameter_enabled)

    def plan(dialog: FitPlanDialog) -> Any:
        base = original_plan(dialog)
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

    def accept(dialog: FitPlanDialog) -> None:
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
            return

        if candidate.mode == FitMode.SEQUENTIAL:
            settings = QSettings("CurveMole", "CurveMole")
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
        original_accept(dialog)

    FitPlanDialog.__init__ = init
    FitPlanDialog.plan = plan
    FitPlanDialog._accept = accept
    FitPlanDialog._sequential_source_changed = source_changed
    FitPlanDialog._update_sequential_controls = update_controls
    FitPlanDialog._curvemole_propagating_sequence_ui = True


def _install_pause_resume_state() -> None:
    if getattr(MainWindow, "_curvemole_durable_sequential_resume", False):
        return

    original_fit_finished = MainWindow._fit_finished

    def fit_finished(window: MainWindow, result: Any) -> None:
        existing_plan = getattr(window, "_sequential_resume_plan", None)
        existing_pause = getattr(window, "_sequential_pause_result", None)
        pause_plan = None
        if result.mode == FitMode.SEQUENTIAL and result.paused_curve_id:
            pause_plan = copy.deepcopy(window.last_fit_plan)

        original_fit_finished(window, result)

        if result.mode == FitMode.SEQUENTIAL and result.paused_curve_id:
            window._sequential_resume_plan = pause_plan or existing_plan
            window._sequential_pause_result = result
            window._paused_result = result
            window.resume_action.setEnabled(True)
        elif result.mode == FitMode.SEQUENTIAL and result.success:
            window._sequential_resume_plan = None
            window._sequential_pause_result = None
        elif existing_plan is not None and existing_pause is not None:
            # A normal manual fit performed while the sequence is paused must not
            # discard the suspended sequence. The edited/fitted spectrum will be
            # used as the next propagation source when Resume is pressed.
            window._sequential_resume_plan = existing_plan
            window._sequential_pause_result = existing_pause
            window._paused_result = existing_pause
            window.resume_action.setEnabled(True)
            window.statusBar().showMessage(
                window.tr("Sequential fit is paused. Resume when the current spectrum is satisfactory."),
                8000,
            )

    def resume_sequence(window: MainWindow) -> None:
        result = getattr(window, "_sequential_pause_result", None) or window._paused_result
        plan_template = getattr(window, "_sequential_resume_plan", None) or window.last_fit_plan
        if not result or not result.paused_curve_id or not plan_template:
            return
        try:
            start = plan_template.curve_ids.index(result.paused_curve_id)
        except ValueError:
            return
        plan = copy.deepcopy(plan_template)
        # The manually approved paused spectrum becomes the new source. The
        # propagating fitter deliberately skips the first curve and starts at the next one.
        plan.curve_ids = plan.curve_ids[start:]
        plan.spectrum_weights = {
            curve_id: plan.spectrum_weights.get(curve_id, 1.0)
            for curve_id in plan.curve_ids
        }
        window._run_fit(plan)

    MainWindow._fit_finished = fit_finished
    MainWindow.resume_sequence = resume_sequence
    MainWindow._curvemole_durable_sequential_resume = True


def install_sequential_fit_ui() -> None:
    _install_fit_plan_dialog()
    _install_pause_resume_state()


install_sequential_fit_ui()
