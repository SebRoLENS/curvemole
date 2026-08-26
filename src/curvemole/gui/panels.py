"""Dockable model, calculator, formula, worksheet, diagnostics, and uncertainty panels."""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.diagnostics import residual_diagnostics
from curvemole.core.expressions import expression_parameters
from curvemole.core.functions import formula_definition
from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry


class ModelPanel(QWidget):
    componentSelected = Signal(str)
    addRequested = Signal()
    duplicateRequested = Signal(str)
    deleteRequested = Signal(str)
    moveRequested = Signal(str, int)
    enabledRequested = Signal(str, bool)
    parameterChangeRequested = Signal(str, str, str, object)
    copyFitRequested = Signal()

    def __init__(self, registry: FunctionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.project: Project | None = None
        self.curve_id: str | None = None
        self._updating = False
        layout = QVBoxLayout(self)
        self.stack = QStackedWidget()
        single = QWidget()
        single_layout = QVBoxLayout(single)
        self.title = QLabel(self.tr("No active curve"))
        single_layout.addWidget(self.title)
        self.components = QListWidget()
        self.components.currentItemChanged.connect(self._component_selected)
        self.components.itemChanged.connect(self._component_enabled)
        single_layout.addWidget(self.components, 1)
        buttons = QHBoxLayout()
        for text, tooltip, slot in (
            ("+", self.tr("Add component"), self.addRequested.emit),
            ("⧉", self.tr("Duplicate component"), self._duplicate),
            ("↑", self.tr("Move component up"), lambda: self._move(-1)),
            ("↓", self.tr("Move component down"), lambda: self._move(1)),
            ("−", self.tr("Delete component"), self._delete),
        ):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tooltip)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        copy_button = QPushButton(self.tr("Copy fit…"))
        copy_button.clicked.connect(self.copyFitRequested)
        buttons.addWidget(copy_button)
        single_layout.addLayout(buttons)
        self.parameters = QTableWidget(0, 7)
        self.parameters.setHorizontalHeaderLabels(
            [
                self.tr("Parameter"),
                self.tr("Value"),
                self.tr("±1σ"),
                self.tr("Fixed"),
                self.tr("Lower"),
                self.tr("Upper"),
                self.tr("Link"),
            ]
        )
        self.parameters.itemChanged.connect(self._parameter_changed)
        single_layout.addWidget(self.parameters, 2)
        self.derived = QLabel()
        self.derived.setWordWrap(True)
        single_layout.addWidget(self.derived)
        multi = QWidget()
        multi_layout = QVBoxLayout(multi)
        multi_message = QLabel(
            self.tr(
                "Several curves are selected. Use Fit, Copy fit, mask targets, or the Data Calculator "
                "for multi-curve actions. Activate one curve to edit its model."
            )
        )
        multi_message.setWordWrap(True)
        multi_layout.addWidget(multi_message)
        multi_layout.addStretch(1)
        self.stack.addWidget(single)
        self.stack.addWidget(multi)
        layout.addWidget(self.stack)

    def set_context(
        self,
        project: Project,
        curve_id: str | None,
        selected_count: int,
        component_id: str | None = None,
    ) -> None:
        self.project = project
        self.curve_id = curve_id
        self.stack.setCurrentIndex(1 if selected_count > 1 else 0)
        self.refresh(component_id)

    def refresh(self, selected_component_id: str | None = None) -> None:
        self._updating = True
        try:
            self.components.clear()
            self.parameters.setRowCount(0)
            self.derived.clear()
            if self.project is None or self.curve_id is None:
                self.title.setText(self.tr("No active curve"))
                return
            curve = self.project.dataset.curve(self.curve_id)
            model = self.project.model_for(self.curve_id)
            self.title.setText(f"<b>{curve.name}</b><br>{model.name}")
            selected_row = 0
            for row, component in enumerate(model.components):
                definition = self.registry.get(component.function_id)
                label = f"{component.name}  ·  {definition.display_name}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, component.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if component.enabled else Qt.CheckState.Unchecked)
                if definition.kind == "background":
                    item.setForeground(QColor("#666666"))
                self.components.addItem(item)
                if component.id == selected_component_id:
                    selected_row = row
            if self.components.count():
                self.components.setCurrentRow(selected_row)
        finally:
            self._updating = False
        self.refresh_parameters()

    def selected_component_id(self) -> str | None:
        item = self.components.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def refresh_parameters(self) -> None:
        self._updating = True
        try:
            self.parameters.setRowCount(0)
            component_id = self.selected_component_id()
            if not component_id or not self.project or not self.curve_id:
                self.derived.clear()
                return
            model = self.project.model_for(self.curve_id)
            component = model.component(component_id)
            self.parameters.setRowCount(len(component.parameters))
            for row, (name, parameter) in enumerate(component.parameters.items()):
                name_item = QTableWidgetItem(("🔗 " if parameter.link else "") + name)
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.parameters.setItem(row, 0, name_item)
                value = QTableWidgetItem(f"{parameter.value:.12g}")
                value.setData(Qt.ItemDataRole.UserRole, (component.id, name, "value"))
                self.parameters.setItem(row, 1, value)
                error = QTableWidgetItem(
                    "—" if parameter.standard_error is None else f"{parameter.standard_error:.5g}"
                )
                error.setFlags(error.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.parameters.setItem(row, 2, error)
                fixed = QTableWidgetItem("🔒" if parameter.fixed else "")
                fixed.setFlags(fixed.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                fixed.setCheckState(Qt.CheckState.Checked if parameter.fixed else Qt.CheckState.Unchecked)
                fixed.setData(Qt.ItemDataRole.UserRole, (component.id, name, "fixed"))
                self.parameters.setItem(row, 3, fixed)
                lower = QTableWidgetItem("" if math.isinf(parameter.minimum) else f"{parameter.minimum:.12g}")
                lower.setData(Qt.ItemDataRole.UserRole, (component.id, name, "minimum"))
                self.parameters.setItem(row, 4, lower)
                upper = QTableWidgetItem("" if math.isinf(parameter.maximum) else f"{parameter.maximum:.12g}")
                upper.setData(Qt.ItemDataRole.UserRole, (component.id, name, "maximum"))
                self.parameters.setItem(row, 5, upper)
                link = QTableWidgetItem(parameter.link or "")
                link.setData(Qt.ItemDataRole.UserRole, (component.id, name, "link"))
                self.parameters.setItem(row, 6, link)
            self.parameters.resizeColumnsToContents()
            definition = self.registry.get(component.function_id)
            values = {name: parameter.value for name, parameter in component.parameters.items()}
            derived = definition.derived_values(values, component.metadata)
            parts = [
                f"{name}: {'undefined' if value is None else f'{value:.8g}'}"
                for name, value in derived.items()
            ]
            self.derived.setText(self.tr("Derived: ") + "; ".join(parts) if parts else "")
        finally:
            self._updating = False

    def _component_selected(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if self._updating or current is None:
            return
        component_id = str(current.data(Qt.ItemDataRole.UserRole))
        self.refresh_parameters()
        self.componentSelected.emit(component_id)

    def _component_enabled(self, item: QListWidgetItem) -> None:
        if self._updating:
            return
        self.enabledRequested.emit(
            str(item.data(Qt.ItemDataRole.UserRole)), item.checkState() == Qt.CheckState.Checked
        )

    def _parameter_changed(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        metadata = item.data(Qt.ItemDataRole.UserRole)
        if not metadata:
            return
        component_id, name, field = metadata
        try:
            if field == "fixed":
                value: Any = item.checkState() == Qt.CheckState.Checked
            elif field == "link":
                value = item.text().strip() or None
            elif field == "minimum":
                value = float(item.text()) if item.text().strip() else -math.inf
            elif field == "maximum":
                value = float(item.text()) if item.text().strip() else math.inf
            else:
                value = float(item.text())
        except ValueError:
            QMessageBox.warning(self, self.tr("Parameter"), self.tr("Enter a valid number."))
            self.refresh_parameters()
            return
        self.parameterChangeRequested.emit(component_id, name, field, value)

    def _duplicate(self) -> None:
        if component_id := self.selected_component_id():
            self.duplicateRequested.emit(component_id)

    def _delete(self) -> None:
        if component_id := self.selected_component_id():
            self.deleteRequested.emit(component_id)

    def _move(self, delta: int) -> None:
        if component_id := self.selected_component_id():
            self.moveRequested.emit(component_id, delta)


class CalculatorPanel(QWidget):
    applyRequested = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)
        self.operation = QComboBox()
        for label, identifier in (
            (self.tr("Add to y"), "y_add"),
            (self.tr("Subtract from y"), "y_subtract"),
            (self.tr("Multiply y"), "y_multiply"),
            (self.tr("Divide y"), "y_divide"),
            (self.tr("Shift x"), "x_add"),
            (self.tr("Scale x"), "x_multiply"),
            (self.tr("Normalise by maximum"), "normalize_max"),
            (self.tr("Normalise by area"), "normalize_area"),
            (self.tr("Add another curve"), "curve_add"),
            (self.tr("Subtract another curve"), "curve_subtract"),
            (self.tr("Multiply by another curve"), "curve_multiply"),
            (self.tr("Divide by another curve"), "curve_divide"),
        ):
            self.operation.addItem(label, identifier)
        self.value = QDoubleSpinBox()
        self.value.setDecimals(12)
        self.value.setRange(-1e100, 1e100)
        self.value.setValue(1.0)
        self.scope = QComboBox()
        self.scope.addItems([self.tr("Active curve"), self.tr("Selected curves"), self.tr("Entire series")])
        self.operand = QComboBox()
        self.interpolation = QComboBox()
        self.interpolation.addItems(["linear", "nearest", "cubic"])
        self.extrapolate = QCheckBox(self.tr("Allow extrapolation (advanced)"))
        apply = QPushButton(self.tr("Apply non-destructively"))
        restore = QPushButton(self.tr("Restore original data"))
        apply.clicked.connect(self._apply)
        restore.clicked.connect(lambda: self.applyRequested.emit({"restore": True, "scope": self.scope.currentIndex()}))
        layout.addRow(self.tr("Operation"), self.operation)
        layout.addRow(self.tr("Value"), self.value)
        layout.addRow(self.tr("Target"), self.scope)
        layout.addRow(self.tr("Operand curve"), self.operand)
        layout.addRow(self.tr("Interpolation"), self.interpolation)
        layout.addRow("", self.extrapolate)
        layout.addRow(apply)
        layout.addRow(restore)
        self.operation.currentIndexChanged.connect(self._update_enabled)
        self._update_enabled()

    def set_curves(self, project: Project | None) -> None:
        current = self.operand.currentData()
        self.operand.clear()
        if project:
            for curve in project.curves:
                self.operand.addItem(curve.name, curve.id)
        index = self.operand.findData(current)
        self.operand.setCurrentIndex(max(0, index))

    def _update_enabled(self) -> None:
        operation = self.operation.currentData()
        curve_operation = str(operation).startswith("curve_")
        scalar = operation not in {"normalize_max", "normalize_area"} and not curve_operation
        self.value.setEnabled(scalar)
        self.operand.setEnabled(curve_operation)
        self.interpolation.setEnabled(curve_operation)
        self.extrapolate.setEnabled(curve_operation)

    def _apply(self) -> None:
        self.applyRequested.emit(
            {
                "operation": self.operation.currentData(),
                "value": self.value.value(),
                "scope": self.scope.currentIndex(),
                "operand_curve_id": self.operand.currentData(),
                "interpolation": self.interpolation.currentText(),
                "extrapolate": self.extrapolate.isChecked(),
            }
        )


class FunctionBuilderPanel(QWidget):
    functionAdded = Signal(str)

    def __init__(self, registry: FunctionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.project: Project | None = None
        layout = QFormLayout(self)
        self.identifier = QLineEdit()
        self.display_name = QLineEdit()
        self.kind = QComboBox()
        self.kind.addItems(["peak", "background", "generic"])
        self.formula = QPlainTextEdit("area * exp(-0.5*((x-center)/sigma)**2) / (sigma*sqrt(2*pi))")
        self.formula.setMaximumHeight(95)
        self.parameters = QLabel()
        self.parameters.setWordWrap(True)
        self.derived_area = QLineEdit()
        self.derived_fwhm = QLineEdit()
        validate = QPushButton(self.tr("Validate formula"))
        add = QPushButton(self.tr("Add to function library"))
        validate.clicked.connect(self._validate)
        add.clicked.connect(self._add)
        layout.addRow(self.tr("Identifier"), self.identifier)
        layout.addRow(self.tr("Display name"), self.display_name)
        layout.addRow(self.tr("Classification"), self.kind)
        layout.addRow(self.tr("Formula in x"), self.formula)
        layout.addRow(self.tr("Detected parameters"), self.parameters)
        layout.addRow(self.tr("Derived area formula (optional)"), self.derived_area)
        layout.addRow(self.tr("Derived FWHM formula (optional)"), self.derived_fwhm)
        layout.addRow(validate)
        layout.addRow(add)
        self.formula.textChanged.connect(self._validate)
        self._validate()

    def set_project(self, project: Project) -> None:
        self.project = project

    def _validate(self) -> bool:
        try:
            names = expression_parameters(self.formula.toPlainText())
            self.parameters.setText(", ".join(names) or self.tr("None"))
            self.parameters.setStyleSheet("color: #007A5E")
            return True
        except Exception as exc:
            self.parameters.setText(str(exc))
            self.parameters.setStyleSheet("color: #B00020")
            return False

    def _add(self) -> None:
        if not self._validate():
            return
        identifier = re.sub(r"[^a-z0-9_]+", "_", self.identifier.text().strip().lower()).strip("_")
        if not identifier:
            QMessageBox.warning(self, self.tr("Function Builder"), self.tr("Enter an identifier."))
            return
        derived = {}
        if self.derived_area.text().strip():
            derived["area"] = self.derived_area.text().strip()
        if self.derived_fwhm.text().strip():
            derived["FWHM"] = self.derived_fwhm.text().strip()
        try:
            definition = formula_definition(
                identifier,
                self.display_name.text().strip() or identifier,
                self.formula.toPlainText(),
                kind=self.kind.currentText(),
                derived_formulas=derived,
            )
            self.registry.register(definition, replace=True)
            if self.project is not None:
                self.project.custom_functions = [
                    value for value in self.project.custom_functions if value.get("identifier") != identifier
                ]
                self.project.custom_functions.append(
                    {
                        "identifier": identifier,
                        "display_name": definition.display_name,
                        "kind": definition.kind,
                        **definition.custom_metadata,
                    }
                )
                self.project.touch()
            self.functionAdded.emit(identifier)
            QMessageBox.information(self, self.tr("Function Builder"), self.tr("Function added."))
        except Exception as exc:
            QMessageBox.warning(self, self.tr("Function Builder"), str(exc))


class WorksheetPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.label = QLabel(self.tr("No active curve"))
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.label)
        layout.addWidget(self.table)

    def set_curve(self, curve: Any | None, *, maximum_rows: int = 100_000) -> None:
        if curve is None:
            self.label.setText(self.tr("No active curve"))
            self.table.setRowCount(0)
            return
        rows = min(len(curve), maximum_rows)
        self.label.setText(
            f"{curve.name} — {rows}/{len(curve)} " + self.tr("rows shown")
        )
        self.table.setRowCount(rows)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["x", "y", "sigma_y", "weight", self.tr("masked")])
        sigma = curve.current_sigma_y
        for row in range(rows):
            values = [
                curve.x[row],
                curve.y[row],
                sigma[row] if sigma is not None else None,
                curve.weights[row] if curve.weights is not None else None,
                bool(curve.effective_mask[row]),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem("" if value is None else str(value)))


class DiagnosticsPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        layout.addWidget(self.summary)

    def set_residual(self, residual: np.ndarray | None) -> None:
        if residual is None:
            self.summary.setPlainText(self.tr("No fitted residuals are available."))
            return
        diagnostics = residual_diagnostics(residual)
        values = diagnostics.summary()
        text = "\n".join(f"{key}: {value}" for key, value in values.items())
        self.summary.setPlainText(text)


class UncertaintyPanel(QWidget):
    runRequested = Signal(str, int, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)
        self.method = QComboBox()
        self.method.addItem(self.tr("Parametric Monte Carlo"), "monte_carlo")
        self.method.addItem(self.tr("Residual bootstrap"), "residual_bootstrap")
        self.method.addItem(self.tr("Block bootstrap"), "block_bootstrap")
        self.method.addItem(self.tr("Profile likelihood"), "profile_likelihood")
        self.replicates = QSpinBox()
        self.replicates.setRange(10, 1_000_000)
        self.replicates.setValue(1000)
        self.block_length = QSpinBox()
        self.block_length.setRange(0, 1_000_000)
        self.block_length.setSpecialValueText(self.tr("Automatic"))
        self.parameter = QComboBox()
        run = QPushButton(self.tr("Run explicit uncertainty analysis"))
        run.clicked.connect(self._run)
        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        layout.addRow(self.tr("Method"), self.method)
        layout.addRow(self.tr("Replicates"), self.replicates)
        layout.addRow(self.tr("Block length"), self.block_length)
        layout.addRow(self.tr("Profile parameter"), self.parameter)
        layout.addRow(run)
        layout.addRow(self.status)
        self.method.currentIndexChanged.connect(self._update_controls)
        self._update_controls()

    def set_parameters(self, project: Project, curve_id: str | None) -> None:
        current = self.parameter.currentData()
        self.parameter.clear()
        if curve_id:
            model = project.model_for(curve_id)
            for component in model.components:
                for name in component.parameters:
                    path = model.parameter_path(curve_id, component.id, name)
                    self.parameter.addItem(f"{component.name} · {name}", path)
        index = self.parameter.findData(current)
        self.parameter.setCurrentIndex(max(0, index))

    def _update_controls(self) -> None:
        method = self.method.currentData()
        self.replicates.setEnabled(method != "profile_likelihood")
        self.block_length.setEnabled(method == "block_bootstrap")
        self.parameter.setEnabled(method == "profile_likelihood")

    def _run(self) -> None:
        method = self.method.currentData()
        option = (
            self.parameter.currentData()
            if method == "profile_likelihood"
            else None
            if self.block_length.value() == 0
            else self.block_length.value()
        )
        self.runRequested.emit(method, self.replicates.value(), option)
