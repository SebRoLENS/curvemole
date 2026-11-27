"""CalculatorPanel."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.calculator_equations import normalize_equation
from curvemole.core.columns import calculator_column_axes
from curvemole.core.project import Project
from curvemole.gui.calculator_columns import ColumnSelector, choose_column


class _CalculatorValue(QDoubleSpinBox):
    def textFromValue(self, value: float) -> str:
        text = super().textFromValue(value)
        separator = self.locale().decimalPoint()
        return text.rstrip("0").removesuffix(separator) if separator in text else text


class CalculatorPanel(QWidget):
    applyRequested = Signal(dict)
    saveFormulaRequested = Signal(dict)
    equationLibraryRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._library_equations = []
        self._column_axes = {}
        self._active_name = ""
        self._has_active = False
        self._selected_count = 0
        self._has_curves = False
        layout = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        sections = QVBoxLayout(content)
        sections.setContentsMargins(0, 0, 0, 0)
        sections.setSpacing(12)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        self.targets_group = QGroupBox(self.tr("1. Spectra to modify"))
        target_layout = QVBoxLayout(self.targets_group)
        self.scope = QComboBox()
        # Keep legacy numeric scopes for active/chooser; selected is explicit,
        # so existing callers using scope=2 for a whole series retain that API.
        self.scope.addItem(self.tr("Active spectrum"), 0)
        self.scope.addItem(self.tr("Selected spectra (0)"), "selected")
        self.scope.addItem(self.tr("Choose multiple spectra…"), 1)
        self.scope_help = QLabel()
        self.scope_help.setWordWrap(True)
        self.scope_help.setTextFormat(Qt.TextFormat.PlainText)
        target_layout.addWidget(self.scope)
        target_layout.addWidget(self.scope_help)
        sections.addWidget(self.targets_group)

        self.operation_group = QGroupBox(self.tr("2. Operation"))
        form = self.operation_form = QFormLayout(self.operation_group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.operation = QComboBox()
        for label, identifier in (
            (self.tr("Custom formulas"), "column_formula"),
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
        self.operation.setCurrentIndex(self.operation.findData("y_multiply"))
        self._style_formula_entries()
        self.value = _CalculatorValue()
        self.value.setDecimals(12)
        self.value.setRange(-1e100, 1e100)
        self.value.setValue(1.0)
        self.column_target = ColumnSelector()
        self.column_insert = QPushButton(self.tr("Insert column…"))
        self.column_insert.clicked.connect(self._insert_column)
        self.destination_help = QLabel(self.tr("The result replaces the chosen column."))
        self.destination_help.setWordWrap(True)
        self.insert_help = QLabel(self.tr("Insert column… lets you search by code or name and insert at the cursor."))
        self.insert_help.setWordWrap(True)
        self.formula_summary = QLabel()
        self.formula_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.formula_summary.setWordWrap(True)
        summary_font = self.formula_summary.font()
        summary_font.setBold(True)
        self.formula_summary.setFont(summary_font)
        self.column_help = QLabel()
        self.column_help.setTextFormat(Qt.TextFormat.PlainText)
        self.column_help.setWordWrap(True)
        self.formula = QLineEdit()
        self.formula.setPlaceholderText(self.tr("e.g. c2 / c3**2, x*y, sqrt(c5)"))
        self.formula_hint = QLabel(self.tr("For mathematical operators, use Python syntax."))
        self.formula_hint.setWordWrap(True)
        self._formula_name = ""
        self.saved_formula = QComboBox()
        self.saved_formula.addItem(self.tr("Choose a formula…"), None)
        self.save_formula_button = QPushButton(self.tr("Save formula"))
        self.save_formula_button.setToolTip(self.tr(
            "Name and save this formula in the project and reusable formula library."))
        self.library_button = QPushButton(self.tr("Library folder…"))
        self.library_button.clicked.connect(self.equationLibraryRequested.emit)
        self.library_help = QLabel()
        self.library_help.setTextFormat(Qt.TextFormat.PlainText)
        self.library_help.setWordWrap(True)
        self.library_help.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.saved_formulas_toggle = QToolButton()
        self.saved_formulas_toggle.setText(self.tr("Load formula"))
        self.saved_formulas_toggle.setCheckable(True)
        self.saved_formulas_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.saved_formulas_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.formula_actions = QWidget()
        formula_actions_layout = QHBoxLayout(self.formula_actions)
        formula_actions_layout.setContentsMargins(0, 0, 0, 0)
        formula_actions_layout.addWidget(self.saved_formulas_toggle)
        formula_actions_layout.addWidget(self.save_formula_button)
        formula_actions_layout.addStretch(1)
        self.saved_formulas_body = QWidget()
        saved_layout = QFormLayout(self.saved_formulas_body)
        saved_layout.setContentsMargins(0, 0, 0, 0)
        saved_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        saved_layout.addRow(self.saved_formula)
        saved_layout.addRow(self.library_button)
        saved_layout.addRow(self.library_help)
        self.saved_formulas_body.hide()
        self.saved_formulas_toggle.toggled.connect(self._toggle_saved_formulas)
        self.operand = QComboBox()
        self.interpolation = QComboBox()
        self.interpolation.addItems(["linear", "nearest", "cubic"])
        self.extrapolate = QCheckBox(self.tr("Allow extrapolation (advanced)"))
        self.apply_button = QPushButton()
        self.restore_button = QPushButton(self.tr("Restore original"))
        self.apply_button.clicked.connect(self._apply)
        self.restore_button.clicked.connect(
            lambda: self.applyRequested.emit({"restore": True, "scope": self.scope.currentData()}))
        form.addRow(self.operation)
        form.addRow(self.tr("Value"), self.value)
        form.addRow(self.tr("Write result to"), self.column_target)
        form.addRow(self.destination_help)
        self.formula_row = QWidget()
        formula_layout = QHBoxLayout(self.formula_row)
        formula_layout.setContentsMargins(0, 0, 0, 0)
        formula_layout.addWidget(self.formula, 1)
        formula_layout.addWidget(self.column_insert)
        form.addRow(self.tr("Formula"), self.formula_row)
        form.addRow(self.formula_hint)
        form.addRow(self.insert_help)
        form.addRow(self.column_help)
        form.addRow(self.formula_actions)
        form.addRow(self.saved_formulas_body)
        form.addRow(self.tr("Operand spectrum"), self.operand)
        form.addRow(self.tr("Interpolation"), self.interpolation)
        form.addRow(self.extrapolate)
        sections.addWidget(self.operation_group)

        self.result_group = QGroupBox(self.tr("3. Result"))
        result_layout = QVBoxLayout(self.result_group)
        result_layout.addWidget(self.formula_summary)
        self.result_targets = QLabel()
        self.result_targets.setWordWrap(True)
        result_layout.addWidget(self.result_targets)
        history_help = QLabel(self.tr("Original data are kept. Operations can be undone."))
        history_help.setWordWrap(True)
        result_layout.addWidget(history_help)
        sections.addWidget(self.result_group)
        sections.addStretch(1)
        footer = QHBoxLayout()
        footer.addWidget(self.restore_button)
        footer.addWidget(self.apply_button, 1)
        layout.addLayout(footer)
        self.formula.textChanged.connect(self._update_formula_summary)
        self.column_target.currentIndexChanged.connect(self._update_formula_summary)
        self.value.valueChanged.connect(self._update_formula_summary)
        self.operand.currentIndexChanged.connect(self._update_formula_summary)
        self.scope.currentIndexChanged.connect(self._update_scope_summary)
        self.operation.currentIndexChanged.connect(self._update_enabled)
        self.saved_formula.currentIndexChanged.connect(self._load_saved_formula)
        self.save_formula_button.clicked.connect(self._save_formula)
        self._update_enabled()
        self._update_scope_summary()

    def _toggle_saved_formulas(self, expanded: bool) -> None:
        self.operation_form.setRowVisible(
            self.saved_formulas_body, expanded and self.operation.currentData() == "column_formula")
        self.saved_formulas_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def set_selection_context(self, project, active_id, selected_ids=()) -> None:
        """Refresh only scope feedback when highlighted rows change."""
        curves = project.curves if project else []
        active = next((curve for curve in curves if curve.id == active_id), None)
        self._active_name = active.name if active is not None else ""
        self._has_active = active is not None
        self._has_curves = bool(curves)
        self._selected_count = sum(curve.id in selected_ids for curve in curves)
        self.scope.setItemText(self.scope.findData("selected"),
                               self.tr("Selected spectra ({count})").format(count=self._selected_count))
        self._update_scope_summary()

    def _update_scope_summary(self, *_: Any) -> None:
        scope = self.scope.currentData()
        if scope == "selected":
            count = self._selected_count
            help_text = (self.tr("Uses the highlighted rows in the spectrum list, including selected series.")
                         if count else self.tr("No spectra selected. Highlight rows in the spectrum list first."))
        elif scope == 1:
            count = None
            help_text = self.tr("A separate selection window opens when you apply or restore.")
        else:
            count = int(self._has_active)
            help_text = (self.tr("Active spectrum: {name}").format(name=self._active_name)
                         if count else self.tr("No active spectrum."))
        self.scope_help.setText(help_text)
        if count is None:
            result = self.tr("Choose spectra in the separate selection window.")
            apply_text = self.tr("Choose spectra and apply…")
        elif count == 1:
            result = self.tr("Applies to 1 spectrum.")
            apply_text = self.tr("Apply to 1 spectrum")
        else:
            result = self.tr("Applies to {count} spectra.").format(count=count)
            apply_text = self.tr("Apply to {count} spectra").format(count=count)
        self.result_targets.setText(result)
        self.apply_button.setText(apply_text)
        enabled = self._has_curves if count is None else count > 0
        self.apply_button.setEnabled(enabled)
        self.restore_button.setEnabled(enabled)
        self.restore_button.setToolTip(self.tr("Restore original data for this scope. Undo remains available."))

    def _style_formula_entries(self) -> None:
        colour = QColor("#66C7A8") if self.palette().window().color().lightness() < 128 else QColor("#087F6C")
        font = self.operation.font()
        font.setBold(True)
        for identifier in ("column_formula",):
            index = self.operation.findData(identifier)
            self.operation.setItemData(index, colour, Qt.ItemDataRole.ForegroundRole)
            self.operation.setItemData(index, font, Qt.ItemDataRole.FontRole)
        normal = self.palette().text().color().name()
        selected = colour.name() if self.operation.currentData() == "column_formula" else normal
        self.operation.setStyleSheet(f"QComboBox {{ color: {selected}; }} QComboBox QAbstractItemView {{ color: {normal}; }}")

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "operation"):
            self._style_formula_entries()

    def set_curves(self, project: Project | None, active_id: str | None = None, selected_ids=()) -> None:
        target = self.column_target.currentData()
        had_columns = bool(self.column_target.count())
        self.column_target.blockSignals(True)
        self.column_target.clear()
        self._column_axes = {}
        if project and active_id:
            curve = project.dataset.curve(active_id)
            self._column_axes = calculator_column_axes(curve.original_columns, curve.column_axes)
            keys = list(curve.original_columns)
            keys.extend(key for key in self._column_axes.values() if key not in keys)
            for key in keys:
                roles = [axis.upper() for axis in ("x", "y")
                         if self._column_axes.get(axis) == key]
                display = key + (f" ({', '.join(roles)})" if roles else "")
                label = curve.column_labels.get(key, "")
                if not label and roles:
                    label = curve.x_label if "X" in roles else curve.y_label
                self.column_target.add_column(display, key, label)
        if target is not None:
            target = self._column_axes.get(target, target)
        elif not had_columns:
            target = self._column_axes.get("y")
        self.column_target.setCurrentIndex(self.column_target.findData(target))
        self.column_target.blockSignals(False)
        self.column_insert.setEnabled(bool(self.column_target.count()))
        self.column_target.setEnabled(bool(self.column_target.count()))
        self.column_help.setText(self.tr(
            "Use c1, c2, … for columns; (X) and (Y) identify the current axes. "
            "The names x and y also refer to those axes. Example: c2 / c3**2."))
        current_formula = self.saved_formula.currentData()
        self.saved_formula.blockSignals(True)
        self.saved_formula.clear()
        self.saved_formula.addItem(self.tr("Choose a formula…"), None)
        equations = {item["name"]: (item, "library") for item in self._library_equations}
        if project:
            for item in project.custom_formulas:
                try:
                    item = normalize_equation(item)
                except Exception:
                    # Preserve malformed historical entries in the project so
                    # the user can still recover them from its metadata.
                    continue
                equations[item["name"]] = (item, "project")
        for name in sorted(equations, key=str.casefold):
            item, origin = equations[name]
            origin_text = self.tr("project") if origin == "project" else self.tr("library")
            self.saved_formula.addItem(f"{name} ({origin_text})", item)
            self.saved_formula.setItemData(self.saved_formula.count() - 1,
                                          f"{item['target']} ← {item['formula']}",
                                          Qt.ItemDataRole.ToolTipRole)
        index = next((i for i in range(self.saved_formula.count()) if self.saved_formula.itemData(i) == current_formula), 0)
        self.saved_formula.setCurrentIndex(index)
        self.saved_formula.blockSignals(False)
        current = self.operand.currentData()
        self.operand.clear()
        if project:
            for curve in project.curves:
                self.operand.addItem(curve.name, curve.id)
        index = self.operand.findData(current)
        self.operand.setCurrentIndex(max(0, index))
        self.set_selection_context(project, active_id, selected_ids)
        self._update_formula_summary()


    def _update_formula_summary(self, *_: Any) -> None:
        operation = self.operation.currentData()
        formula = self.formula.text().strip()
        if operation == "column_formula":
            destination = self.column_target.currentText()
            text = (f"{destination} ← {formula}" if formula and destination
                    else self.tr("Enter a formula to see where its result will be written."))
        elif operation in {"normalize_max", "normalize_area"}:
            text = self.operation.currentText()
        elif str(operation).startswith("curve_"):
            text = self.operation.currentText() + " — " + self.operand.currentText()
        else:
            axis = "X" if str(operation).startswith("x_") else "Y"
            symbol = {"y_add": "+", "y_subtract": "−", "y_multiply": "×", "y_divide": "÷",
                      "x_add": "+", "x_multiply": "×"}.get(operation, "")
            text = f"{axis} ← {axis} {symbol} {self.value.cleanText()}"
        self.formula_summary.setText(text)

    def set_equation_library(self, equations, directory, failures=()) -> None:
        self._library_equations = equations
        message = self.tr("Formula library: {path}").format(path=directory)
        if failures:
            message += "\n" + self.tr("Some formulas could not be loaded:") + "\n" + "\n".join(failures)
        self.library_help.setText(message)
        self.library_button.setToolTip(str(directory))

    def _insert_column(self) -> None:
        cursor = self.formula.cursorPosition()
        selection = self.formula.selectionStart()
        selection_length = len(self.formula.selectedText())
        index = choose_column(self.column_insert, self.column_target.model())
        if index is not None:
            key = self.column_target.itemData(index)
            self.formula.setFocus()
            if selection >= 0:
                self.formula.setSelection(selection, selection_length)
            else:
                self.formula.setCursorPosition(cursor)
            self.formula.insert(key)

    def _load_saved_formula(self, index: int) -> None:
        item = self.saved_formula.itemData(index)
        if not isinstance(item, dict):
            return
        try:
            item = normalize_equation(item)
        except Exception as exc:
            QMessageBox.warning(self, self.tr("Load formula"), str(exc))
            return
        self.formula.setText(item["formula"])
        self._formula_name = item["name"]
        self.operation.setCurrentIndex(self.operation.findData("column_formula"))
        target = self._column_axes.get(item["target"], item["target"])
        self.column_target.setCurrentIndex(self.column_target.findData(target))
        # An unavailable destination remains unselected. Never silently write a
        # recalled equation into another column in a differently shaped table.

    def _save_formula(self) -> None:
        formula = self.formula.text().strip()
        if not formula:
            QMessageBox.warning(self, self.tr("Save formula"), self.tr("Enter a formula first."))
            return
        target = self.column_target.currentData()
        if target is None:
            QMessageBox.warning(self, self.tr("Save formula"), self.tr("Choose a destination column."))
            return
        name, accepted = QInputDialog.getText(
            self.window(), self.tr("Save formula"), self.tr("Formula name:"), text=self._formula_name)
        if not accepted:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, self.tr("Save formula"), self.tr("Enter a formula name."))
            return
        self._formula_name = name
        self.saveFormulaRequested.emit({"name": name, "formula": formula,
                                        "mode": "column_formula", "target": target})

    def _update_enabled(self) -> None:
        self._style_formula_entries()
        operation = self.operation.currentData()
        curve_operation = str(operation).startswith("curve_")
        scalar = operation not in {"normalize_max", "normalize_area"} and not curve_operation
        custom = operation == "column_formula"
        form = self.operation_form
        form.labelForField(self.value).setText({
            "y_multiply": self.tr("Multiply by"), "x_multiply": self.tr("Multiply by"),
            "y_divide": self.tr("Divide by"), "x_add": self.tr("Shift by"),
        }.get(operation, self.tr("Value")))
        for widget, visible in (
            (self.formula_hint, custom), (self.formula_row, custom),
            (self.column_help, custom), (self.destination_help, custom), (self.insert_help, custom),
            (self.column_target, custom), (self.value, scalar and not custom),
            (self.formula_actions, custom),
            (self.saved_formulas_body, custom and self.saved_formulas_toggle.isChecked()),
            (self.operand, curve_operation), (self.interpolation, curve_operation),
            (self.extrapolate, curve_operation),
        ):
            form.setRowVisible(widget, visible)
        self.column_target.setEnabled(custom and bool(self.column_target.count()))
        self.column_insert.setEnabled(custom and bool(self.column_target.count()))
        self.save_formula_button.setEnabled(custom)
        self.formula.setEnabled(custom)
        self.formula.setPlaceholderText(self.tr("e.g. c2 / c3**2, x*y, sqrt(c5)"))
        self.value.setEnabled(scalar and not custom)
        for widget in (self.operand, self.interpolation, self.extrapolate):
            widget.setEnabled(curve_operation)
        self._update_formula_summary()

    def _apply(self) -> None:
        if self.operation.currentData() == "column_formula" and self.column_target.currentData() is None:
            QMessageBox.warning(self, self.tr("Data Calculator"), self.tr("Choose a destination column."))
            return
        self.applyRequested.emit(
            {
                "operation": self.operation.currentData(),
                "value": self.value.value(),
                "column_target": self.column_target.currentData(),
                "formula": self.formula.text(),
                "scope": self.scope.currentData(),
                "operand_curve_id": self.operand.currentData(),
                "interpolation": self.interpolation.currentText(),
                "extrapolate": self.extrapolate.isChecked(),
            }
        )

