"""UncertaintyPanel."""

from __future__ import annotations

import os

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.project import Project
from curvemole.core.results_store import ResultKey
from curvemole.core.uncertainty import DEFAULT_BLOCK_BOOTSTRAP_REPLICATES, AdaptiveReplicateSettings


class UncertaintyPanel(QWidget):
    runRequested = Signal(str, int, object, str, int, object, int)
    deleteRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        layout = QFormLayout(content)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)
        self.form = layout
        self.method = QComboBox()
        self.method.addItem(self.tr("Fit covariance"), "covariance")
        self.method.addItem(self.tr("Parametric Monte Carlo"), "monte_carlo")
        self.method.addItem(self.tr("Residual bootstrap"), "residual_bootstrap")
        self.method.addItem(self.tr("Block bootstrap"), "block_bootstrap")
        self.method.addItem(self.tr("Profile likelihood"), "profile_likelihood")
        self.method.setCurrentIndex(1)
        self.scope = QComboBox()
        self.scope.addItem(self.tr("Active spectrum"), "active")
        self.scope.addItem(self.tr("Selected spectra"), "selected")
        self.scope.addItem(self.tr("All fitted spectra"), "all")
        self.replicates = QSpinBox()
        self.replicates.setRange(10, 1_000_000)
        self._replicates_edited = False
        self.replicates.setValue(200)
        self.replicates.valueChanged.connect(self._mark_replicates_edited)
        self.replica_timeout = QSpinBox()
        self.replica_timeout.setRange(1, 86_400)
        self.replica_timeout.setValue(60)
        self.replica_timeout.setToolTip(self.tr(
            "Maximum duration of one replica, starting when its calculation begins. "
            "If any replica exceeds this limit, the entire analysis stops and is marked as failed."))
        self.replica_mode = QComboBox()
        self.replica_mode.addItem(self.tr("Fixed count"), "fixed")
        self.replica_mode.addItem(self.tr("Adaptive - stop when intervals stabilize"), "adaptive")
        self.replica_mode.setCurrentIndex(self.replica_mode.findData("adaptive"))
        self.fixed_warning = QLabel(self.tr(
            "Fixed count does not check the numerical stability of confidence intervals. "
            "Prefer Adaptive; use fixed count for tests or when a quick analysis is needed."))
        self.fixed_warning.setWordWrap(True)
        self.fixed_warning.setStyleSheet("color: #9b6500; background: #fff2cf; padding: 6px;")
        self.adaptive_initial = QSpinBox()
        self.adaptive_initial.setRange(2, 1_000_000)
        self.adaptive_initial.setValue(500)
        self.adaptive_batch = QSpinBox()
        self.adaptive_batch.setRange(1, 1_000_000)
        self.adaptive_batch.setValue(200)
        self.adaptive_tolerance = QDoubleSpinBox()
        self.adaptive_tolerance.setRange(0.01, 99.99)
        self.adaptive_tolerance.setDecimals(2)
        self.adaptive_tolerance.setValue(5)
        self.adaptive_tolerance.setSuffix(" %")
        self.adaptive_tolerance.setToolTip(self.tr(
            "Both endpoints of every free parameter's interval must change by less "
            "than this percentage of that interval's current width. "
            "This checks numerical stability, not the validity of the model."))
        self.adaptive_checks = QSpinBox()
        self.adaptive_checks.setRange(1, 100)
        self.adaptive_checks.setValue(3)
        self.adaptive_maximum = QSpinBox()
        self.adaptive_maximum.setRange(500, 1_000_000)
        self.adaptive_maximum.setValue(10_000)
        self.adaptive_maximum.setToolTip(self.tr(
            "Hard limit per independent spectrum or joint fit, including failed fits. "
            "Only successful replicates count toward the initial sample and each batch."))
        self.adaptive_initial.valueChanged.connect(self.adaptive_maximum.setMinimum)
        self.workers = QSpinBox()
        self.workers.setRange(1, max(1, os.cpu_count() or 1))
        self.workers.setValue(min(4, self.workers.maximum()))
        self.workers.setToolTip(self.tr(
            "Maximum spectra processed in parallel: one process per spectrum, "
            "with remaining spectra queued. A single or joint analysis parallelizes "
            "replicates; profile scans parallelize grid points. Custom formulas are supported. "
            "Plugin functions run in one process."))
        self.block_length = QSpinBox()
        self.block_length.setRange(0, 1_000_000)
        self.block_length.setSpecialValueText(self.tr("Automatic"))
        self.parameter = QComboBox()
        self.profile_points = QSpinBox()
        self.profile_points.setRange(5, 1001)
        self.profile_points.setValue(31)
        self.profile_lower = QLineEdit()
        self.profile_upper = QLineEdit()
        self.profile_lower.setPlaceholderText(self.tr("Automatic"))
        self.profile_upper.setPlaceholderText(self.tr("Automatic"))
        self.confidence = QDoubleSpinBox()
        self.confidence.setRange(50, 99.9)
        self.confidence.setValue(95)
        self.confidence.setSuffix(" %")
        self.replica_global_search = QCheckBox(self.tr("Search for alternative minima in each replica"))
        self.replica_global_search.setToolTip(self.tr(
            "Runs Differential Evolution before each local refit. Set physical bounds to cover all plausible "
            "minima. This can substantially increase computation time."))
        from curvemole.gui.uncertainty_results import UncertaintyResults
        self.results = UncertaintyResults(self)
        self.status = self.results.details
        run = QPushButton(self.tr("Run explicit uncertainty analysis"))
        run.clicked.connect(self._run)
        self.delete_button = QPushButton(self.tr("Delete selected analysis from all spectra"))
        self.delete_button.setToolTip(self.tr(
            "Remove the method selected above from every spectrum, including stored samples "
            "and warning tags. Other methods and fitted parameters are preserved. Undo restores it."))
        self.delete_button.clicked.connect(lambda: self.deleteRequested.emit(self.method.currentData()))
        self._busy = False
        layout.addRow(self.tr("Method"), self.method)
        layout.addRow(self.tr("Run on"), self.scope)
        layout.addRow(self.tr("Replicate mode"), self.replica_mode)
        layout.addRow(self.fixed_warning)
        layout.addRow(self.tr("Replicates"), self.replicates)
        layout.addRow(self.tr("Replica timeout (seconds)"), self.replica_timeout)
        layout.addRow(self.tr("Initial successful replicates"), self.adaptive_initial)
        layout.addRow(self.tr("Successful replicates per batch"), self.adaptive_batch)
        layout.addRow(self.tr("Endpoint change tolerance"), self.adaptive_tolerance)
        layout.addRow(self.tr("Consecutive stable checks"), self.adaptive_checks)
        layout.addRow(self.tr("Maximum attempts (including failures)"), self.adaptive_maximum)
        layout.addRow(self.tr("CPU processes"), self.workers)
        layout.addRow(self.replica_global_search)
        layout.addRow(self.tr("Block length"), self.block_length)
        layout.addRow(self.tr("Profile parameter"), self.parameter)
        layout.addRow(self.tr("Profile grid points"), self.profile_points)
        layout.addRow(self.tr("Profile lower limit"), self.profile_lower)
        layout.addRow(self.tr("Profile upper limit"), self.profile_upper)
        layout.addRow(self.tr("Confidence level"), self.confidence)
        layout.addRow(run)
        layout.addRow(self.delete_button)
        layout.addRow(self.results)
        self.method.currentIndexChanged.connect(self._update_controls)
        self.replica_mode.currentIndexChanged.connect(self._update_controls)
        self._update_controls()

    def set_parameters(self, project: Project, curve_id: str | None) -> None:
        self.results.set_project(project, curve_id)
        self._update_delete_button()
        current = self.parameter.currentData()
        self.parameter.clear()
        if curve_id:
            model = project.model_for(curve_id)
            for component in model.components:
                if not component.enabled:
                    continue
                for name, parameter in component.parameters.items():
                    if not parameter.is_free:
                        continue
                    path = model.parameter_path(curve_id, component.id, name)
                    self.parameter.addItem(f"{component.name} · {name}", path)
        index = self.parameter.findData(current)
        self.parameter.setCurrentIndex(max(0, index))

    def _mark_replicates_edited(self) -> None:
        self._replicates_edited = True

    def _update_controls(self) -> None:
        method = self.method.currentData()
        if not self._replicates_edited:
            with QSignalBlocker(self.replicates):
                self.replicates.setValue(DEFAULT_BLOCK_BOOTSTRAP_REPLICATES if method == "block_bootstrap" else 200)
        resampling = method not in {"profile_likelihood", "covariance"}
        adaptive = resampling and self.replica_mode.currentData() == "adaptive"
        self.replica_mode.setEnabled(resampling)
        self.replicates.setEnabled(resampling and not adaptive)
        for widget in (self.adaptive_initial, self.adaptive_batch, self.adaptive_tolerance,
                       self.adaptive_checks, self.adaptive_maximum):
            widget.setEnabled(adaptive)
            self.form.setRowVisible(widget, adaptive)
        self.workers.setEnabled(method != "covariance")
        self.profile_points.setEnabled(method == "profile_likelihood")
        self.profile_lower.setEnabled(method == "profile_likelihood")
        self.profile_upper.setEnabled(method == "profile_likelihood")
        self.confidence.setEnabled(method != "covariance")
        self.block_length.setEnabled(method == "block_bootstrap")
        self.parameter.setEnabled(method == "profile_likelihood")
        self.scope.setEnabled(method != "profile_likelihood")
        if method == "profile_likelihood":
            self.scope.setCurrentIndex(0)
        for widget, visible in (
            (self.replica_mode, resampling),
            (self.replicates, resampling and not adaptive),
            (self.replica_timeout, resampling),
            (self.replica_global_search, resampling),
            (self.workers, method != "covariance"),
            (self.block_length, method == "block_bootstrap"),
            (self.parameter, method == "profile_likelihood"),
            (self.profile_points, method == "profile_likelihood"),
            (self.profile_lower, method == "profile_likelihood"),
            (self.profile_upper, method == "profile_likelihood"),
            (self.confidence, method != "covariance"),
        ):
            self.form.setRowVisible(widget, visible)
        self.results.show_method(method)
        self.form.setRowVisible(self.fixed_warning, resampling and not adaptive)
        self._update_delete_button()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_delete_button()

    def _update_delete_button(self) -> None:
        project = self.results.project
        method = self.method.currentData()
        method = "parametric_monte_carlo" if method == "monte_carlo" else method
        available = project is not None and any(
            method in methods for key in (ResultKey.UNCERTAINTY_REPORTS_BY_CURVE, ResultKey.UNCERTAINTY_BY_CURVE,
                                         ResultKey.UNCERTAINTY_FAILURES_BY_CURVE)
            for methods in project.results.get(key, {}).values())
        self.delete_button.setEnabled(bool(available) and not project.read_only and not self._busy)

    def adaptive_settings(self) -> AdaptiveReplicateSettings | None:
        if (self.method.currentData() in {"profile_likelihood", "covariance"}
                or self.replica_mode.currentData() != "adaptive"):
            return None
        return AdaptiveReplicateSettings(
            initial_successes=self.adaptive_initial.value(),
            batch_successes=self.adaptive_batch.value(),
            tolerance=self.adaptive_tolerance.value() / 100,
            consecutive_checks=self.adaptive_checks.value(),
            maximum_attempts=self.adaptive_maximum.value(),
        )

    def _run(self) -> None:
        method = self.method.currentData()
        option = (
            self.parameter.currentData()
            if method == "profile_likelihood"
            else None
            if self.block_length.value() == 0
            else self.block_length.value()
        )
        self.runRequested.emit(method, self.replicates.value(), option,
                               self.scope.currentData(), self.workers.value(),
                               self.adaptive_settings(), self.replica_timeout.value())

