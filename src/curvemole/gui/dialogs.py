"""Focused dialogs used by the single-window CurveMole interface."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.data import Curve
from curvemole.core.expressions import SafeExpression
from curvemole.core.fitting import FitMode, FitPlan, FitSettings
from curvemole.core.importers import ColumnMapping, ImportConfig, inspect_file
from curvemole.core.models import Component
from curvemole.core.plugins import PluginCandidate, PluginManager
from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry
from curvemole.version import __version__


def _set_list_checked(widget: QListWidget, checked: bool) -> None:
    state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
    for index in range(widget.count()):
        item = widget.item(index)
        if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            item.setCheckState(state)


def _set_table_checked(table: QTableWidget, column: int, checked: bool) -> None:
    state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
    for row in range(table.rowCount()):
        item = table.item(row, column)
        if item is not None and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            item.setCheckState(state)


class ImportMappingDialog(QDialog):
    def __init__(
        self,
        path: str | Path,
        *,
        batch_size: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = Path(path)
        self.setWindowTitle(self.tr("Import data — column mapping"))
        self.resize(900, 610)
        self.inspection = inspect_file(self.path)
        layout = QVBoxLayout(self)
        title = QLabel(f"<b>{self.path.name}</b>")
        layout.addWidget(title)

        settings = QGroupBox(self.tr("Parsing"))
        settings_layout = QHBoxLayout(settings)
        settings_layout.addWidget(QLabel(self.tr("Delimiter:")))
        self.delimiter = QComboBox()
        self.delimiter.addItem(self.tr("Whitespace"), None)
        self.delimiter.addItem(self.tr("Comma"), ",")
        self.delimiter.addItem(self.tr("Semicolon"), ";")
        self.delimiter.addItem(self.tr("Tab"), "\t")
        self.delimiter.addItem(self.tr("Pipe"), "|")
        selected = self.delimiter.findData(self.inspection.config.delimiter)
        self.delimiter.setCurrentIndex(max(0, selected))
        settings_layout.addWidget(self.delimiter)
        settings_layout.addWidget(QLabel(self.tr("Decimal:")))
        self.decimal = QComboBox()
        self.decimal.addItems([".", ","])
        self.decimal.setCurrentText(self.inspection.config.decimal)
        settings_layout.addWidget(self.decimal)
        self.header = QCheckBox(self.tr("First data row is a header"))
        self.header.setChecked(bool(self.inspection.config.header))
        settings_layout.addWidget(self.header)
        settings_layout.addStretch(1)
        self.delimiter.currentIndexChanged.connect(self._reload)
        self.decimal.currentTextChanged.connect(self._reload)
        self.header.toggled.connect(self._reload)
        layout.addWidget(settings)

        self.preview = QTableWidget()
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.setAlternatingRowColors(True)
        layout.addWidget(self.preview, 1)

        mapping_box = QGroupBox(self.tr("Columns"))
        mapping = QGridLayout(mapping_box)
        mapping.addWidget(QLabel(self.tr("X column")), 0, 0)
        self.x_column = QComboBox()
        mapping.addWidget(self.x_column, 0, 1)
        mapping.addWidget(QLabel(self.tr("Y column(s)")), 0, 2)
        self.y_columns = QListWidget()
        self.y_columns.setMaximumHeight(105)
        mapping.addWidget(self.y_columns, 0, 3, 3, 1)
        mapping.addWidget(QLabel(self.tr("sigma_x")), 1, 0)
        self.sigma_x = QComboBox()
        mapping.addWidget(self.sigma_x, 1, 1)
        mapping.addWidget(QLabel(self.tr("Uncertainty/weight")), 2, 0)
        uncertainty_row = QHBoxLayout()
        self.uncertainty_kind = QComboBox()
        self.uncertainty_kind.addItems(
            [self.tr("None"), "sigma_y", self.tr("Weight"), self.tr("Variance"), self.tr("Inverse variance")]
        )
        self.uncertainty_column = QComboBox()
        uncertainty_row.addWidget(self.uncertainty_kind)
        uncertainty_row.addWidget(self.uncertainty_column)
        mapping.addLayout(uncertainty_row, 2, 1, 1, 2)
        layout.addWidget(mapping_box)
        y_buttons = QHBoxLayout()
        self.select_all_y_button = QPushButton(self.tr("Select all Y columns"))
        self.deselect_all_y_button = QPushButton(self.tr("Deselect all Y columns"))
        self.select_all_y_button.clicked.connect(lambda: _set_list_checked(self.y_columns, True))
        self.deselect_all_y_button.clicked.connect(lambda: _set_list_checked(self.y_columns, False))
        y_buttons.addWidget(self.select_all_y_button)
        y_buttons.addWidget(self.deselect_all_y_button)
        y_buttons.addStretch(1)
        layout.addLayout(y_buttons)

        self.apply_all = QCheckBox(self.tr("Apply this mapping to all files in this batch"))
        self.apply_all.setChecked(batch_size > 1)
        self.apply_all.setVisible(batch_size > 1)
        layout.addWidget(self.apply_all)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._populate()

    def config(self) -> ImportConfig:
        return ImportConfig(
            delimiter=self.delimiter.currentData(),
            decimal=self.decimal.currentText(),
            header=self.header.isChecked(),
        )

    def mapping(self) -> ColumnMapping:
        selected_y = [
            self.y_columns.item(index).text()
            for index in range(self.y_columns.count())
            if self.y_columns.item(index).checkState() == Qt.CheckState.Checked
        ]
        mapping = ColumnMapping(
            x=self.x_column.currentText(),
            y=selected_y,
            sigma_x=self.sigma_x.currentData(),
        )
        kind = self.uncertainty_kind.currentText()
        column = self.uncertainty_column.currentData()
        if kind == "sigma_y":
            mapping.sigma_y = column
        elif kind == self.tr("Weight"):
            mapping.weights = column
        elif kind == self.tr("Variance"):
            mapping.variance = column
        elif kind == self.tr("Inverse variance"):
            mapping.inverse_variance = column
        return mapping

    def _reload(self) -> None:
        try:
            self.inspection = inspect_file(self.path, self.config())
            self._populate()
        except Exception as exc:
            QMessageBox.warning(self, self.tr("Import preview"), str(exc))

    def _populate(self) -> None:
        frame = self.inspection.preview
        self.preview.setRowCount(len(frame))
        self.preview.setColumnCount(len(frame.columns))
        self.preview.setHorizontalHeaderLabels([str(value) for value in frame.columns])
        for row in range(len(frame)):
            for column in range(len(frame.columns)):
                self.preview.setItem(row, column, QTableWidgetItem(str(frame.iat[row, column])))
        self.preview.resizeColumnsToContents()
        previous_x = self.x_column.currentText()
        previous_y = {
            self.y_columns.item(index).text()
            for index in range(self.y_columns.count())
            if self.y_columns.item(index).checkState() == Qt.CheckState.Checked
        }
        columns = [str(value) for value in frame.columns]
        self.x_column.clear()
        self.x_column.addItems(columns)
        if previous_x in columns:
            self.x_column.setCurrentText(previous_x)
        self.y_columns.clear()
        for index, column in enumerate(columns):
            item = QListWidgetItem(column)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if column in previous_y or (not previous_y and index == 1) else Qt.CheckState.Unchecked
            )
            self.y_columns.addItem(item)
        for combo in (self.sigma_x, self.uncertainty_column):
            old = combo.currentData()
            combo.clear()
            combo.addItem(self.tr("None"), None)
            for column in columns:
                combo.addItem(column, column)
            selected = combo.findData(old)
            combo.setCurrentIndex(max(0, selected))

    def _accept(self) -> None:
        try:
            self.mapping().validate()
        except Exception as exc:
            QMessageBox.warning(self, self.tr("Column mapping"), str(exc))
            return
        self.accept()


class BackgroundComponentsDialog(QDialog):
    """Choose model components that define the background to subtract."""

    def __init__(
        self,
        project: Project,
        curve_id: str,
        registry: FunctionRegistry,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.curve_id = curve_id
        self.registry = registry
        model = project.model_for(curve_id)
        marked = [component for component in model.components if component.is_background]
        self.marking_mode = not marked
        candidates = [
            component
            for component in (model.components if self.marking_mode else marked)
            if component.enabled
        ]

        self.setWindowTitle(self.tr("Subtract background"))
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        if self.marking_mode:
            message = self.tr(
                "No model functions are marked as background. Indicate which functions represent "
                "the background. The selected functions will be marked as background and subtracted."
            )
        else:
            message = self.tr(
                "Select which functions marked as background should be subtracted from the data."
            )
        explanation = QLabel(message)
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.components = QListWidget()
        for component in candidates:
            definition = registry.get(component.function_id)
            item = QListWidgetItem(f"{component.name}  ·  {definition.display_name}")
            item.setData(Qt.ItemDataRole.UserRole, component.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Unchecked if self.marking_mode else Qt.CheckState.Checked
            )
            self.components.addItem(item)
        layout.addWidget(self.components, 1)

        selection = QHBoxLayout()
        select_all = QPushButton(self.tr("Select all"))
        deselect_all = QPushButton(self.tr("Deselect all"))
        select_all.clicked.connect(lambda: _set_list_checked(self.components, True))
        deselect_all.clicked.connect(lambda: _set_list_checked(self.components, False))
        selection.addWidget(select_all)
        selection.addWidget(deselect_all)
        selection.addStretch(1)
        layout.addLayout(selection)

        if not candidates:
            empty = QLabel(
                self.tr(
                    "There are no enabled candidate functions. Add or enable a model function first."
                )
            )
            empty.setWordWrap(True)
            layout.addWidget(empty)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(candidates))
        layout.addWidget(self.buttons)

    def selected_component_ids(self) -> list[str]:
        return [
            str(self.components.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.components.count())
            if self.components.item(index).checkState() == Qt.CheckState.Checked
        ]


class AddComponentDialog(QDialog):
    def __init__(
        self,
        registry: FunctionRegistry,
        curve: Curve | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.registry = registry
        self.curve = curve
        self.setWindowTitle(self.tr("Add model component"))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.function = QComboBox()
        for definition in registry.values():
            self.function.addItem(definition.display_name, definition.identifier)
        self.name = QLineEdit()
        self.operator = QComboBox()
        self.operator.addItems(["add", "subtract", "multiply", "divide", "convolve"])
        self.polynomial_order = QSpinBox()
        self.polynomial_order.setRange(0, 50)
        self.polynomial_order.setValue(2)
        self.spline_nodes = QLineEdit()
        self.spline_nodes_label = QLabel(self.tr("Spline x nodes"))
        self.spline_help = QLabel(
            self.tr("After pressing Add, place spline nodes anywhere in the plot; pan and zoom remain available.")
        )
        self.spline_help.setWordWrap(True)
        if curve is not None:
            finite_x = curve.x[~curve.invalid]
            if len(finite_x):
                nodes = [np for np in (float(min(finite_x)), float(np_median(finite_x)), float(max(finite_x)))]
                self.spline_nodes.setText(", ".join(f"{value:.8g}" for value in nodes))
        self.description = QLabel()
        self.description.setWordWrap(True)
        form.addRow(self.tr("Function"), self.function)
        form.addRow(self.tr("Component name"), self.name)
        form.addRow(self.tr("Composition"), self.operator)
        form.addRow(self.tr("Polynomial order"), self.polynomial_order)
        form.addRow(self.spline_nodes_label, self.spline_nodes)
        form.addRow("", self.spline_help)
        layout.addLayout(form)
        layout.addWidget(self.description)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.function.currentIndexChanged.connect(self._update)
        self._update()

    def component(self) -> Component:
        identifier = self.function.currentData()
        metadata: dict[str, Any] = {}
        if identifier == "polynomial":
            metadata["order"] = self.polynomial_order.value()
        elif identifier == "cubic_spline":
            metadata["x_nodes"] = [
                float(value.strip()) for value in self.spline_nodes.text().split(",") if value.strip()
            ]
        return Component.create(
            identifier,
            registry=self.registry,
            name=self.name.text().strip() or None,
            metadata=metadata,
            operator=self.operator.currentText(),
        )

    def _update(self) -> None:
        definition = self.registry.get(self.function.currentData())
        self.description.setText(definition.description or definition.display_name)
        self.polynomial_order.setEnabled(definition.identifier == "polynomial")
        is_spline = definition.identifier == "cubic_spline"
        self.spline_nodes.setVisible(False)
        self.spline_nodes_label.setVisible(False)
        self.spline_help.setVisible(is_spline)
        if not self.name.text():
            self.name.setPlaceholderText(definition.display_name)


class ParameterLinkDialog(QDialog):
    """Graphical editor for a parameter dependency."""

    def __init__(
        self,
        project: Project,
        target_curve_id: str,
        target_component_id: str,
        target_parameter: str,
        current_link: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.target_curve_id = target_curve_id
        self.target_component_id = target_component_id
        self.target_parameter = target_parameter
        self._result_link = current_link
        target_curve = project.dataset.curve(target_curve_id)
        target_component = project.model_for(target_curve_id).component(target_component_id)

        self.setWindowTitle(self.tr("Link parameter"))
        self.resize(620, 360)
        layout = QVBoxLayout(self)
        title = QLabel(
            self.tr("Link ")
            + f"<b>{target_curve.name} / {target_component.name} / {target_parameter}</b>"
        )
        title.setWordWrap(True)
        layout.addWidget(title)
        explanation = QLabel(
            self.tr(
                "Choose the parameter that should control this value. CurveMole creates the "
                "internal reference automatically. Links between different spectra require a "
                "Global simultaneous fit."
            )
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        form = QFormLayout()
        self.source_curve = QComboBox()
        self.source_component = QComboBox()
        self.source_parameter = QComboBox()
        self.mode = QComboBox()
        self.mode.addItem(self.tr("Equal to source"), "equal")
        self.mode.addItem(self.tr("Advanced expression"), "advanced")
        self.advanced = QLineEdit()
        self.advanced.setPlaceholderText("2 * ${source} + 1")
        self.advanced_help = QLabel(
            self.tr("Use ${source} for the selected source parameter, for example: 2 * ${source} + 1")
        )
        self.advanced_help.setWordWrap(True)
        form.addRow(self.tr("Source spectrum"), self.source_curve)
        form.addRow(self.tr("Source component"), self.source_component)
        form.addRow(self.tr("Source parameter"), self.source_parameter)
        form.addRow(self.tr("Relationship"), self.mode)
        form.addRow(self.tr("Expression"), self.advanced)
        form.addRow("", self.advanced_help)
        layout.addLayout(form)

        for curve in project.curves:
            self.source_curve.addItem(curve.name, curve.id)
        self.source_curve.currentIndexChanged.connect(self._populate_components)
        self.source_component.currentIndexChanged.connect(self._populate_parameters)
        self.mode.currentIndexChanged.connect(self._update_mode)
        self._populate_components()
        self._load_current(current_link)
        self._update_mode()

        action_row = QHBoxLayout()
        remove = QPushButton(self.tr("Remove link"))
        remove.clicked.connect(self._remove_link)
        action_row.addWidget(remove)
        action_row.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        action_row.addWidget(buttons)
        layout.addLayout(action_row)

    def _populate_components(self) -> None:
        curve_id = self.source_curve.currentData()
        previous = self.source_component.currentData()
        self.source_component.clear()
        if curve_id:
            for component in self.project.model_for(str(curve_id)).components:
                self.source_component.addItem(component.name, component.id)
        index = self.source_component.findData(previous)
        if index >= 0:
            self.source_component.setCurrentIndex(index)
        self._populate_parameters()

    def _populate_parameters(self) -> None:
        curve_id = self.source_curve.currentData()
        component_id = self.source_component.currentData()
        previous = self.source_parameter.currentData()
        self.source_parameter.clear()
        if not curve_id or not component_id:
            return
        component = self.project.model_for(str(curve_id)).component(str(component_id))
        for name in component.parameters:
            if (
                str(curve_id) == self.target_curve_id
                and str(component_id) == self.target_component_id
                and name == self.target_parameter
            ):
                continue
            self.source_parameter.addItem(name, name)
        index = self.source_parameter.findData(previous)
        if index >= 0:
            self.source_parameter.setCurrentIndex(index)

    def _source_path(self) -> str | None:
        curve_id = self.source_curve.currentData()
        component_id = self.source_component.currentData()
        parameter = self.source_parameter.currentData()
        if not curve_id or not component_id or not parameter:
            return None
        return f"{curve_id}.{component_id}.{parameter}"

    def _select_source_path(self, path: str) -> bool:
        parts = path.split(".", 2)
        if len(parts) != 3:
            return False
        curve_id, component_id, parameter = parts
        curve_index = self.source_curve.findData(curve_id)
        if curve_index < 0:
            return False
        self.source_curve.setCurrentIndex(curve_index)
        component_index = self.source_component.findData(component_id)
        if component_index < 0:
            return False
        self.source_component.setCurrentIndex(component_index)
        parameter_index = self.source_parameter.findData(parameter)
        if parameter_index < 0:
            return False
        self.source_parameter.setCurrentIndex(parameter_index)
        return True

    def _load_current(self, current_link: str | None) -> None:
        if not current_link:
            return
        try:
            expression = SafeExpression.compile(current_link)
        except Exception:
            self.mode.setCurrentIndex(self.mode.findData("advanced"))
            self.advanced.setText(current_link)
            return
        references = expression.references
        if references:
            self._select_source_path(references[0])
        exact = len(references) == 1 and current_link.strip() == f"${{{references[0]}}}"
        if exact:
            self.mode.setCurrentIndex(self.mode.findData("equal"))
        else:
            self.mode.setCurrentIndex(self.mode.findData("advanced"))
            if references:
                self.advanced.setText(current_link.replace(f"${{{references[0]}}}", "${source}", 1))
            else:
                self.advanced.setText(current_link)

    def _update_mode(self) -> None:
        advanced = self.mode.currentData() == "advanced"
        self.advanced.setVisible(advanced)
        self.advanced_help.setVisible(advanced)

    def link_expression(self) -> str | None:
        source = self._source_path()
        if source is None:
            return None
        reference = f"${{{source}}}"
        if self.mode.currentData() == "equal":
            return reference
        expression = self.advanced.text().strip() or "${source}"
        return expression.replace("${source}", reference)

    def selected_link(self) -> str | None:
        return self._result_link

    def _remove_link(self) -> None:
        self._result_link = None
        self.accept()

    def _accept(self) -> None:
        link = self.link_expression()
        if not link:
            QMessageBox.warning(
                self,
                self.tr("Link parameter"),
                self.tr("Choose a source parameter or use Remove link."),
            )
            return
        try:
            SafeExpression.compile(link)
        except Exception as exc:
            QMessageBox.warning(self, self.tr("Link parameter"), str(exc))
            return
        self._result_link = link
        self.accept()


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
        self.curves = QTableWidget(len(project.curves), 3)
        self.curves.setHorizontalHeaderLabels([self.tr("Use"), self.tr("Curve"), self.tr("Spectrum weight")])
        for row, curve in enumerate(project.curves):
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
        self.curves.resizeColumnsToContents()
        layout.addWidget(self.curves)
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
        self.solver.addItem(self.tr("Local constrained least squares"), "local")
        self.solver.addItem(self.tr("Differential Evolution + local refinement"), "differential_evolution")
        self.solver.setCurrentIndex(max(0, self.solver.findData(settings.solver)))
        self.loss = QComboBox()
        self.loss.addItems(["linear", "soft_l1", "huber", "cauchy"])
        self.loss.setCurrentText(settings.loss)
        self.max_nfev = QSpinBox()
        self.max_nfev.setRange(100, 10_000_000)
        self.max_nfev.setValue(settings.max_nfev)
        self.confidence = QDoubleSpinBox()
        self.confidence.setRange(50, 99.999)
        self.confidence.setDecimals(3)
        self.confidence.setValue(settings.confidence_level * 100)
        advanced.addRow(self.tr("Initial search"), self.solver)
        advanced.addRow(self.tr("Loss"), self.loss)
        advanced.addRow(self.tr("Maximum evaluations"), self.max_nfev)
        advanced.addRow(self.tr("Confidence level (%)"), self.confidence)
        layout.addWidget(advanced_box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def plan(self) -> FitPlan:
        curve_ids: list[str] = []
        weights: dict[str, float] = {}
        for row in range(self.curves.rowCount()):
            use = self.curves.item(row, 0)
            if use.checkState() != Qt.CheckState.Checked:
                continue
            curve_id = str(use.data(Qt.ItemDataRole.UserRole))
            curve_ids.append(curve_id)
            weights[curve_id] = float(self.curves.item(row, 2).text())
        settings = FitSettings(**asdict(self.settings))
        settings.solver = self.solver.currentData()
        settings.loss = self.loss.currentText()
        settings.max_nfev = self.max_nfev.value()
        settings.confidence_level = self.confidence.value() / 100
        return FitPlan(
            curve_ids,
            self.mode.currentData(),
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

    def _accept(self) -> None:
        try:
            plan = self.plan()
            plan.validate()
            self._validate_link_scope(plan)
        except Exception as exc:
            QMessageBox.warning(self, self.tr("Fit plan"), str(exc))
            return
        self.accept()


class CopyFitDialog(QDialog):
    def __init__(self, project: Project, source_curve_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Copy fit"))
        layout = QVBoxLayout(self)
        source = project.dataset.curve(source_curve_id)
        layout.addWidget(QLabel(self.tr("Source: ") + f"<b>{source.name}</b>"))
        self.targets = QListWidget()
        for curve in project.curves:
            if curve.id == source_curve_id:
                continue
            item = QListWidgetItem(curve.name)
            item.setData(Qt.ItemDataRole.UserRole, curve.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.targets.addItem(item)
        layout.addWidget(self.targets)
        target_buttons = QHBoxLayout()
        self.select_all_targets_button = QPushButton(self.tr("Select all"))
        self.deselect_all_targets_button = QPushButton(self.tr("Deselect all"))
        self.select_all_targets_button.clicked.connect(lambda: _set_list_checked(self.targets, True))
        self.deselect_all_targets_button.clicked.connect(lambda: _set_list_checked(self.targets, False))
        target_buttons.addWidget(self.select_all_targets_button)
        target_buttons.addWidget(self.deselect_all_targets_button)
        target_buttons.addStretch(1)
        layout.addLayout(target_buttons)
        self.structure = QCheckBox(self.tr("Component structure"))
        self.structure.setChecked(True)
        self.values = QCheckBox(self.tr("Current/best values"))
        self.values.setChecked(True)
        self.bounds = QCheckBox(self.tr("Bounds and fixed states"))
        self.bounds.setChecked(True)
        self.links = QCheckBox(self.tr("Internal links"))
        self.links.setChecked(True)
        self.background = QCheckBox(self.tr("Background"))
        self.background.setChecked(True)
        self.masks = QCheckBox(self.tr("Masks (normally excluded)"))
        self.ranges = QCheckBox(self.tr("Fit ranges (normally excluded)"))
        for widget in (self.structure, self.values, self.bounds, self.links, self.background, self.masks, self.ranges):
            layout.addWidget(widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choices(self) -> tuple[list[str], dict[str, bool]]:
        targets = [
            str(self.targets.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.targets.count())
            if self.targets.item(index).checkState() == Qt.CheckState.Checked
        ]
        return targets, {
            "structure": self.structure.isChecked(),
            "values": self.values.isChecked(),
            "bounds_and_fixed": self.bounds.isChecked(),
            "links": self.links.isChecked(),
            "background": self.background.isChecked(),
            "masks": self.masks.isChecked(),
            "fit_ranges": self.ranges.isChecked(),
        }


class ExportBundleDialog(QDialog):
    def __init__(self, remembered: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Export analysis bundle"))
        layout = QVBoxLayout(self)
        info = QLabel(
            self.tr(
                "Wide tables are organised for Origin/QtiPlot and quick inspection. "
                "Tidy tables and JSON are organised for Python and automation."
            )
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        row = QHBoxLayout()
        self.directory = QLineEdit(remembered or "")
        browse = QLabel(f'<a href="#">{self.tr("Choose folder…")}</a>')
        browse.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        browse.linkActivated.connect(self._browse)
        row.addWidget(self.directory, 1)
        row.addWidget(browse)
        layout.addLayout(row)
        self.versioned = QCheckBox(self.tr("Create versioned export"))
        self.overwrite = QCheckBox(self.tr("Update existing CurveMole-owned files after confirmation"))
        self.full_samples = QCheckBox(
            self.tr("Include full uncertainty samples (larger project, easier complete recovery)")
        )
        self.full_samples.setChecked(True)
        layout.addWidget(self.versioned)
        layout.addWidget(self.overwrite)
        layout.addWidget(self.full_samples)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, self.tr("Export folder"), self.directory.text())
        if selected:
            self.directory.setText(selected)

    def _accept(self) -> None:
        if not self.directory.text().strip():
            QMessageBox.warning(self, self.tr("Export"), self.tr("Choose an export folder."))
            return
        self.accept()


class AboutDialog(QDialog):
    def __init__(self, logo_path: str | Path | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("About CurveMole"))
        layout = QVBoxLayout(self)
        if logo_path and Path(logo_path).is_file():
            logo = QLabel()
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo.setPixmap(QPixmap(str(logo_path)).scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            layout.addWidget(logo)
        text = QLabel(
            f"<h2>CurveMole {__version__}</h2>"
            "<p>Modular Scientific Curve Fitting</p>"
            "<p>Sebastiano Romi<br>European Laboratory for Non-Linear Spectroscopy (LENS)<br>"
            "University of Florence (UNIFI)<br>"
            '<a href="mailto:romi@lens.unifi.it">romi@lens.unifi.it</a></p>'
            "<p>GPL-3.0-or-later</p>"
            '<p><a href="https://github.com/SebRoLENS/curvemole">Project and updates</a></p>'
        )
        text.setOpenExternalLinks(True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.accept)
        layout.addWidget(buttons)


class PluginManagerDialog(QDialog):
    def __init__(
        self,
        manager: PluginManager,
        directory: str | Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.candidates: list[PluginCandidate] = []
        self.loaded_identifiers: list[str] = []
        self.setWindowTitle(self.tr("Plugin Manager"))
        self.resize(720, 460)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            self.tr(
                "Python plugins can execute arbitrary code. CurveMole reads local JSON metadata first "
                "and loads code only after your explicit approval."
            )
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        row = QHBoxLayout()
        self.directory = QLineEdit(str(directory or ""))
        browse = QPushButton(self.tr("Choose folder…"))
        browse.clicked.connect(self._browse)
        scan = QPushButton(self.tr("Scan"))
        scan.clicked.connect(self.scan)
        row.addWidget(self.directory, 1)
        row.addWidget(browse)
        row.addWidget(scan)
        layout.addLayout(row)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._show_details)
        layout.addWidget(self.list, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(130)
        layout.addWidget(self.details)
        buttons_row = QHBoxLayout()
        load = QPushButton(self.tr("Review and trust selected plugin…"))
        load.clicked.connect(self._load)
        close = QPushButton(self.tr("Close"))
        close.clicked.connect(self.accept)
        buttons_row.addWidget(load)
        buttons_row.addStretch(1)
        buttons_row.addWidget(close)
        layout.addLayout(buttons_row)
        self.scan()

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, self.tr("Plugin folder"), self.directory.text()
        )
        if selected:
            self.directory.setText(selected)
            self.scan()

    def scan(self) -> None:
        self.candidates = self.manager.discover_local(self.directory.text())
        self.candidates.extend(self.manager.discover_entry_points())
        self.list.clear()
        for candidate in self.candidates:
            self.list.addItem(
                f"{candidate.metadata.identifier}  {candidate.metadata.version}  [{candidate.kind}]"
            )
        if self.candidates:
            self.list.setCurrentRow(0)
        else:
            self.details.setPlainText(self.tr("No plugin manifests or entry points found."))

    def _show_details(self, row: int) -> None:
        if not 0 <= row < len(self.candidates):
            return
        value = self.candidates[row].metadata
        self.details.setPlainText(
            f"Identifier: {value.identifier}\nVersion: {value.version}\n"
            f"API compatibility: {value.api_compatibility}\nLicence: {value.licence}\n"
            f"Capabilities: {', '.join(value.capabilities)}\nSource: {value.source}"
        )

    def _load(self) -> None:
        row = self.list.currentRow()
        if not 0 <= row < len(self.candidates):
            return
        candidate = self.candidates[row]
        answer = QMessageBox.warning(
            self,
            self.tr("Trust Python plugin"),
            self.tr("Loading executes Python code with your user permissions. Review this source first:")
            + f"\n\n{candidate.metadata.source}\n\n"
            + self.tr("Trust and execute this plugin now?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            metadata = self.manager.load(candidate, trust=True)
            self.loaded_identifiers.append(metadata.identifier)
            QMessageBox.information(
                self, self.tr("Plugin Manager"), self.tr("Plugin loaded: ") + metadata.identifier
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("Plugin Manager"), str(exc))


def np_median(values: Any) -> float:
    import numpy as np

    return float(np.median(values))
