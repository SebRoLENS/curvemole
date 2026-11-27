"""FunctionList, ModelPanel."""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.background_status import background_component_status
from curvemole.core.data import CurveState
from curvemole.core.expressions import SafeExpression
from curvemole.core.plugin_identity import function_tooltip
from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry
from curvemole.core.results_store import ResultKey
from curvemole.gui.background_role import BackgroundSwitch
from curvemole.gui.model_selection import COMPONENT_CURVE_ROLE  # noqa: E402
from curvemole.gui.parameter_limits import POSITIVE_BOUND_ROLE, positive_width_bound
from curvemole.gui.row_drag import RowDragMixin, RowDrop


class FunctionList(RowDragMixin, QListWidget):
    rowMoveRequested = Signal(str, object, str, bool)

    def __init__(self):
        super().__init__()
        self.setup_row_drag()

    def _row_drop_at(self, source, position):
        target = self.indexAt(position)
        if not target.isValid() and self.spacing():
            target = self.indexAt(position + QPoint(0, self.spacing()))
        if not target.isValid() and self.count():
            last = self.item(self.count() - 1)
            if position.y() > self.visualItemRect(last).bottom():
                target = self.indexFromItem(last)
        curve_id = source.data(COMPONENT_CURVE_ROLE)
        if not self.dragEnabled() or not curve_id or target.data(COMPONENT_CURVE_ROLE) != curve_id:
            return None
        rect = self.visualRect(target)
        after = position.y() >= rect.center().y()
        return RowDrop(target, after, 3, rect.bottom() + 1 if after else rect.top())

    def _request_row_move(self, source, drop, sources=()):
        refs = tuple((index.data(COMPONENT_CURVE_ROLE), index.data(Qt.ItemDataRole.UserRole))
                     for index in (sources or (source,)))
        self.rowMoveRequested.emit(
            source.data(COMPONENT_CURVE_ROLE),
            refs[0][1] if len(refs) == 1 else refs,
            drop.target.data(Qt.ItemDataRole.UserRole),
            drop.after,
        )


