"""AddComponentDialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.data import Curve
from curvemole.core.models import Component
from curvemole.core.plugin_identity import function_tooltip
from curvemole.core.registry import FunctionRegistry
from curvemole.gui.dialogs._shared import (
    _name_accept,
    np_median,
)
from curvemole.gui.parameter_link import ParameterLinkDialog  # noqa: E402, F401


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
            self.function.setItemData(self.function.count() - 1, function_tooltip(definition),
                                      Qt.ItemDataRole.ToolTipRole)
        self.name = QLineEdit()
        self.operator = QComboBox()
        self.operator.addItems(["add", "subtract", "multiply", "divide", "convolve"])
        self.add_as_background = QCheckBox(self.tr("Mark as background"))
        self.add_as_background.setToolTip(self.tr("Mark this function as part of the spectrum background."))
        self.spline_nodes = QLineEdit()
        self.spline_nodes_label = QLabel(self.tr("Spline x nodes"))
        self.spline_help = QLabel(
            self.tr("For manual initialization, select nodes on the graph after pressing OK. Otherwise edit the node values below.")
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
        form.addRow("", self.add_as_background)
        form.addRow(self.spline_nodes_label, self.spline_nodes)
        form.addRow("", self.spline_help)
        layout.addLayout(form)
        layout.addWidget(self.description)
        from curvemole.gui.function_configuration import InitialParametersTable
        self.options_layout = QVBoxLayout()
        layout.addLayout(self.options_layout)
        self.options_widget = None
        self.parameter_table = InitialParametersTable(self)
        layout.addWidget(self.parameter_table)
        actions = QHBoxLayout()
        self.reset_parameters = QPushButton(self.tr("Restore defaults"))
        self.estimate_parameters = QPushButton(self.tr("Estimate from data"))
        self.estimate_parameters.setEnabled(curve is not None)
        actions.addWidget(self.reset_parameters)
        actions.addWidget(self.estimate_parameters)
        layout.addLayout(actions)
        self.validation_error = QLabel()
        self.validation_error.setWordWrap(True)
        layout.addWidget(self.validation_error)
        self.reset_parameters.clicked.connect(lambda: self._rebuild_parameters(False))
        self.estimate_parameters.clicked.connect(self._estimate_parameters)
        self.resize(760, 640)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        _name_accept(buttons, self.tr("Add"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.function.currentIndexChanged.connect(self._update)
        self._update()
        self.spline_nodes.textChanged.connect(lambda *_: self._rebuild_parameters())

    def _base_component(self) -> Component:
        identifier = self.function.currentData()
        metadata = self.options_widget.metadata()
        if identifier == "cubic_spline":
            metadata["x_nodes"] = [
                float(value.strip()) for value in self.spline_nodes.text().split(",") if value.strip()
            ]
            import math
            nodes = metadata["x_nodes"]
            if any(not math.isfinite(node) for node in nodes) or any(
                right <= left for left, right in zip(nodes, nodes[1:], strict=False)
            ):
                raise ValueError(self.tr("Spline x nodes must be finite and strictly increasing."))
        component = Component.create(
            identifier,
            registry=self.registry,
            name=self.name.text().strip() or None,
            metadata=metadata,
            operator=self.operator.currentText(),
        )
        component.is_background = self.add_as_background.isChecked()
        return component

    def _update(self) -> None:
        definition = self.registry.get(self.function.currentData())
        self.description.setText(function_tooltip(definition) or definition.display_name)
        self.function.setToolTip(function_tooltip(definition))
        from curvemole.gui.function_configuration import FunctionOptionsWidget
        if self.options_widget is not None:
            self.options_layout.removeWidget(self.options_widget)
            self.options_widget.deleteLater()
        self.options_widget = FunctionOptionsWidget(definition, self, getattr(self.parent(), "settings", None))
        self.options_layout.addWidget(self.options_widget)
        self.options_widget.changed.connect(self._rebuild_parameters)
        # Compatibility for callers that already configure polynomial order.
        self.polynomial_order = self.options_widget.controls.get("order")
        self._rebuild_parameters()
        is_spline = definition.identifier == "cubic_spline"
        self.spline_nodes.setVisible(is_spline)
        self.spline_nodes_label.setVisible(is_spline)
        self.spline_help.setVisible(is_spline)
        if not self.name.text():
            self.name.setPlaceholderText(definition.display_name)


    def _rebuild_parameters(self, preserve: bool = True) -> None:
        try:
            component = self._base_component()
            self.parameter_table.populate(component, preserve)
            self.validation_error.clear()
        except Exception as exc:
            self.validation_error.setText(str(exc))

    def component(self) -> Component:
        component = self._base_component()
        if not getattr(self, "manual_points", None) or not self.manual_points.isChecked():
            self.parameter_table.apply(component, self.registry.get(component.function_id))
        return component

    def _estimate_parameters(self) -> None:
        from curvemole.gui.function_configuration import estimate_initial_parameters
        try:
            component = self.component()
            estimated = estimate_initial_parameters(component, self.curve, self.registry)
            self.parameter_table.populate(estimated, preserve=False)
            self.validation_error.clear()
        except Exception as exc:
            self.validation_error.setText(str(exc))

    def accept(self) -> None:
        try:
            self.component()
            self.options_widget.remember()
        except Exception as exc:
            self.validation_error.setText(str(exc))
            return
        super().accept()
