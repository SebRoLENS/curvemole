"""Readable parameter expressions and parameter-dependent bounds."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.expressions import SafeExpression
from curvemole.core.project import Project
from curvemole.gui.series_groups import SourceSpectrumComboBox

_REFERENCE = re.compile(r"\$\{([^{}]+)\}")


class ExpressionEdit(QPlainTextEdit):
    """Multiline expression field, with the previous editor's text API."""

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, value: str) -> None:
        self.setPlainText(value)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)


class ToleranceSpinBox(QDoubleSpinBox):
    def textFromValue(self, value: float) -> str:
        return self.locale().toString(value, "f", self.decimals()).rstrip("0").rstrip(self.locale().decimalPoint())


class ParameterLinkDialog(QDialog):
    def __init__(
        self, project: Project, target_curve_id: str, target_component_id: str,
        target_parameter: str, current_link: str | None = None,
        parent: QWidget | None = None, *, current_scope: str = "relative",
        current_reference_scopes: list[str] | None = None,
        current_relation: str = "equal", current_tolerance: float = 0.0,
        current_tolerance_mode: str = "absolute",
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.target_curve_id = target_curve_id
        self.target_component_id = target_component_id
        self.target_parameter = target_parameter
        self._current_scope = current_scope
        self._result_link = current_link
        self._aliases: dict[str, tuple[str, str]] = {}
        self._advanced_text = ""
        self._last_mode = "equal"
        self._setting_expression = False
        self._ready = False
        curve = project.dataset.curve(target_curve_id)
        component = project.model_for(target_curve_id).component(target_component_id)
        self._target_name = f"{component.name}.{target_parameter}"
        self.setWindowTitle(self.tr("Parameter bounds and links"))
        self.resize(740, 510)
        layout = QVBoxLayout(self)
        title = QLabel(f"{curve.name} / {component.name} / {target_parameter}")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        layout.addWidget(title)
        explanation = QLabel(self.tr(
            "Choose a relationship and its source parameter. For a formula, choose "
            "Advanced expression, then Add each parameter and type the mathematical operators."))
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        form = QFormLayout()
        self.mode = QComboBox()
        for label, value in (("Equal to source (=)", "equal"), ("At least source (≥)", "lower"),
                             ("At most source (≤)", "upper"), ("Similar to source (within a range)", "similar"),
                             ("Advanced expression", "advanced")):
            self.mode.addItem(self.tr(label), value)
        form.addRow(self.tr("Relationship"), self.mode)
        self.source_curve = SourceSpectrumComboBox(project, target_curve_id, self)
        self.source_component = QComboBox()
        self.source_parameter = QComboBox()
        form.addRow(self.tr("Source spectrum"), self.source_curve)
        form.addRow(self.tr("Source function"), self.source_component)
        parameter_row = QWidget()
        row = QHBoxLayout(parameter_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.source_parameter, 1)
        self.add_parameter = QPushButton(self.tr("Add"))
        self.add_parameter.setToolTip(self.tr("Insert the selected parameter at the expression cursor."))
        row.addWidget(self.add_parameter)
        form.addRow(self.tr("Source parameter"), parameter_row)
        self.tolerance_row = QWidget()
        row = QHBoxLayout(self.tolerance_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.tolerance = ToleranceSpinBox()
        self.tolerance.setDecimals(12)
        self.tolerance.setRange(1e-12, 1e12)
        self.tolerance.setSingleStep(0.1)
        self.tolerance.setValue(current_tolerance if current_tolerance > 0 else 0.1)
        self.tolerance_mode = QComboBox()
        self.tolerance_mode.addItem(self.tr("Parameter units"), "absolute")
        self.tolerance_mode.addItem(self.tr("% of the source's absolute value"), "percent")
        self.tolerance_mode.setCurrentIndex(max(0, self.tolerance_mode.findData(current_tolerance_mode)))
        row.addWidget(self.tolerance)
        row.addWidget(self.tolerance_mode)
        form.addRow(self.tr("Tolerance ±"), self.tolerance_row)
        self.tolerance_label = form.labelForField(self.tolerance_row)
        self.copy_help = QLabel()
        self.copy_help.setTextFormat(Qt.TextFormat.PlainText)
        self.copy_help.setWordWrap(True)
        form.addRow("", self.copy_help)
        self.advanced = ExpressionEdit()
        self.advanced.setMaximumHeight(105)
        self.advanced.setPlaceholderText(self.tr("Add parameters, for example: (${Gaussian2.center} + ${Gaussian3.center}) / 2"))
        self.advanced_label = QLabel()
        form.addRow(self.advanced_label, self.advanced)
        layout.addLayout(form)
        self.advanced_help = QLabel(self.tr(
            "Add inserts a named reference to the exact parameter you selected. Use +, -, *, /, "
            "** and parentheses. Changing the selectors does not change references already inserted."))
        self.advanced_help.setWordWrap(True)
        layout.addWidget(self.advanced_help)
        self.preview = QLabel()
        self.preview.setTextFormat(Qt.TextFormat.PlainText)
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        self.constraint_help = QLabel()
        self.constraint_help.setWordWrap(True)
        layout.addWidget(self.constraint_help)
        self.source_curve.currentIndexChanged.connect(self._populate_components)
        self.source_component.currentIndexChanged.connect(self._populate_parameters)
        self.source_parameter.currentIndexChanged.connect(self._update_preview)
        self.mode.currentIndexChanged.connect(self._update_mode)
        self.tolerance.valueChanged.connect(self._update_preview)
        self.tolerance_mode.currentIndexChanged.connect(self._update_tolerance_mode)
        self.add_parameter.clicked.connect(self._add_parameter)
        self.advanced.textChanged.connect(self._expression_changed)
        self._populate_components()
        self._load_current(current_link, current_reference_scopes or [], current_relation)
        self._ready = True
        self._update_tolerance_mode()
        self._update_mode()

        row = QHBoxLayout()
        remove = QPushButton(self.tr("Remove link / constraint"))
        remove.clicked.connect(self._remove_link)
        row.addWidget(remove)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)

    def _populate_components(self) -> None:
        previous = self.source_component.currentData()
        blocked = self.source_component.blockSignals(True)
        self.source_component.clear()
        curve_id = self._source_curve_id()
        if curve_id:
            for component in self.project.model_for(curve_id).display_components:
                self.source_component.addItem(component.name, component.id)
        index = self.source_component.findData(previous)
        if index < 0 and curve_id == self.target_curve_id:
            for row in range(self.source_component.count()):
                candidate = self.source_component.itemData(row)
                if candidate != self.target_component_id and self.target_parameter in self.project.model_for(curve_id).component(candidate).parameters:
                    index = row
                    break
        if index >= 0:
            self.source_component.setCurrentIndex(index)
        self.source_component.blockSignals(blocked)
        self._populate_parameters()

    def _populate_parameters(self) -> None:
        previous = self.source_parameter.currentData()
        blocked = self.source_parameter.blockSignals(True)
        self.source_parameter.clear()
        curve_id = self._source_curve_id()
        component_id = self.source_component.currentData()
        if curve_id and component_id:
            component = self.project.model_for(curve_id).component(component_id)
            for name in component.parameters:
                if (curve_id, component_id, name) != (
                        self.target_curve_id, self.target_component_id, self.target_parameter):
                    self.source_parameter.addItem(name, name)
        index = self.source_parameter.findData(previous)
        if index < 0:
            index = self.source_parameter.findData(self.target_parameter)
        if index >= 0:
            self.source_parameter.setCurrentIndex(index)
        self.source_parameter.blockSignals(blocked)
        self._update_preview()

    def _source_curve_id(self) -> str | None:
        value = self.source_curve.currentData()
        return self.target_curve_id if value == "self" else value

    def _picker_scope(self) -> str:
        return "relative" if self.source_curve.currentData() == "self" else "absolute"

    def _source_path(self) -> str | None:
        values = (self._source_curve_id(), self.source_component.currentData(), self.source_parameter.currentData())
        return ".".join(values) if all(values) else None

    def _select_source_path(self, path: str, scope: str) -> bool:
        parts = path.split(".", 2)
        if len(parts) != 3:
            return False
        curve_id, component_id, parameter = parts
        index = self.source_curve.findData("self" if curve_id == self.target_curve_id and scope == "relative" else curve_id)
        if index < 0:
            return False
        self.source_curve.setCurrentIndex(index)
        index = self.source_component.findData(component_id)
        if index < 0:
            return False
        self.source_component.setCurrentIndex(index)
        index = self.source_parameter.findData(parameter)
        if index < 0:
            return False
        self.source_parameter.setCurrentIndex(index)
        return True

    def _alias(self, path: str, scope: str) -> str:
        for alias, reference in self._aliases.items():
            if alias != "source" and reference == (path, scope):
                return alias
        try:
            curve_id, component_id, parameter = path.split(".", 2)
            curve = self.project.dataset.curve(curve_id)
            component = self.project.model_for(curve_id).component(component_id)
            base = f"{component.name}.{parameter}"
            if scope == "absolute" or curve_id != self.target_curve_id:
                base = f"{self.project.dataset.series_for(curve_id).name} / {curve.name} / {base}"
        except (ValueError, KeyError):
            base = path
        base = base.replace("{", "(").replace("}", ")")
        alias = base
        number = 2
        while alias in self._aliases and self._aliases[alias] != (path, scope):
            alias = f"{base} [{number}]"
            number += 1
        self._aliases[alias] = (path, scope)
        return alias

    def _display_expression(self, expression: str, scopes: list[str]) -> str:
        index = 0

        def replace(match):
            nonlocal index
            scope = scopes[index] if index < len(scopes) else self._current_scope
            index += 1
            return "${" + self._alias(match.group(1).strip(), scope) + "}"

        return _REFERENCE.sub(replace, expression)

    def _load_current(self, link: str | None, scopes: list[str], relation: str) -> None:
        if not link:
            return
        try:
            references = SafeExpression.compile(link).references
        except Exception:
            references = ()
        scopes = scopes or [self._current_scope] * len(references)
        if references:
            self._select_source_path(references[0], scopes[0])
        exact = len(references) == 1 and link.strip() == f"${{{references[0]}}}"
        mode = relation if relation != "equal" else ("equal" if exact else "advanced")
        self.mode.setCurrentIndex(max(0, self.mode.findData(mode)))
        if mode == "advanced":
            self._advanced_text = self._display_expression(link, scopes)

    def _set_expression(self, text: str) -> None:
        self._setting_expression = True
        self.advanced.setText(text)
        self._setting_expression = False

    def _update_mode(self) -> None:
        if not self._ready:
            return
        mode = self.mode.currentData()
        if self._last_mode == "advanced":
            self._advanced_text = self.advanced.text()
        advanced = mode == "advanced"
        self.advanced.setReadOnly(not advanced)
        self.advanced.setFixedHeight(100 if advanced else 54)
        self.add_parameter.setVisible(advanced)
        self.advanced_help.setVisible(advanced)
        self.tolerance_row.setVisible(mode == "similar")
        self.tolerance_label.setVisible(mode == "similar")
        if advanced:
            self._set_expression(self._advanced_text)
        self._last_mode = mode
        self._update_preview()

    def _update_tolerance_mode(self) -> None:
        percent = self.tolerance_mode.currentData() == "percent"
        self.tolerance.setMaximum(99.999999999999 if percent else 1e12)
        self.tolerance.setSuffix(" %" if percent else "")
        self.tolerance.setToolTip(self.tr("A positive percentage below 100%.") if percent else self.tr("A positive tolerance in the parameter's units."))
        self._update_preview()

    def _expression_changed(self) -> None:
        if self._setting_expression or not self._ready or self.mode.currentData() != "advanced":
            return
        if "${source}" in self.advanced.text() and "source" not in self._aliases and self._source_path():
            self._aliases["source"] = (self._source_path(), self._picker_scope())
        self._advanced_text = self.advanced.text()
        self._update_preview()

    def _add_parameter(self) -> None:
        path = self._source_path()
        if path and self.mode.currentData() == "advanced":
            alias = self._alias(path, self._picker_scope())
            self.advanced.insertPlainText("${" + alias + "}")
            self.advanced.setFocus()

    def _update_preview(self) -> None:
        if not self._ready:
            return
        mode = self.mode.currentData()
        path = self._source_path()
        relative = self._picker_scope() == "relative"
        if relative:
            self.copy_help.setText(self.tr("Uses the spectrum containing this parameter. When functions are copied, the reference uses the destination spectrum."))
        else:
            curve_id = self._source_curve_id()
            name = self.project.dataset.curve(curve_id).name if curve_id else ""
            self.copy_help.setText(self.tr("Keeps {spectrum} as its source, including after copying the functions.").format(spectrum=name))
        if mode == "advanced":
            self.copy_help.setText(self.copy_help.text() + " " + self.tr("Add stores this choice with the inserted reference."))
        self.add_parameter.setEnabled(bool(path))
        operator = {"equal": "=", "advanced": "=", "lower": "≥", "upper": "≤", "similar": "≈"}[mode]
        self.advanced_label.setText(f"{self.target_parameter} {operator}")
        if mode != "advanced":
            self._set_expression("${" + self._alias(path, self._picker_scope()) + "}" if path else "")
        expression = self.advanced.text().replace("${", "").replace("}", "")
        if not expression:
            self.preview.setText(self.tr("Choose a source parameter." if mode != "advanced" else "Add the parameters needed for your expression."))
        elif mode == "similar":
            delta = f"{self.tolerance.value():g}"
            if self.tolerance_mode.currentData() == "percent":
                delta = f"{delta}% × |{expression}|"
            self.preview.setText(f"{expression} - ({delta}) ≤ {self._target_name} ≤ {expression} + ({delta})")
        else:
            self.preview.setText(f"{self._target_name} {operator} {expression}")
        bounded = mode in {"lower", "upper", "similar"}
        self.constraint_help.setText(self.tr(
            "The parameter remains free within this constraint. Its limits follow the source at every fit iteration. Static bounds also apply."
            if bounded else "This relationship determines the parameter's value."))
        if self._source_curve_id() != self.target_curve_id or any(
                path.split(".", 1)[0] != self.target_curve_id for path, _ in self._aliases.values()):
            self.constraint_help.setText(self.constraint_help.text() + " " + self.tr("References to other spectra require a Global simultaneous fit including their sources."))

    def _references(self) -> tuple[str, list[str]]:
        if self.mode.currentData() != "advanced":
            path = self._source_path()
            return (f"${{{path}}}", [self._picker_scope()]) if path else ("", [])
        scopes = []

        def replace(match):
            alias = match.group(1).strip()
            path, scope = self._aliases.get(alias, (alias, self._current_scope if alias.startswith(self.target_curve_id + ".") else "absolute"))
            scopes.append(scope)
            return f"${{{path}}}"

        return _REFERENCE.sub(replace, self.advanced.text().strip()), scopes

    def link_expression(self) -> str | None:
        return self._references()[0] or None

    def selected_reference_scopes(self) -> list[str]:
        return self._references()[1] if self._result_link is not None else []

    def selected_link_scope(self) -> str:
        scopes = self._references()[1]
        return "absolute" if scopes and all(scope == "absolute" for scope in scopes) else "relative"

    def selected_relation(self) -> str:
        mode = self.mode.currentData()
        return "equal" if mode == "advanced" else mode

    def selected_tolerance(self) -> float:
        return self.tolerance.value() if self.mode.currentData() == "similar" else 0.0

    def selected_tolerance_mode(self) -> str:
        return self.tolerance_mode.currentData()

    def selected_link(self) -> str | None:
        return self._result_link

    def _remove_link(self) -> None:
        self._result_link = None
        self.accept()

    def _accept(self) -> None:
        link = self.link_expression()
        if not link:
            QMessageBox.warning(self, self.windowTitle(), self.tr("Choose a source parameter, write an expression, or use Remove link / constraint."))
            return
        try:
            SafeExpression.compile(link)
        except Exception as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        self._result_link = link
        self.accept()