class ModelPanel(QWidget):
    displayMethodChanged = Signal(str)
    uncertaintyRequested = Signal()
    noteRequested = Signal(object)
    componentSelected = Signal(str)
    addRequested = Signal()
    duplicateRequested = Signal(str)
    deleteRequested = Signal(str)
    moveRequested = Signal(str, int)
    enabledRequested = Signal(str, bool)
    backgroundRequested = Signal(str, bool)
    compositionRequested = Signal(str, str, str)
    compositionOrderRequested = Signal(str)
    parameterChangeRequested = Signal(str, str, str, object)
    parameterLinkRequested = Signal(str, str)
    bulkFixedRequested = Signal(str, bool)
    copyFitRequested = Signal()
    copyFitNextRequested = Signal()
    descriptionRequested = Signal(str, str)
    renameRequested = Signal(str, str)
    editPointsRequested = Signal(str, str)
    reorderRequested = Signal()
    reorderRulesRequested = Signal()

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
        self.components = FunctionList()
        self.components.currentItemChanged.connect(self._component_selected)
        self.components.itemChanged.connect(self._component_enabled)
        self.components.setMinimumHeight(4 * self.components.fontMetrics().height() + 16)
        single_layout.addWidget(self.components, 1)
        self.composition_summary = QLabel()
        self.composition_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.composition_summary.setWordWrap(True)
        self.composition_summary.setMaximumHeight(60)
        single_layout.addWidget(self.composition_summary)
        self.calculation_order_button = QPushButton(self.tr("Calculation order…"))
        self.calculation_order_button.clicked.connect(
            lambda: self.compositionOrderRequested.emit(self._composition_curve_id)
            if getattr(self, "_composition_curve_id", None) else None)
        single_layout.addWidget(self.calculation_order_button)
        self.edit_points_action = None
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
            button.setAccessibleName(tooltip)  # screen readers would read only the symbol
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.reorder_button = QPushButton(self.tr("Reorder"))
        self.reorder_button.setToolTip(self.tr(
            "Sort the function list and renumber automatic names without changing the fit or calculation order."))
        self.reorder_button.clicked.connect(self.reorderRequested)
        buttons.addWidget(self.reorder_button)
        self.reorder_rules_button = QToolButton()
        self.reorder_rules_button.setText("⚙")
        self.reorder_rules_button.setToolTip(self.tr("Advanced reorder rules…"))
        self.reorder_rules_button.setAccessibleName(self.tr("Advanced reorder rules"))
        self.reorder_rules_button.clicked.connect(self.reorderRulesRequested)
        buttons.addWidget(self.reorder_rules_button)
        single_layout.addLayout(buttons)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        copy_button = QPushButton(self.tr("Copy fit…"))
        copy_button.clicked.connect(self.copyFitRequested)
        buttons.addWidget(copy_button)
        self.copy_fit_next_button = QPushButton(self.tr("Copy fit to next…"))
        self.copy_fit_next_button.clicked.connect(self.copyFitNextRequested)
        buttons.addWidget(self.copy_fit_next_button)
        single_layout.addLayout(buttons)
        self.background_group = QGroupBox(self.tr("No functions selected"))
        background_layout = QVBoxLayout(self.background_group)
        self.background_toggle = BackgroundSwitch(self.tr("Mark as background"))
        self.background_toggle.setAccessibleName(self.tr("Mark selected functions as background"))
        self.background_toggle.checkStateChanged.connect(
            lambda state: self._background_toggled(state == Qt.CheckState.Checked))
        background_layout.addWidget(self.background_toggle)
        single_layout.addWidget(self.background_group)
        self._sync_background_role([])
        from curvemole.gui.uncertainty_display import UncertaintyDisplayMenu

        self.display_method = UncertaintyDisplayMenu(self)
        self.display_method.methodSelected.connect(self.displayMethodChanged)
        self.display_method.analysisRequested.connect(self.uncertaintyRequested)
        self.parameters = QTableWidget(0, 8)
        self.parameters.setHorizontalHeaderLabels(
            [
                self.tr("Parameter"),
                self.tr("Value"),
                self.tr("±1σ"),
                self.tr("Analysis − / + ▾"),
                self.tr("Fixed"),
                self.tr("Lower"),
                self.tr("Upper"),
                self.tr("Link"),
            ]
        )
        self.parameters.horizontalHeaderItem(3).setToolTip(
            self.tr("Click to choose the displayed uncertainty. ") + self.display_method.toolTip())
        self.parameters.horizontalHeader().setSectionsClickable(True)
        self.parameters.horizontalHeader().sectionClicked.connect(self._show_uncertainty_menu)
        self.parameters.itemChanged.connect(self._parameter_changed)
        # The parameter table is the main editing surface: keep about five rows
        # visible. On short screens the panel scrolls instead of squeezing it.
        row_height = self.parameters.verticalHeader().defaultSectionSize()
        self.parameters.setMinimumHeight(self.parameters.horizontalHeader().sizeHint().height() + 5 * row_height + 6)
        single_layout.addWidget(self.parameters, 2)
        fixed_buttons = QHBoxLayout()
        self.lock_all_parameters_button = QPushButton(self.tr("Lock all"))
        self.unlock_all_parameters_button = QPushButton(self.tr("Unlock all"))
        self.lock_all_parameters_button.setToolTip(
            self.tr("Fix every parameter in the selected component during fitting.")
        )
        self.unlock_all_parameters_button.setToolTip(
            self.tr("Allow every parameter in the selected component to vary during fitting.")
        )
        self.lock_all_parameters_button.clicked.connect(lambda: self._bulk_fixed(True))
        self.unlock_all_parameters_button.clicked.connect(lambda: self._bulk_fixed(False))
        fixed_buttons.addWidget(self.lock_all_parameters_button)
        fixed_buttons.addWidget(self.unlock_all_parameters_button)
        fixed_buttons.addStretch(1)
        single_layout.addLayout(fixed_buttons)
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
        self.components.setDragEnabled(not project.read_only)
        self.display_method.set_context(project, curve_id)
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
            for row, component in enumerate(model.display_components):
                label = component.name
                tooltip = ""
                if component.is_background:
                    label += self.tr("  ·  Background")
                    background_status = background_component_status(curve, component, model, self.registry)
                    if background_status == "subtracted":
                        label += self.tr("  ·  Subtracted")
                        tooltip = self.tr(
                            "Background status: subtracted from this spectrum. "
                            "The subtraction keeps the values used at that time; editing or "
                            "copying parameter values does not subtract the function again."
                        )
                    elif background_status == "unresolved":
                        label += self.tr("  ·  Subtraction recorded — function uncertain")
                        tooltip = self.tr(
                            "A background subtraction is recorded for this spectrum, but the saved "
                            "history cannot identify this function unambiguously. Revert background "
                            "uses the stored subtraction array; the data have not been changed."
                        )
                    else:
                        label += self.tr("  ·  Not subtracted")
                        tooltip = self.tr(
                            "Background status: present in the model and not subtracted "
                            "from this spectrum."
                        )
                if component.function_id in self.registry.identifiers():
                    definition = self.registry.get(component.function_id)
                    symbol = definition.custom_metadata.get("plugin_symbol", "")
                    if symbol and not label.startswith(symbol + " "):
                        label = symbol + " " + label
                    function_help = function_tooltip(definition)
                    tooltip = "\n\n".join(part for part in (function_help, tooltip) if part)
                item = QListWidgetItem(label)
                if tooltip:
                    item.setToolTip(tooltip)
                item.setData(Qt.ItemDataRole.UserRole, component.id)
                item.setData(COMPONENT_CURVE_ROLE, curve.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if component.enabled else Qt.CheckState.Unchecked)
                if component.is_background:
                    dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
                    item.setForeground(QColor("#63D7C4" if dark else "#087565"))
                    font = item.font()
                    font.setWeight(QFont.Weight.DemiBold)
                    item.setFont(font)
                self.components.addItem(item)
                if component.id == selected_component_id:
                    selected_row = row
            if self.components.count():
                self.components.setCurrentRow(selected_row)
        finally:
            self._updating = False
        self.refresh_parameters()

    def _show_uncertainty_menu(self, section: int) -> None:
        if section != 3 or not self.display_method.isEnabled():
            return
        header = self.parameters.horizontalHeader()
        point = QPoint(header.sectionViewportPosition(section), header.height())
        self.display_method.popup(header.viewport().mapToGlobal(point))

    def refresh_parameters(self) -> None:
        self.display_method.set_context(self.project, self.curve_id)
        self._updating = True
        try:
            self.parameters.setRowCount(0)
            component_id = self.selected_component_id()
            if not component_id or not self.project or not self.curve_id:
                self._sync_background_role([])
                if self.edit_points_action is not None:
                    self.edit_points_action.setEnabled(False)
                self.derived.clear()
                return
            model = self.project.model_for(self.curve_id)
            component = model.component(component_id)
            from curvemole.gui.edit_function_points import can_edit_points
            editable = not self.project.read_only and can_edit_points(component, self.registry)
            if self.edit_points_action is not None:
                self.edit_points_action.setEnabled(editable)
            self._sync_background_role([component.is_background])
            self.parameters.setRowCount(len(component.parameters))
            from curvemole.core.analysis_errors import (
                DISPLAY_METHODS,
                display_method,
                recorded_analysis_error,
                recorded_analysis_interval,
            )
            from curvemole.core.background_uncertainty import (
                background_uncertainty_is_current,
                background_uncertainty_note,
                background_uncertainty_record,
            )

            chosen = display_method(self.project)
            report = self.project.results.get(ResultKey.UNCERTAINTY_REPORTS_BY_CURVE, {}).get(
                self.curve_id, {}).get(chosen, {}) if chosen else {}
            recorded_analysis = report.get("analysis", {})
            if hasattr(recorded_analysis, "to_dict"):
                recorded_analysis = recorded_analysis.to_dict()
            confidence = recorded_analysis.get("confidence_level", recorded_analysis.get("settings", {}).get("confidence_level"))
            baseline = report.get("baseline", {})
            if hasattr(baseline, "to_dict"):
                baseline = baseline.to_dict(arrays=False)
            background_note = background_uncertainty_note(baseline)
            treatment = background_uncertainty_record(baseline)
            outdated = (not background_uncertainty_is_current(self.project, treatment) if treatment
                        else self.project.dataset.curve(self.curve_id).state != CurveState.FITTED)
            provenance = DISPLAY_METHODS[chosen] if chosen else self.tr("No analysis selected")
            if confidence is not None:
                provenance += f" ({confidence:.1%} confidence)"
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
                path = model.parameter_path(self.curve_id, component.id, name)
                offsets = recorded_analysis_error(self.project, self.curve_id, path)
                text = f"−{offsets[0]:.5g} / +{offsets[1]:.5g}" if offsets else "—"
                if offsets and outdated:
                    text = self.tr("Recorded: ") + text
                separate_interval = recorded_analysis_interval(report, chosen, path) if treatment else None
                if separate_interval:
                    center, lower, upper = separate_interval
                    if lower <= center <= upper:
                        text = f"{center:.8g}  −{center - lower:.5g} / +{upper - center:.5g}"
                    else:
                        text = f"{center:.8g}  [{lower:.8g}, {upper:.8g}]"
                    if outdated:
                        text = self.tr("Recorded: ") + text
                analysis_item = QTableWidgetItem(
                    text)
                analysis_item.setFlags(analysis_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                analysis_item.setForeground(QColor("#9b6500" if outdated else "#2877b7"))
                analysis_item.setToolTip(
                    self.tr("Calculated with {method}. Negative and positive errors are "
                            "distances from the fitted value to the confidence limits.")
                    .format(method=provenance) if offsets else
                    self.tr("{method}: no valid interval for this parameter.")
                    .format(method=provenance))
                if offsets and outdated:
                    recorded_value = baseline.get("parameters", {}).get(path, {}).get("value")
                    analysis_item.setToolTip(analysis_item.toolTip() + "\n" + self.tr(
                        "Historical result around recorded fit value {value}. Data/model have changed; "
                        "these are not uncertainties of the current fit. Refit and rerun the analysis."
                    ).format(value=f"{recorded_value:.12g}"))
                if background_note:
                    analysis_item.setToolTip(background_note + "\n" + self.tr(
                        "This column shows the separate fit value and its interval. "
                        "Open Uncertainty for the full report."))
                    if separate_interval and outdated:
                        analysis_item.setToolTip(analysis_item.toolTip() + "\n" + self.tr(
                            "Historical result. The spectrum or model has changed since this analysis."))
                self.parameters.setItem(row, 3, analysis_item)
                equality_linked = bool(parameter.link and parameter.link_relation == "equal")
                fixed_value = parameter.fixed and not equality_linked
                fixed = QTableWidgetItem(self.tr("Linked") if equality_linked else "🔒" if fixed_value else "")
                fixed.setFlags((fixed.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable)
                fixed.setCheckState(Qt.CheckState.Checked if fixed_value else Qt.CheckState.Unchecked)
                if equality_linked:
                    fixed.setToolTip(self.tr(
                        "This value is controlled by an equality link, not Fixed. "
                        "Remove the link in the Link column first, then set the value and select Fixed."
                    ))
                fixed.setData(Qt.ItemDataRole.UserRole, (component.id, name, "fixed"))
                self.parameters.setItem(row, 4, fixed)
                positive_floor, show_zero = positive_width_bound(self.registry, component, parameter)
                lower_text = ("0" if show_zero else "" if math.isinf(parameter.minimum)
                              else f"{parameter.minimum:.12g}")
                lower = QTableWidgetItem(lower_text)
                lower.setData(Qt.ItemDataRole.UserRole, (component.id, name, "minimum"))
                if positive_floor is not None:
                    lower.setData(POSITIVE_BOUND_ROLE, positive_floor)
                    help_text = self.tr(
                        "{parameter} must be greater than zero. Enter 0, or leave this bound blank, "
                        "to use its automatic positive numerical limit. "
                        "This is a lower bound, not a fixed parameter value.").format(parameter=name)
                    if show_zero:
                        help_text += "\n" + self.tr(
                            "0 represents strict positivity (> 0); the numerical lower limit "
                            "used internally is {value}.").format(value=f"{parameter.minimum:.12g}")
                    lower.setToolTip(help_text)
                self.parameters.setItem(row, 5, lower)
                upper = QTableWidgetItem("" if math.isinf(parameter.maximum) else f"{parameter.maximum:.12g}")
                upper.setData(Qt.ItemDataRole.UserRole, (component.id, name, "maximum"))
                self.parameters.setItem(row, 6, upper)
                link_button = QPushButton(self._link_button_text(
                    parameter.link, parameter.link_relation,
                    parameter.link_tolerance, parameter.link_tolerance_mode))
                link_button.setToolTip(self._link_tooltip(parameter))
                link_button.clicked.connect(
                    lambda checked=False, component_id=component.id, parameter_name=name: (
                        self.parameterLinkRequested.emit(component_id, parameter_name)
                    )
                )
                self.parameters.setCellWidget(row, 7, link_button)
            self.parameters.resizeColumnsToContents()
            if component.function_id not in self.registry.identifiers():
                self.derived.setText(self.tr("Function unavailable — enable its plugin in File → Plugin Manager."))
                return
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

    def _sync_background_role(self, states) -> None:
        """Bind the switch explicitly to the current function selection."""
        count = len(states)
        self.background_group.setTitle(
            self.tr("Selected functions: {count}").format(count=count)
            if count else self.tr("No functions selected"))
        mixed = bool(states) and any(states) and not all(states)
        toggle = self.background_toggle
        was_blocked = toggle.blockSignals(True)
        try:
            toggle.setTristate(mixed)
            toggle.setCheckState(Qt.CheckState.PartiallyChecked if mixed else
                                 Qt.CheckState.Checked if states and all(states) else
                                 Qt.CheckState.Unchecked)
            toggle.setEnabled(bool(count) and self.project is not None and not self.project.read_only)
        finally:
            toggle.blockSignals(was_blocked)
        help_text = self.tr(
            "Applies to all currently selected functions. "
            "Marks them as background without subtracting them or changing whether they are enabled.")
        if mixed:
            help_text += "\n" + self.tr(
                "Mixed selection: click to mark all selected functions as background; "
                "click again to remove the mark from all of them.")
        elif not count:
            help_text = self.tr("Select one or more functions to change their background role.")
        toggle.setToolTip(help_text)
        toggle.setAccessibleDescription(help_text)
        toggle.update()

    def _link_button_text(self, link: str | None, relation: str = "equal",
                          tolerance: float = 0.0, tolerance_mode: str = "absolute") -> str:
        if not link:
            return self.tr("Set link…")
        if self.project is None:
            return self.tr("Linked…")
        try:
            expression = SafeExpression.compile(link)
            references = expression.references
            if len(references) != 1:
                return self.tr("Linked (advanced)…")
            curve_id, component_id, parameter_name = references[0].split(".", 2)
            curve = self.project.dataset.curve(curve_id)
            component = self.project.model_for(curve_id).component(component_id)
            exact = link.strip() == f"${{{references[0]}}}"
            if relation != "equal":
                symbol = {"lower": "≥", "upper": "≤", "similar": "≈"}[relation]
                suffix = f" (± {tolerance:g}{'%' if tolerance_mode == 'percent' else ''})" if relation == "similar" else ""
                return f"{symbol} {curve.name} / {component.name} / {parameter_name}{suffix}"
            prefix = self.tr("Linked → ") if exact else self.tr("Linked (advanced) → ")
            return prefix + f"{curve.name} / {component.name} / {parameter_name}"
        except Exception:
            return self.tr("Linked (advanced)…")

    def _link_tooltip(self, parameter) -> str:
        if not parameter.link or self.project is None:
            return self.tr("Choose a source parameter or a parameter-dependent bound")
        expression = parameter.link
        try:
            for path in SafeExpression.compile(expression).references:
                curve_id, component_id, name = path.split(".", 2)
                curve = self.project.dataset.curve(curve_id)
                component = self.project.model_for(curve_id).component(component_id)
                expression = expression.replace(f"${{{path}}}", f"{curve.name} / {component.name}.{name}")
            symbol = {"equal": "=", "lower": "≥", "upper": "≤", "similar": "≈"}[parameter.link_relation]
            text = f"{parameter.name} {symbol} {expression}"
            if parameter.link_relation == "similar":
                unit = "% of the source's absolute value" if parameter.link_tolerance_mode == "percent" else parameter.unit
                text += f" (± {parameter.link_tolerance:g} {unit})"
            return text
        except Exception:
            return expression

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
            elif field == "minimum":
                value = float(item.text()) if item.text().strip() else -math.inf
                positive_floor = item.data(POSITIVE_BOUND_ROLE)
                if positive_floor is not None:
                    if not item.text().strip() or value == 0:
                        value = positive_floor
                    elif value < 0:
                        QMessageBox.warning(self, self.tr("Parameter"), self.tr(
                            "{parameter} must remain greater than zero. "
                            "Use 0 for its automatic positive lower limit.").format(parameter=name))
                        self.refresh_parameters()
                        return
            elif field == "maximum":
                value = float(item.text()) if item.text().strip() else math.inf
            else:
                value = float(item.text())
        except ValueError:
            QMessageBox.warning(self, self.tr("Parameter"), self.tr("Enter a valid number."))
            self.refresh_parameters()
            return
        self.parameterChangeRequested.emit(component_id, name, field, value)

