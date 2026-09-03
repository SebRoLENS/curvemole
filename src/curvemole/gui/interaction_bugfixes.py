"""Targeted GUI bug fixes for parameter copying and wheel navigation."""

from __future__ import annotations

from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
)

from curvemole.gui.main_window import MainWindow
from curvemole.gui.panels import ModelPanel
from curvemole.gui.parameter_copy import (
    _component_label,
    _show_copy_result,
    copy_parameter_to_refs,
)
from curvemole.gui.plot import MaskViewBox, PlotWorkspace


def _all_component_refs(window: MainWindow) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for curve in window.project.curves:
        model = window.project.model_for(curve.id)
        refs.extend((str(curve.id), str(component.id)) for component in model.components)
    return refs


def _current_parameter_name(panel: ModelPanel) -> str | None:
    row = panel.parameters.currentRow()
    if row < 0 and panel.parameters.rowCount():
        row = 0
    if row < 0:
        return None
    value_item = panel.parameters.item(row, 1)
    metadata = value_item.data(Qt.ItemDataRole.UserRole) if value_item is not None else None
    if not metadata:
        return None
    return str(metadata[1])


class ProjectParameterCopyDialog(QDialog):
    """Copy one already-selected parameter to checked functions in the project."""

    def __init__(
        self,
        window: MainWindow,
        source_ref: tuple[str, str],
        parameter_name: str,
    ) -> None:
        super().__init__(window)
        self.window = window
        self._source_ref = source_ref
        self._parameter_name = parameter_name
        self.setWindowTitle(self.tr("Copy parameter"))
        self.resize(620, 520)

        curve_id, component_id = source_ref
        component = window.project.model_for(curve_id).component(component_id)
        source = component.parameters[parameter_name]

        layout = QVBoxLayout(self)
        intro = QLabel(
            self.tr("Parameter '")
            + parameter_name
            + self.tr("' of function '")
            + component.name
            + self.tr("' (")
            + f"{source.value:.12g}"
            + self.tr(") will be copied to:")
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.targets = QListWidget()
        self.targets.setMinimumHeight(190)
        for ref in _all_component_refs(window):
            if ref == source_ref:
                continue
            target_curve_id, target_component_id = ref
            target_component = window.project.model_for(target_curve_id).component(target_component_id)
            item = QListWidgetItem(_component_label(window, ref))
            item.setData(Qt.ItemDataRole.UserRole, ref)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if parameter_name not in target_component.parameters:
                item.setText(item.text() + self.tr("  — parameter not available"))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setCheckState(Qt.CheckState.Unchecked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            self.targets.addItem(item)
        layout.addWidget(self.targets)

        select_note = QLabel(
            self.tr("Check one or more destination functions. The numerical value is always copied.")
        )
        select_note.setWordWrap(True)
        layout.addWidget(select_note)

        self.copy_fixed = QCheckBox(self.tr("Also copy fixed/free state"))
        self.copy_bounds = QCheckBox(self.tr("Also copy lower and upper bounds"))
        self.copy_link = QCheckBox(self.tr("Also copy link / relation"))
        layout.addWidget(self.copy_fixed)
        layout.addWidget(self.copy_bounds)
        layout.addWidget(self.copy_link)

        bounds_note = QLabel(
            self.tr(
                "Without 'copy bounds', a destination is skipped if the source value lies outside "
                "its existing bounds. Functions without this parameter cannot be selected."
            )
        )
        bounds_note.setWordWrap(True)
        layout.addWidget(bounds_note)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.copy_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.copy_button.setText(self.tr("Copy parameter"))
        self.copy_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.targets.itemChanged.connect(lambda *_: self._refresh_summary())
        self._refresh_summary()

    def source_ref(self) -> tuple[str, str]:
        return self._source_ref

    def parameter_name(self) -> str:
        return self._parameter_name

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

    def _refresh_summary(self) -> None:
        count = len(self.target_refs())
        self.copy_button.setEnabled(count > 0)
        self.summary.setText(
            self.tr("Selected destinations: ") + str(count)
            if count
            else self.tr("Select at least one destination function.")
        )


def _install_parameter_copy_presentation() -> None:
    def remember_source(
        panel: ModelPanel,
        row: int,
        column: int,
        previous_row: int,
        previous_column: int,
    ) -> None:
        del column, previous_row, previous_column
        if panel._updating or row < 0:
            return
        refs = panel.selected_component_refs()
        if len(refs) != 1:
            panel._update_copy_parameter_button()
            return
        name = _current_parameter_name(panel)
        if name is not None:
            panel._parameter_copy_source_ref = refs[0]
            panel._parameter_copy_parameter_name = name
        panel._update_copy_parameter_button()

    def update_button(panel: ModelPanel) -> None:
        button = getattr(panel, "copy_parameter_button", None)
        if button is None:
            return
        refs = panel.selected_component_refs()
        if not refs:
            button.setEnabled(False)
            button.setText(panel.tr("First select a function"))
            button.setToolTip(panel.tr("Select one source function, then choose the parameter to copy."))
            return
        if len(refs) != 1:
            button.setEnabled(False)
            button.setText(panel.tr("Select one source function"))
            button.setToolTip(panel.tr("Destination functions are selected in the copy window."))
            return

        name = _current_parameter_name(panel)
        if name is None:
            button.setEnabled(False)
            button.setText(panel.tr("Select a parameter to copy"))
            return
        panel._parameter_copy_source_ref = refs[0]
        panel._parameter_copy_parameter_name = name
        button.setEnabled(True)
        button.setText(panel.tr("Copy parameter…"))
        button.setToolTip(
            panel.tr(
                "Copy the selected parameter to one or more functions in the project. "
                "Destinations and optional fixed/bounds/relations are chosen in the next window."
            )
        )

    def copy_selected(panel: ModelPanel) -> None:
        refs = panel.selected_component_refs()
        if not refs:
            QMessageBox.information(
                panel,
                panel.tr("Copy parameter"),
                panel.tr("First select a function."),
            )
            return
        if len(refs) != 1:
            QMessageBox.information(
                panel,
                panel.tr("Copy parameter"),
                panel.tr("Select exactly one source function. Destination functions are chosen next."),
            )
            return
        window = panel.window()
        if not isinstance(window, MainWindow):
            return
        parameter_name = _current_parameter_name(panel)
        if parameter_name is None:
            QMessageBox.information(
                panel,
                panel.tr("Copy parameter"),
                panel.tr("Select a parameter to copy."),
            )
            return

        source_ref = refs[0]
        dialog = ProjectParameterCopyDialog(window, source_ref, parameter_name)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            result = copy_parameter_to_refs(
                window,
                source_ref,
                dialog.target_refs(),
                parameter_name,
                copy_fixed=dialog.copy_fixed.isChecked(),
                copy_bounds=dialog.copy_bounds.isChecked(),
                copy_link=dialog.copy_link.isChecked(),
            )
        except Exception as exc:
            window._show_error(window.tr("Copy parameter"), exc)
            return
        _show_copy_result(window, result, parameter_name)

    ModelPanel._remember_parameter_copy_source = remember_source
    ModelPanel._update_copy_parameter_button = update_button
    ModelPanel._copy_parameter_to_selected = copy_selected


_original_set_view_locked = PlotWorkspace.set_view_locked


def _set_view_locked_with_wheel_state(workspace: PlotWorkspace, enabled: bool) -> None:
    workspace.view_box._curvemole_view_locked = bool(enabled)
    _original_set_view_locked(workspace, enabled)


def _wheel_event(view_box: MaskViewBox, event: Any, axis: int | None = None) -> None:
    """Keep wheel zoom available during interactive modes without defeating View Lock."""
    if getattr(view_box, "_curvemole_view_locked", False):
        pg.ViewBox.wheelEvent(view_box, event, axis=axis)
        return

    # pyqtgraph disables wheel scaling when mouseEnabled is false. CurveMole uses
    # that flag to reserve left-click/drag gestures for placement/masking, but the
    # wheel is independent navigation and should remain available.
    previous = list(view_box.state.get("mouseEnabled", [True, True]))
    view_box.state["mouseEnabled"] = [True, True]
    try:
        pg.ViewBox.wheelEvent(view_box, event, axis=axis)
    finally:
        view_box.state["mouseEnabled"] = previous


def _install_wheel_zoom_fix() -> None:
    PlotWorkspace.set_view_locked = _set_view_locked_with_wheel_state
    MaskViewBox.wheelEvent = _wheel_event


_install_parameter_copy_presentation()
_install_wheel_zoom_fix()
