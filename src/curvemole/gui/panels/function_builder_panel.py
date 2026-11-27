"""FunctionBuilderPanel."""

from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from curvemole.core.expressions import expression_parameters
from curvemole.core.functions import formula_definition
from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry


class FunctionBuilderPanel(QWidget):
    functionAdded = Signal(str)

    def __init__(self, registry: FunctionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.project: Project | None = None
        layout = QFormLayout(self)
        layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.identifier = QLineEdit()
        self.display_name = QLineEdit()
        self.kind = QComboBox()
        self.kind.addItem(self.tr("Peak-shaped function"), "peak")
        self.kind.addItem(self.tr("General function"), "generic")
        self.kind.setToolTip(self.tr("Peak-shaped functions support graphical peak placement."))
        self.formula = QPlainTextEdit("area * exp(-0.5*((x-center)/sigma)**2) / (sigma*sqrt(2*pi))")
        self.formula.setMaximumHeight(95)
        self.parameters = QLabel()
        self.parameters.setWordWrap(True)
        self.derived_area = QLineEdit()
        self.derived_fwhm = QLineEdit()
        validate = QPushButton(self.tr("Validate formula"))
        add = QPushButton(self.tr("Add to function library"))
        self.library_button = QPushButton(self.tr("Library folder…"))
        validate.clicked.connect(self._validate)
        add.clicked.connect(self._add)
        layout.addRow(self.tr("Identifier"), self.identifier)
        layout.addRow(self.tr("Display name"), self.display_name)
        layout.addRow(self.tr("Graphical behaviour"), self.kind)
        layout.addRow(self.tr("Formula in x"), self.formula)
        layout.addRow(self.tr("Detected parameters"), self.parameters)
        layout.addRow(self.tr("Derived area formula (optional)"), self.derived_area)
        layout.addRow(self.tr("Derived FWHM formula (optional)"), self.derived_fwhm)
        layout.addRow(validate)
        layout.addRow(add)
        layout.addRow(self.library_button)
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
                kind=str(self.kind.currentData()),
                derived_formulas=derived,
            )
            self.registry.register_custom(definition, replace=True)
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

