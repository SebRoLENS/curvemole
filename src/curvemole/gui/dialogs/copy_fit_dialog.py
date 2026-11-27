"""CopyFitDialog."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.project import Project
from curvemole.gui.dialogs._shared import (
    _name_accept,
    _set_list_checked,
)
from curvemole.gui.parameter_link import ParameterLinkDialog  # noqa: E402, F401


class CopyFitDialog(QDialog):
    def __init__(self, project: Project, source_curve_id: str, parent: QWidget | None = None, *, next_curve_id: str | None = None) -> None:
        super().__init__(parent)
        self.resize(640, 780)
        self.setWindowTitle(self.tr("Copy fit"))
        layout = QVBoxLayout(self)
        source = project.dataset.curve(source_curve_id)
        source_label = QLabel(self.tr("Source: ") + source.name)
        source_label.setTextFormat(Qt.TextFormat.PlainText)
        source_label.setWordWrap(True)
        layout.addWidget(source_label)
        from curvemole.gui.series_groups import add_scope, style_heading

        add_scope(self, layout, project, source_curve_id, self._filter_series)
        self.targets = QListWidget()
        self.targets.setAlternatingRowColors(True)
        self.targets.setSpacing(3)
        self._target_series = {}
        for series in project.dataset.series:
            curves = [curve for curve in series.curves if curve.id != source_curve_id]
            if not curves:
                continue
            heading = QListWidgetItem(series.name)
            style_heading(heading, self.targets)
            self.targets.addItem(heading)
            self._target_series[self.targets.count() - 1] = series.id
            for curve in curves:
                item = QListWidgetItem("    " + curve.name)
                item.setData(Qt.ItemDataRole.UserRole, curve.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if curve.id == next_curve_id else Qt.CheckState.Unchecked)
                self.targets.addItem(item)
                self._target_series[self.targets.count() - 1] = series.id
        self._filter_series()
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
        layout.addWidget(QLabel(self.tr("Functions to copy — check to include:")))
        self.functions = QListWidget()
        self.functions.setMaximumHeight(160)
        self._background_functions = set()
        for component in project.model_for(source_curve_id).display_components:
            label = component.name + " — " + component.operator
            if component.is_background:
                label += self.tr(" (background)")
                self._background_functions.add(component.id)
            if not component.enabled:
                label += self.tr(" (disabled in model)")
            item = QListWidgetItem(label, self.functions)
            item.setData(Qt.ItemDataRole.UserRole, component.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
        layout.addWidget(self.functions)
        function_buttons = QHBoxLayout()
        self.select_all_functions_button = QPushButton(self.tr("Select all functions"))
        self.clear_functions_button = QPushButton(self.tr("Clear functions"))
        self.select_all_functions_button.clicked.connect(lambda: _set_list_checked(self.functions, True))
        self.clear_functions_button.clicked.connect(lambda: _set_list_checked(self.functions, False))
        function_buttons.addWidget(self.select_all_functions_button)
        function_buttons.addWidget(self.clear_functions_button)
        layout.addLayout(function_buttons)
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
        self.function_summary = QLabel()
        self.function_summary.setWordWrap(True)
        layout.addWidget(self.function_summary)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        _name_accept(self.buttons, self.tr("Copy"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.functions.itemChanged.connect(self._update_function_selection)
        for widget in (self.structure, self.background, self.masks, self.ranges):
            widget.toggled.connect(self._update_function_selection)
        self._update_function_selection()

    def _update_function_selection(self, *_args):
        for row in range(self.functions.count()):
            item = self.functions.item(row)
            item.setHidden(item.data(Qt.ItemDataRole.UserRole) in self._background_functions
                           and not self.background.isChecked())
        count = len(self._selected_functions())
        text = str(count) + self.tr(" function(s) selected. ")
        text += self.tr("Component structure replaces each target model with these functions, including their composition and calculation order.") if self.structure.isChecked() else self.tr(
            "With structure off, only corresponding target functions are updated; other target functions stay unchanged.")
        self.function_summary.setText(text)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            count > 0 or self.masks.isChecked() or self.ranges.isChecked())

    def _selected_functions(self):
        return [self.functions.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.functions.count())
                if not self.functions.item(row).isHidden()
                and self.functions.item(row).checkState() == Qt.CheckState.Checked]

    def _filter_series(self):
        for row, series_id in self._target_series.items():
            self.targets.item(row).setHidden(not self.all_series.isChecked() and series_id != self.scope_series_id)

    def choices(self) -> tuple[list[str], dict[str, Any]]:
        targets = [
            str(self.targets.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.targets.count())
            if not self.targets.item(index).isHidden() and self.targets.item(index).data(Qt.ItemDataRole.UserRole)
            and self.targets.item(index).checkState() == Qt.CheckState.Checked
        ]
        return targets, {
            "structure": self.structure.isChecked(),
            "values": self.values.isChecked(),
            "bounds_and_fixed": self.bounds.isChecked(),
            "links": self.links.isChecked(),
            "background": self.background.isChecked(),
            "masks": self.masks.isChecked(),
            "fit_ranges": self.ranges.isChecked(),
            "component_ids": self._selected_functions(),
        }
