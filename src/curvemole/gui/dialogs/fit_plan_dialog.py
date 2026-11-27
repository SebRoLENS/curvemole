"""FitPlanDialog."""

from __future__ import annotations

import os
from dataclasses import asdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.expressions import SafeExpression
from curvemole.core.fitting import FitMode, FitPlan, FitSettings
from curvemole.core.plugin_identity import contribution_tooltip
from curvemole.core.project import Project
from curvemole.gui.dialogs._shared import (
    _name_accept,
    _set_table_checked,
)
from curvemole.gui.parameter_link import ParameterLinkDialog  # noqa: E402, F401


class FitPlanDialog(QDialog):
    def __init__(
        self,
        project: Project,
        selected_curve_ids: set[str],
        settings: FitSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.settings = settings
        self.setWindowTitle(self.tr("Fit"))
        self.resize(620, 520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItem(self.tr("Single / independent"), FitMode.INDEPENDENT)
        self.mode.addItem(self.tr("Sequential"), FitMode.SEQUENTIAL)
        self.mode.addItem(self.tr("Global simultaneous"), FitMode.GLOBAL)
        form.addRow(self.tr("Mode"), self.mode)
        layout.addLayout(form)
        from curvemole.gui.series_groups import add_scope, style_heading

        source_id = getattr(parent, "active_curve_id", None) or next(
            (curve.id for curve in project.curves if curve.id in selected_curve_ids), None)
        add_scope(self, layout, project, source_id, self._filter_series)
        self.curves = QTableWidget(0, 3)
        self.curves.setAlternatingRowColors(True)
        self.curves.verticalHeader().hide()
        self._series_rows = {}
        self._heading_rows = {}
        self.curves.setHorizontalHeaderLabels([self.tr("Use"), self.tr("Curve"), self.tr("Spectrum weight")])
        for series in project.dataset.series:
            row = self.curves.rowCount()
            self.curves.insertRow(row)
            heading = QTableWidgetItem(series.name)
            style_heading(heading, self.curves)
            self.curves.setItem(row, 0, heading)
            self.curves.setSpan(row, 0, 1, 3)
            self._heading_rows[row] = series.id
            for curve in series.curves:
                row = self.curves.rowCount()
                self.curves.insertRow(row)
                self._series_rows[row] = series.id
                use = QTableWidgetItem()
                use.setFlags(use.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                use.setCheckState(
                    Qt.CheckState.Checked
                    if not selected_curve_ids or curve.id in selected_curve_ids
                    else Qt.CheckState.Unchecked
                )
                use.setData(Qt.ItemDataRole.UserRole, curve.id)
                self.curves.setItem(row, 0, use)
                self.curves.setItem(row, 1, QTableWidgetItem(curve.name))
                self.curves.setItem(row, 2, QTableWidgetItem("1"))
        self.curves.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.curves.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.curves.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.curves)
        self._filter_series()
        curve_buttons = QHBoxLayout()
        self.select_all_curves_button = QPushButton(self.tr("Select all"))
        self.deselect_all_curves_button = QPushButton(self.tr("Deselect all"))
        self.select_all_curves_button.clicked.connect(lambda: _set_table_checked(self.curves, 0, True))
        self.deselect_all_curves_button.clicked.connect(lambda: _set_table_checked(self.curves, 0, False))
        curve_buttons.addWidget(self.select_all_curves_button)
        curve_buttons.addWidget(self.deselect_all_curves_button)
        curve_buttons.addStretch(1)
        layout.addLayout(curve_buttons)
        self.equal_contribution = QCheckBox(self.tr("Scale each spectrum to equal numerical contribution"))
        self.equal_contribution.setChecked(False)
        layout.addWidget(self.equal_contribution)
        advanced_box = QGroupBox(self.tr("Advanced solver settings"))
        advanced = QFormLayout(advanced_box)
        self.solver = QComboBox()
        solver_choices = (
            ("Local least squares (automatic)", "local", "Default: fast local fit. Selects a suitable method for the model, constraints and loss."),
            ("Differential Evolution + local refinement", "differential_evolution", "Global population search, then local fit. Useful when starting values are uncertain; slower."),
            ("Trust Region Reflective (TRF)", "trf", "Local least squares with parameter bounds and robust losses; good general choice."),
            ("Dogbox", "dogbox", "Local least squares with bounds; can suit a small number of parameters."),
            ("Levenberg–Marquardt (LM)", "lm", "Fast local least squares; requires no parameter bounds and linear loss."),
            ("Nelder–Mead", "nelder_mead", "Derivative-free simplex search; useful for rough or non-smooth objectives, often slower."),
            ("Powell", "powell", "Derivative-free direction search; useful when derivatives are unreliable."),
            ("L-BFGS-B", "lbfgsb", "Memory-efficient gradient-based minimisation with optional parameter bounds."),
        )
        for label, identifier, description in solver_choices:
            self.solver.addItem(self.tr(label), identifier)
            self.solver.setItemData(self.solver.count() - 1, self.tr(description),
                                    Qt.ItemDataRole.ToolTipRole)
        from curvemole.core.extensions import extensions
        for entry in extensions.values("fit_solvers"):
            self.solver.addItem(entry.label, entry.identifier)
            self.solver.setItemData(self.solver.count() - 1, contribution_tooltip(entry),
                                    Qt.ItemDataRole.ToolTipRole)
        self.solver.currentIndexChanged.connect(self._update_solver_options)
        self.solver.setCurrentIndex(max(0, self.solver.findData(settings.solver)))
        self.de_bounds = QWidget()
        bound_row = QHBoxLayout(self.de_bounds)
        bound_row.setContentsMargins(0, 0, 0, 0)
        self.de_lower_percent = QDoubleSpinBox()
        self.de_upper_percent = QDoubleSpinBox()
        for spin, value in ((self.de_lower_percent, settings.de_lower_percent),
                            (self.de_upper_percent, settings.de_upper_percent)):
            spin.setRange(0.001, 10000)
            spin.setDecimals(3)
            spin.setSuffix(" %")
            spin.setValue(value)
            spin.setToolTip(self.tr(
                "Applied to the current parameter value only where an explicit bound is absent. "
                "At zero a data-based scale is used. Differential Evolution searches only inside "
                "these limits: with the default 50 %, it cannot reach a value more than 50 % away "
                "from the starting value. Widen these limits or set explicit "
                "bounds when the starting values are uncertain."))
        bound_row.addWidget(QLabel(self.tr("Below")))
        bound_row.addWidget(self.de_lower_percent)
        bound_row.addWidget(QLabel(self.tr("Above")))
        bound_row.addWidget(self.de_upper_percent)
        self.loss = QComboBox()
        for label, description in (
            ("linear", "Ordinary squared residuals: best for approximately Gaussian noise without outliers."),
            ("soft_l1", "Smoothly reduces the influence of large residuals; a gentle robust default."),
            ("huber", "Squared residuals near zero, approximately linear penalty for outliers."),
            ("cauchy", "Strongly suppresses very large residuals; may make optimisation harder."),
        ):
            self.loss.addItem(label)
            self.loss.setItemData(self.loss.count() - 1, self.tr(description), Qt.ItemDataRole.ToolTipRole)
        self.loss.currentIndexChanged.connect(lambda index: self.loss.setToolTip(
            self.loss.itemData(index, Qt.ItemDataRole.ToolTipRole) or ""))
        self.loss.setCurrentText(settings.loss)
        self.loss.setToolTip(self.loss.currentData(Qt.ItemDataRole.ToolTipRole) or "")
        self.max_nfev = QSpinBox()
        self.max_nfev.setRange(1, 10_000_000)
        self.max_nfev.setValue(settings.max_nfev)
        self.confidence = QDoubleSpinBox()
        self.confidence.setRange(50, 99.999)
        self.confidence.setDecimals(3)
        self.confidence.setValue(settings.confidence_level * 100)
        self.solver_form = advanced
        advanced.addRow(self.tr("Algorithm"), self.solver)
        advanced.addRow(self.tr("Automatic search limits"), self.de_bounds)
        advanced.addRow(self.tr("Loss"), self.loss)
        self.f_scale = QLineEdit(str(settings.f_scale))
        self.f_scale.setToolTip(self.tr(
            "Positive transition scale for robust losses, in the residual units used by the solver. "
            "With sigma weighting these are standardized residuals; without it, signal units. "
            "Spectrum weights and equal-contribution scaling also affect this scale."))
        advanced.addRow(self.tr("Loss scale (f_scale)"), self.f_scale)
        self.loss.currentIndexChanged.connect(self._update_loss_options)
        self._update_loss_options()
        advanced.addRow(self.tr("Maximum evaluations"), self.max_nfev)
        self.workers = QSpinBox()
        self.workers.setRange(1, max(1, os.cpu_count() or 1))
        self.workers.setValue(min(settings.workers, self.workers.maximum()))
        self.workers.setToolTip(self.tr(
            "Run independent fits of multiple spectra in separate CPU processes. "
            "Built-in functions and custom formulas support this. "
            "Sequential and global fits remain single-process. Plugins with custom "
            "functions or solvers use the single-process path."))
        advanced.addRow(self.tr("CPU processes (independent fits)"), self.workers)
        advanced.addRow(self.tr("Confidence level (%)"), self.confidence)
        self.use_data_errors = QCheckBox(self.tr("Use data errors / weights in the fit"))
        self.use_data_errors.setChecked(settings.use_data_errors)
        self.use_data_errors.setToolTip(self.tr(
            "Use imported Y uncertainties or point weights. Asymmetric confidence intervals "
            "use the upper/lower error according to the prediction at each iteration. "
            "Uncheck for an unweighted fit; plotted errors and Monte Carlo noise are retained. "
            "X errors are displayed but are not included in this Y-residual fit."))
        from curvemole.gui.solver_options import SolverOptions
        self.solver_options = SolverOptions(settings)
        self.solver_options.form.insertRow(0, self.use_data_errors)
        self.noise_scale = QComboBox()
        self.noise_scale.addItem(self.tr("Automatic from data"), None)
        self.noise_scale.addItem(self.tr("Known absolute uncertainties"), True)
        self.noise_scale.addItem(self.tr("Estimate scale from residuals"), False)
        self.noise_scale.setCurrentIndex(self.noise_scale.findData(settings.absolute_sigma))
        self.noise_scale.setToolTip(self.tr(
            "Automatic treats imported standard deviations or inverse variances as calibrated. "
            "Select Estimate scale when these columns specify only relative precision."))
        self.solver_options.form.insertRow(1, self.tr("Y noise scale"), self.noise_scale)
        self.noise_scale.setEnabled(settings.use_data_errors)
        self.use_data_errors.toggled.connect(self.noise_scale.setEnabled)
        self.advanced_scroll = QScrollArea()
        self.advanced_scroll.setWidgetResizable(True)
        self.advanced_scroll.setWidget(self.solver_options)
        self.advanced_scroll.setMinimumHeight(180)
        self.advanced_scroll.setMaximumHeight(240)
        self.advanced_toggle = QPushButton(self.tr("Advanced algorithm options"))
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self.advanced_scroll.setVisible)
        self.advanced_scroll.hide()
        self.reset_defaults = QPushButton(self.tr("Reset default"))
        self.reset_defaults.setToolTip(self.tr(
            "Restore recommended solver and loss parameters. Keep the selected algorithm, "
            "loss, spectra and fit mode."))
        self.reset_defaults.clicked.connect(self._reset_solver_defaults)
        option_buttons = QHBoxLayout()
        option_buttons.addWidget(self.advanced_toggle)
        option_buttons.addWidget(self.reset_defaults)
        advanced.addRow(option_buttons)
        advanced.addRow(self.advanced_scroll)
        layout.addWidget(advanced_box)
        self._update_solver_options(self.solver.currentIndex())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        _name_accept(buttons, self.tr("Fit"))
        buttons.accepted.connect(lambda: self._accept())
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        from curvemole.gui import sequential_plan_controls

        sequential_plan_controls.build_sequential_controls(self)
        sequential_plan_controls.build_propagation_controls(self)

    def _update_solver_options(self, index: int) -> None:
        self.solver.setToolTip(self.solver.itemData(index, Qt.ItemDataRole.ToolTipRole) or "")
        if hasattr(self, "solver_form"):
            self.solver_form.setRowVisible(self.de_bounds, self.solver.currentData() == "differential_evolution")
        if hasattr(self, "solver_options"):
            self.solver_options.set_solver(self.solver.currentData())

    def _update_loss_options(self, *_):
        self.solver_form.setRowVisible(self.f_scale, self.loss.currentText() != "linear")

    def _reset_solver_defaults(self):
        defaults = FitSettings()
        # Reset hidden controls too, so switching algorithms cannot resurrect stale values.
        self.settings = defaults
        self.solver_options.load(defaults)
        self.f_scale.setText(str(defaults.f_scale))
        self.max_nfev.setValue(defaults.max_nfev)
        self.workers.setValue(defaults.workers)
        self.use_data_errors.setChecked(defaults.use_data_errors)
        self.noise_scale.setCurrentIndex(0)
        self.confidence.setValue(defaults.confidence_level * 100)
        self.de_lower_percent.setValue(defaults.de_lower_percent)
        self.de_upper_percent.setValue(defaults.de_upper_percent)

    def _filter_series(self):
        for row, series_id in {**self._series_rows, **self._heading_rows}.items():
            self.curves.setRowHidden(row, not self.all_series.isChecked() and series_id != self.scope_series_id)
        if hasattr(self, "_refresh_sources"):
            self._refresh_sources()

    def _base_plan(self) -> FitPlan:
        curve_ids: list[str] = []
        weights: dict[str, float] = {}
        for row in range(self.curves.rowCount()):
            use = self.curves.item(row, 0)
            if row not in self._series_rows or self.curves.isRowHidden(row) or use.checkState() != Qt.CheckState.Checked:
                continue
            curve_id = str(use.data(Qt.ItemDataRole.UserRole))
            curve_ids.append(curve_id)
            weights[curve_id] = float(self.curves.item(row, 2).text())
        settings = FitSettings(**asdict(self.settings))
        settings.solver = self.solver.currentData()
        settings.loss = self.loss.currentText()
        if settings.loss != "linear":
            settings.f_scale = float(self.f_scale.text())
        self.solver_options.apply(settings)
        settings.de_lower_percent = self.de_lower_percent.value()
        settings.de_upper_percent = self.de_upper_percent.value()
        settings.max_nfev = self.max_nfev.value()
        settings.workers = self.workers.value()
        settings.confidence_level = self.confidence.value() / 100
        settings.use_data_errors = self.use_data_errors.isChecked()
        settings.absolute_sigma = self.noise_scale.currentData()
        return FitPlan(
            curve_ids,
            FitMode(self.mode.currentData()),
            settings,
            weights,
            self.equal_contribution.isChecked(),
        )

    def _validate_link_scope(self, plan: FitPlan) -> None:
        selected = set(plan.curve_ids)
        for curve_id in plan.curve_ids:
            model = self.project.model_for(curve_id)
            for component in model.components:
                for parameter in component.parameters.values():
                    if not parameter.link:
                        continue
                    for reference in SafeExpression.compile(parameter.link).references:
                        source_curve_id = reference.split(".", 1)[0]
                        if source_curve_id == curve_id:
                            continue
                        if source_curve_id not in selected:
                            raise ValueError(
                                self.tr(
                                    "A linked parameter depends on another spectrum that is not selected. "
                                    "Select both the source and target spectra."
                                )
                            )
                        if plan.mode != FitMode.GLOBAL:
                            raise ValueError(
                                self.tr(
                                    "This fit contains parameter links between different spectra. "
                                    "Choose Global simultaneous mode to apply those constraints."
                                )
                            )

    def _base_accept(self) -> None:
        try:
            plan = self.plan()
            plan.validate()
            self._validate_link_scope(plan)
        except Exception as exc:
            QMessageBox.warning(self, self.tr("Fit plan"), str(exc))
            return
        self.accept()

    def plan(self):
        from curvemole.gui import sequential_plan_controls

        result = sequential_plan_controls.sequential_plan(self, self._base_plan())
        return sequential_plan_controls.propagation_plan(self, result)

    def _accept(self) -> None:
        from curvemole.gui import sequential_plan_controls

        if sequential_plan_controls.sequential_accept_check(self):
            self._base_accept()

    def _sequential_source_changed(self) -> None:
        from curvemole.gui import sequential_plan_controls

        sequential_plan_controls.sequential_source_changed(self)

    def _update_sequential_controls(self) -> None:
        from curvemole.gui import sequential_plan_controls

        sequential_plan_controls.update_sequential_controls(self)
        sequential_plan_controls.update_propagation_controls(self)
