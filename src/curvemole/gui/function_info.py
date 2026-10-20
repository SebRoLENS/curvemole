"""Formula and parameter reference for the selected function."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from curvemole.core.functions import FunctionDefinition
from curvemole.core.plugin_identity import function_tooltip

_FORMULAS = {
    "gaussian": "f(x) = area / (sigma * sqrt(2*pi)) * exp(-(x-center)^2 / (2*sigma^2))",
    "lorentzian": "f(x) = area * gamma / (pi * ((x-center)^2 + gamma^2))",
    "voigt": "f(x) = area * (G_sigma * L_gamma)(x-center)\nG_sigma and L_gamma are unit-area Gaussian and Lorentzian profiles; * denotes convolution.",
    "pseudo_voigt": "f(x) = area * ((1-eta)*G_sigma(x-center) + eta*L_gamma(x-center))\nsigma = fwhm / (2*sqrt(2*ln(2))); gamma = fwhm / 2\nG_sigma and L_gamma have unit area.",
    "constant": "f(x) = offset",
    "linear": "f(x) = intercept + slope*x",
    "polynomial": "f(x) = c0 + c1*x + ... + cN*x^N",
    "cubic_spline": "f(x) = S(x), S(x_i) = y_i\nNatural cubic spline through the nodes (x_i, y_i); two nodes use linear interpolation.",
}


def function_formula(definition: FunctionDefinition) -> str:
    formula = definition.custom_metadata.get("formula")
    if formula:
        return "f(x) = " + str(formula)
    # Plugin identifiers may replace built-ins; do not claim a built-in formula
    # for a plugin implementation that has not supplied its own expression.
    if not definition.custom_metadata.get("plugin_owner"):
        return _FORMULAS.get(definition.identifier, "")
    return ""


def function_info_html(definition: FunctionDefinition) -> str:
    formula = function_formula(definition)
    parts = [
        f"<h2>{escape(definition.display_name)}</h2>",
        f"<p>{escape(definition.kind)} · {escape(definition.identifier)}</p>",
        "<h3>Formula</h3>",
        f"<pre>{escape(formula)}</pre>"
        if formula
        else "<p>The function provider has not supplied a formula.</p>",
    ]
    description = function_tooltip(definition)
    if description:
        parts.append(f"<p>{escape(description).replace(chr(10), '<br>')}</p>")
    parts.append("<h3>Initial parameters and bounds</h3>")
    if definition.identifier == "cubic_spline" and not definition.custom_metadata.get(
        "plugin_owner"
    ):
        parts.append(
            "<p>One y_i parameter per x node. Automatic insertion uses the data minimum, median and maximum x; point placement uses your selected nodes.</p>"
        )
    else:
        try:
            specs = definition.specs()
        except Exception:
            parts.append(
                "<p>Parameters depend on the configuration selected in Add function.</p>"
            )
        else:
            parts.append(
                "<table border='1' cellpadding='5'><tr><th>Name</th><th>Default</th><th>Minimum</th><th>Maximum</th><th>Unit</th></tr>"
            )
            for spec in specs:
                parts.append(
                    "<tr>"
                    + "".join(
                        f"<td>{escape(str(value))}</td>"
                        for value in (
                            spec.name,
                            spec.default,
                            spec.minimum,
                            spec.maximum,
                            spec.unit,
                        )
                    )
                    + "</tr>"
                )
            parts.append("</table>")
    if definition.derived:
        parts.append("<p>Derived quantities: " + escape(", ".join(definition.derived)) + "</p>")
    parts.append("<h3>Initialization</h3>")
    if definition.kind == "peak":
        parts.append(
            "<p><b>Initialize with points checked:</b> click the centre and drag horizontally to set the initial FWHM. Parameters remain free for fitting.</p><p><b>Unchecked:</b> each Add click inserts one peak estimated from the finite, unmasked data minus the current model. The most prominent positive or negative residual peak is used. Estimates remain editable.</p>"
        )
    else:
        parts.append(
            "<p><b>Initialize with points checked:</b> select graph points and press Finish. Point-initialized parameters start fixed.</p><p><b>Unchecked:</b> insert the normal initial parameters; spline nodes are estimated from the data.</p>"
        )
    parts.append(
        "<p>Defaults above describe the function definition; data-based estimates can differ. Background marks the added component as background. Use Add function to add this function with advanced options, or Model → Add component (Ctrl++).</p>"
    )
    return "".join(parts)


class FunctionInfoDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setObjectName("function_info_dialog")
        self.setWindowTitle(self.tr("Function details"))
        self.resize(700, 600)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.function_selector = QComboBox(self)
        self.function_selector.setObjectName("function_info_selector")
        self.function_selector.setToolTip(self.tr("Choose a function to inspect or add."))
        self.function_selector.currentIndexChanged.connect(self._function_selected)
        form.addRow(self.tr("Function:"), self.function_selector)
        layout.addLayout(form)
        self.browser = QTextBrowser(self)
        self.browser.setOpenLinks(False)
        layout.addWidget(self.browser)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self.copy_button = QPushButton(self.tr("Copy formula"), self)
        buttons.addButton(self.copy_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.add_button = buttons.addButton(
            self.tr("Add function…"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.add_button.setObjectName("function_info_add_button")
        self.add_button.setIcon(window.add_component_action.icon())
        self.add_button.setToolTip(self.tr("Add the selected function: choose its name, composition and initialization options."))
        self.add_button.clicked.connect(lambda: self._add_with_options(window))
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.formula))
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def _add_with_options(self, window):
        self.close()
        window.add_component()

    def _function_selected(self, index):
        identifier = self.function_selector.itemData(index)
        if not identifier:
            return
        window = self.parentWidget()
        # Browsing functions must not restart placement or insert a spline as
        # the toolbar's placement-aware selection handler can do.
        window.plot_workspace.cancel_placement()
        window._remember_quick_function(str(identifier))

    def set_function(self, definition):
        window = self.parentWidget()
        definitions = window.registry.values()
        identifiers = [item.identifier for item in definitions]
        with QSignalBlocker(self.function_selector):
            if identifiers != [self.function_selector.itemData(i) for i in range(self.function_selector.count())]:
                self.function_selector.clear()
                for item in definitions:
                    self.function_selector.addItem(item.display_name, item.identifier)
            for index, item in enumerate(definitions):
                self.function_selector.setItemText(index, item.display_name)
                self.function_selector.setItemData(index, function_tooltip(item), Qt.ItemDataRole.ToolTipRole)
            self.function_selector.setCurrentIndex(self.function_selector.findData(definition.identifier))
        self.function_selector.setToolTip(function_tooltip(definition) or self.tr("Choose a function to inspect or add."))
        self.formula = function_formula(definition)
        self.browser.setHtml(function_info_html(definition))
        self.copy_button.setEnabled(bool(self.formula))
        self.add_button.setEnabled(
            bool(window.active_curve_id)
            and not window.project.read_only
            and window.add_component_action.isEnabled()
        )


def sync_function_info(window, identifier):
    action = getattr(window, "function_info_action", None)
    if action is None:
        return
    definition = window.registry.get(identifier)
    formula = function_formula(definition)
    action.setToolTip(
        window.tr("Function details")
        + ": "
        + definition.display_name
        + ("\n" + formula if formula else "")
    )
    dialog = getattr(window, "_function_info_dialog", None)
    if dialog is not None:
        dialog.set_function(definition)


def show_function_info(window):
    identifier = window.quick_function_selector.currentData()
    if not identifier:
        return
    dialog = getattr(window, "_function_info_dialog", None)
    if dialog is None:
        dialog = FunctionInfoDialog(window)
        window._function_info_dialog = dialog
    dialog.set_function(window.registry.get(str(identifier)))
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
