"""Project-wide destination picker for parameter copying.

This module replaces the old Ctrl/Shift target-selection workflow while keeping
CurveMole's existing copy engine, undo semantics, and optional constraint copy.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from curvemole.gui import parameter_copy as _legacy
from curvemole.gui.main_window import MainWindow
from curvemole.gui.panels import ModelPanel


def _all_component_refs(window: MainWindow) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for curve in window.project.curves:
        model = window.project.model_for(curve.id)
        refs.extend((str(curve.id), str(component.id)) for component in model.components)
    return refs


def _normalise_source(
    refs_or_source: tuple[str, str] | list[tuple[str, str]],
    current_ref: tuple[str, str] | None,
) -> tuple[str, str]:
    """Accept both the redesigned and the historical dialog constructor forms."""
    if isinstance(refs_or_source, tuple) and len(refs_or_source) == 2:
        return str(refs_or_source[0]), str(refs_or_source[1])
    refs = [(str(curve_id), str(component_id)) for curve_id, component_id in refs_or_source]
    if current_ref is not None:
        candidate = (str(current_ref[0]), str(current_ref[1]))
        if candidate in refs:
            return candidate
    if not refs:
        raise ValueError("A source function is required")
    return refs[0]


class CopyParameterDialog(QDialog):
    """Choose a source parameter, then explicit project-wide target functions."""

    def __init__(
        self,
        window: MainWindow,
        refs_or_source: tuple[str, str] | list[tuple[str, str]],
        current_ref: tuple[str, str] | None = None,
        current_parameter: str | None = None,
    ) -> None:
        super().__init__(window)
        self.window = window
        self._source_ref = _normalise_source(refs_or_source, current_ref)
        self._all_refs = _all_component_refs(window)
        self.setWindowTitle(self.tr("Copy parameter"))
        self.resize(620, 540)

        layout = QVBoxLayout(self)
        self.source_summary = QLabel()
        self.source_summary.setWordWrap(True)
        layout.addWidget(self.source_summary)

        self.parameter = QComboBox()
        source_curve_id, source_component_id = self._source_ref
        source_component = window.project.model_for(source_curve_id).component(source_component_id)
        for name in source_component.parameters:
            self.parameter.addItem(name, name)
        if current_parameter:
            index = self.parameter.findData(current_parameter)
            if index >= 0:
                self.parameter.setCurrentIndex(index)

        parameter_row = QHBoxLayout()
        parameter_row.addWidget(QLabel(self.tr("Parameter:")))
        parameter_row.addWidget(self.parameter, 1)
        layout.addLayout(parameter_row)

        layout.addWidget(QLabel(self.tr("Target functions in this project:")))
        self.targets = QListWidget()
        self.targets.setMinimumHeight(180)
        layout.addWidget(self.targets, 1)

        selection_buttons = QHBoxLayout()
        self.select_all_button = QPushButton(self.tr("Select all compatible"))
        self.clear_button = QPushButton(self.tr("Clear selection"))
        self.select_all_button.clicked.connect(self._select_all_compatible)
        self.clear_button.clicked.connect(self._clear_selection)
        selection_buttons.addWidget(self.select_all_button)
        selection_buttons.addWidget(self.clear_button)
        selection_buttons.addStretch(1)
        layout.addLayout(selection_buttons)

        layout.addWidget(QLabel(self.tr("Also copy:")))
        self.copy_fixed = QCheckBox(self.tr("Fixed/free state"))
        self.copy_bounds = QCheckBox(self.tr("Lower and upper bounds"))
        self.copy_link = QCheckBox(self.tr("Link / relation constraint"))
        layout.addWidget(self.copy_fixed)
        layout.addWidget(self.copy_bounds)
        layout.addWidget(self.copy_link)

        note = QLabel(
            self.tr(
                "The numerical value is always copied. If the optional boxes are left unchecked, "
                "each target keeps its current fixed state, bounds, and relation. Functions without "
                "the selected parameter cannot be chosen."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.copy_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.parameter.currentIndexChanged.connect(self._parameter_changed)
        self.copy_bounds.toggled.connect(lambda *_: self._refresh_targets(preserve=True))
        self.targets.itemChanged.connect(lambda *_: self._refresh_summary())
        self._refresh_targets(preserve=False)
        self._refresh_source_summary()
        self._refresh_summary()

    def source_ref(self) -> tuple[str, str]:
        return self._source_ref

    def parameter_name(self) -> str:
        value = self.parameter.currentData()
        return "" if value is None else str(value)

    def target_refs(self) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for row in range(self.targets.count()):
            item = self.targets.item(row)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            value = item.data(Qt.ItemDataRole.UserRole)
            if value is not None:
                result.append((str(value[0]), str(value[1])))
        return result

    def _parameter_changed(self) -> None:
        self._refresh_targets(preserve=False)
        self._refresh_source_summary()
        self._refresh_summary()

    def _refresh_source_summary(self) -> None:
        name = self.parameter_name()
        if not name:
            self.source_summary.clear()
            return
        curve_id, component_id = self._source_ref
        component = self.window.project.model_for(curve_id).component(component_id)
        parameter = component.parameters[name]
        self.source_summary.setText(
            self.tr("Parameter '")
            + name
            + self.tr("' of function '")
            + component.name
            + self.tr("' (")
            + f"{parameter.value:.12g}"
            + self.tr(") will be copied to:")
        )

    def _refresh_targets(self, *, preserve: bool) -> None:
        selected = set(self.target_refs()) if preserve else set()
        name = self.parameter_name()
        source_curve_id, source_component_id = self._source_ref
        source = self.window.project.model_for(source_curve_id).component(source_component_id)
        source_parameter = source.parameters.get(name) if name else None

        self.targets.blockSignals(True)
        try:
            self.targets.clear()
            for ref in self._all_refs:
                if ref == self._source_ref:
                    continue
                curve_id, component_id = ref
                component = self.window.project.model_for(curve_id).component(component_id)
                target = component.parameters.get(name) if name else None
                label = _legacy._component_label(self.window, ref)
                available = target is not None and source_parameter is not None
                if target is None:
                    label += self.tr("  — parameter unavailable")
                elif (
                    source_parameter is not None
                    and not self.copy_bounds.isChecked()
                    and not target.minimum <= source_parameter.value <= target.maximum
                ):
                    available = False
                    label += self.tr("  — value outside current bounds")

                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, ref)
                flags = item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                if available:
                    flags |= Qt.ItemFlag.ItemIsEnabled
                else:
                    flags &= ~Qt.ItemFlag.ItemIsEnabled
                item.setFlags(flags)
                item.setCheckState(
                    Qt.CheckState.Checked if available and ref in selected else Qt.CheckState.Unchecked
                )
                self.targets.addItem(item)
        finally:
            self.targets.blockSignals(False)
        self._refresh_summary()

    def _select_all_compatible(self) -> None:
        self.targets.blockSignals(True)
        try:
            for row in range(self.targets.count()):
                item = self.targets.item(row)
                if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                    item.setCheckState(Qt.CheckState.Checked)
        finally:
            self.targets.blockSignals(False)
        self._refresh_summary()

    def _clear_selection(self) -> None:
        self.targets.blockSignals(True)
        try:
            for row in range(self.targets.count()):
                self.targets.item(row).setCheckState(Qt.CheckState.Unchecked)
        finally:
            self.targets.blockSignals(False)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        count = len(self.target_refs())
        self.copy_button.setEnabled(bool(self.parameter_name()) and count > 0)
        if count:
            self.summary.setText(str(count) + " " + self.tr("target function(s) selected."))
            self.copy_button.setText(
                self.tr("Copy to ") + str(count) + self.tr(" function(s)")
            )
        else:
            self.summary.setText(self.tr("Select at least one target function."))
            self.copy_button.setText(self.tr("Copy parameter"))


def _component_name(panel: ModelPanel, ref: tuple[str, str]) -> str:
    if panel.project is None:
        return panel.tr("selected function")
    try:
        return panel.project.model_for(ref[0]).component(ref[1]).name
    except Exception:
        return panel.tr("selected function")


def _update_button(panel: ModelPanel) -> None:
    button = getattr(panel, "copy_parameter_button", None)
    if button is None:
        return
    refs = panel.selected_component_refs()
    if not refs:
        button.setEnabled(False)
        button.setText(panel.tr("First select a function"))
        button.setToolTip(panel.tr("Select one source function, then choose Copy parameter."))
        return
    if len(refs) != 1:
        button.setEnabled(False)
        button.setText(panel.tr("Select a single source function"))
        button.setToolTip(
            panel.tr("Target functions are chosen in the Copy parameter window, not with Ctrl/Shift.")
        )
        return

    source_ref = refs[0]
    remembered_source = getattr(panel, "_parameter_copy_source_ref", None)
    remembered_parameter = getattr(panel, "_parameter_copy_parameter_name", None)
    button.setEnabled(True)
    if remembered_source == source_ref and remembered_parameter:
        button.setText(
            panel.tr("Copy '")
            + str(remembered_parameter)
            + panel.tr("' from ")
            + _component_name(panel, source_ref)
            + "…"
        )
    else:
        button.setText(panel.tr("Copy parameter from ") + _component_name(panel, source_ref) + "…")
    button.setToolTip(
        panel.tr(
            "Open a project-wide target list. The value is always copied; fixed/free state, bounds, "
            "and link/relation constraints are optional."
        )
    )


def _copy_selected(panel: ModelPanel) -> None:
    refs = panel.selected_component_refs()
    if len(refs) != 1:
        QMessageBox.information(
            panel,
            panel.tr("Copy parameter"),
            panel.tr("First select a single source function."),
        )
        return
    window = panel.window()
    if not isinstance(window, MainWindow) or not window._ensure_editable():
        return

    source_ref = refs[0]
    remembered_source = getattr(panel, "_parameter_copy_source_ref", None)
    remembered_parameter = getattr(panel, "_parameter_copy_parameter_name", None)
    parameter_hint = remembered_parameter if remembered_source == source_ref else None
    dialog = CopyParameterDialog(window, source_ref, current_parameter=parameter_hint)
    if dialog.exec() != dialog.DialogCode.Accepted:
        return
    try:
        result = _legacy.copy_parameter_to_refs(
            window,
            dialog.source_ref(),
            dialog.target_refs(),
            dialog.parameter_name(),
            copy_fixed=dialog.copy_fixed.isChecked(),
            copy_bounds=dialog.copy_bounds.isChecked(),
            copy_link=dialog.copy_link.isChecked(),
        )
    except Exception as exc:
        window._show_error(window.tr("Copy parameter"), exc)
        return
    _legacy._show_copy_result(window, result, dialog.parameter_name())


def _install() -> None:
    # Keep the established import path working for tests/plugins.
    _legacy.CopyParameterDialog = CopyParameterDialog
    ModelPanel._update_copy_parameter_button = _update_button
    ModelPanel._copy_parameter_to_selected = _copy_selected


_install()
