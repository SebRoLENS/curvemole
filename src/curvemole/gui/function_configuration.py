"""Shared construction options and editable initial parameter configuration."""
from __future__ import annotations

import copy
import json
import math

import numpy as np
from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.errors import CurveMoleError
from curvemole.core.parameters import Parameter


class FunctionOptionsWidget(QWidget):
    changed = Signal()

    def __init__(self, definition, parent=None, settings=None):
        super().__init__(parent)
        self.definition = definition
        self.settings = settings or QSettings("CurveMole", "CurveMole")
        self.controls = {}
        form = QFormLayout(self)
        try:
            remembered = json.loads(str(self.settings.value(self.key, "{}")))
            if not isinstance(remembered, dict):
                remembered = {}
        except (ValueError, TypeError):
            remembered = {}
        for spec in definition.configuration_specs:
            value = remembered.get(spec.name, spec.default)
            try:
                spec.validate(value)
            except (ValueError, CurveMoleError):
                value = spec.default
            if spec.kind == "integer":
                control = QSpinBox()
                control.setRange(int(spec.minimum if spec.minimum is not None else -2147483647),
                                 int(spec.maximum if spec.maximum is not None else 2147483647))
                control.setValue(value)
                control.valueChanged.connect(lambda *_: self.changed.emit())
            elif spec.kind == "number":
                control = QDoubleSpinBox()
                control.setDecimals(12)
                control.setRange(spec.minimum if spec.minimum is not None else -1e100,
                                 spec.maximum if spec.maximum is not None else 1e100)
                control.setValue(value)
                control.valueChanged.connect(lambda *_: self.changed.emit())
            elif spec.kind == "boolean":
                control = QCheckBox()
                control.setChecked(value)
                control.toggled.connect(lambda *_: self.changed.emit())
            elif spec.kind == "choice":
                control = QComboBox()
                control.addItems(spec.choices)
                control.setCurrentText(value)
                control.currentTextChanged.connect(lambda *_: self.changed.emit())
            elif spec.kind == "text":
                control = QLineEdit(value)
                control.textChanged.connect(lambda *_: self.changed.emit())
            else:
                raise ValueError(f"Unsupported construction option: {spec.kind}")
            control.setObjectName(f"function_option_{spec.name}")
            control.setToolTip(spec.description)
            self.controls[spec.name] = control
            form.addRow(self.tr(spec.label), control)

    @property
    def key(self):
        return f"function_options/{self.definition.identifier}"

    def metadata(self):
        result = {}
        for spec in self.definition.configuration_specs:
            control = self.controls[spec.name]
            if spec.kind in {"integer", "number"}:
                value = control.value()
            elif spec.kind == "boolean":
                value = control.isChecked()
            elif spec.kind == "choice":
                value = control.currentText()
            else:
                value = control.text()
            result[spec.name] = spec.validate(value)
        return result

    def remember(self):
        self.settings.setValue(self.key, json.dumps(self.metadata()))


class FunctionOptionsDialog(QDialog):
    def __init__(self, definition, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Configure function") + " — " + definition.display_name)
        layout = QVBoxLayout(self)
        self.options = FunctionOptionsWidget(definition, self, getattr(parent, "settings", None))
        layout.addWidget(self.options)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        try:
            self.options.metadata()
            self.options.remember()
        except (ValueError, CurveMoleError) as exc:
            self.error.setText(str(exc))
            return
        super().accept()


class InitialParametersTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 5, parent)
        self.setObjectName("initial_parameters_table")
        self.setHorizontalHeaderLabels([self.tr(s) for s in ("Parameter", "Initial value", "Minimum", "Maximum", "Fixed")])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setMinimumHeight(190)
        self.setToolTip(self.tr("Use -inf and inf for unbounded limits. Bounds also apply during fitting."))
        self._function_id = None

    def populate(self, component, preserve=True):
        previous = {}
        if preserve and self._function_id == component.function_id:
            for row in range(self.rowCount()):
                previous[self.item(row, 0).text()] = [self.item(row, col).text() for col in (1, 2, 3)] + [self.item(row, 4).checkState()]
        self.blockSignals(True)
        self.setRowCount(len(component.parameters))
        for row, parameter in enumerate(component.parameters.values()):
            name = QTableWidgetItem(parameter.name)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, 0, name)
            old = previous.get(parameter.name)
            for col, value in enumerate((parameter.value, parameter.minimum, parameter.maximum), 1):
                self.setItem(row, col, QTableWidgetItem(old[col-1] if old else str(value)))
            fixed = QTableWidgetItem()
            fixed.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            fixed.setCheckState(old[3] if old else Qt.CheckState.Checked if parameter.fixed else Qt.CheckState.Unchecked)
            self.setItem(row, 4, fixed)
        self._function_id = component.function_id
        self.blockSignals(False)

    def apply(self, component, definition):
        specs = {spec.name: spec for spec in definition.specs(component.metadata)}
        errors = []
        for row in range(self.rowCount()):
            name = self.item(row, 0).text()
            try:
                value, lower, upper = (float(self.item(row, col).text().strip().replace("∞", "inf")) for col in (1, 2, 3))
                spec = specs[name]
                if not math.isfinite(value) or math.isnan(lower) or math.isnan(upper):
                    raise ValueError(self.tr("Use a finite initial value and valid limits."))
                if lower < spec.minimum or upper > spec.maximum:
                    raise ValueError(self.tr("Limits exceed the function's allowed domain."))
                parameter = Parameter(name, value, lower, upper,
                                      fixed=self.item(row, 4).checkState() == Qt.CheckState.Checked,
                                      unit=spec.unit)
                component.parameters[name] = parameter
            except (ValueError, CurveMoleError) as exc:
                errors.append(f"{name}: {exc}")
                for col in (1, 2, 3):
                    self.item(row, col).setToolTip(str(exc))
                    self.item(row, col).setBackground(Qt.GlobalColor.red)
            else:
                for col in (1, 2, 3):
                    self.item(row, col).setToolTip("")
                    self.item(row, col).setData(Qt.ItemDataRole.BackgroundRole, None)
        if errors:
            raise ValueError("\n".join(errors))
        return component


def estimate_initial_parameters(component, curve, registry):
    """Estimate on usable data without changing bounds, fixed values or the project."""
    from scipy.optimize import least_squares

    from curvemole.core.initialization import find_peak_suggestions, initialise_peak_component

    definition = registry.get(component.function_id)
    keep = ~curve.effective_mask & np.isfinite(curve.x) & np.isfinite(curve.y)
    x, y = curve.x[keep], curve.y[keep]
    if not len(x):
        raise ValueError("The active curve has no usable points.")
    estimated = copy.deepcopy(component)
    free = [p for p in estimated.parameters.values() if not p.fixed and p.minimum < p.maximum]
    if not free:
        return estimated
    if definition.kind == "peak":
        suggestions = find_peak_suggestions(curve, sign="both", max_peaks=1)
        if suggestions:
            seed = copy.deepcopy(component)
            initialise_peak_component(seed, suggestions[0], registry=registry)
            for parameter in free:
                if parameter.name in seed.parameters:
                    parameter.value = float(np.clip(seed.parameters[parameter.name].value, parameter.minimum, parameter.maximum))
    names = [p.name for p in free]
    values = {name: p.value for name, p in estimated.parameters.items()}
    scale = max(float(np.max(np.abs(y))), 1.0)

    def residual(vector):
        mapping = dict(values, **dict(zip(names, vector, strict=True)))
        result = (definition.evaluate(x, mapping, estimated.metadata) - y) / scale
        if not np.all(np.isfinite(result)):
            raise ValueError("The function produced non-finite values during estimation.")
        return result

    result = least_squares(residual, [p.value for p in free],
                           bounds=([p.minimum for p in free], [p.maximum for p in free]),
                           max_nfev=1000)
    if not result.success:
        raise ValueError(f"Initial estimation did not converge: {result.message}")
    for parameter, value in zip(free, result.x, strict=True):
        parameter.value = float(value)
        parameter.validate()
    return estimated
