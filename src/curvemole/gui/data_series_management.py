"""Data and series commands for the project tree."""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
)

from curvemole.core.data import Series
from curvemole.core.errors import ConstraintError, DataValidationError
from curvemole.core.folder_import import IMPORT_DESTINATION_KEY, IMPORT_PROCESSOR_KEY
from curvemole.core.models import Model
from curvemole.core.state import copy_result_maps
from curvemole.gui.colours import SERIES_PALETTES
from curvemole.gui.main_window import CurveTree, MainWindow
from curvemole.gui.windowing import transient_widget


def _rename_data(window: MainWindow, curve_id: str) -> None:
    """Prompt for a generic data-item name without assuming spectroscopy."""
    if not window._ensure_editable():
        return
    try:
        curve = window.project.dataset.curve(curve_id)
    except KeyError:
        return
    name, accepted = QInputDialog.getText(
        window,
        window.tr("Rename data"),
        window.tr("Data name:"),
        text=curve.name,
    )
    if accepted and name.strip():
        window._rename_curve(curve_id, name.strip())
    elif accepted:
        window.refresh_all()


def _delete_series(window: MainWindow, series_id: str) -> None:
    _delete_selected_series(window, [series_id])


def _delete_selected_series(window: MainWindow, series_ids: Iterable[str]) -> None:
    """Validate and remove all requested series as one undoable operation."""
    if not window._ensure_editable():
        return
    if window._thread is not None:
        window._notify(window.tr("Wait for the current task to finish before removing data."))
        return
    requested = set(series_ids)
    groups = [
        (index, series, list(series.curves))
        for index, series in enumerate(window.project.dataset.series) if series.id in requested
    ]
    if not groups:
        return
    selected = {series.id for _, series, _ in groups}
    curve_ids = [curve.id for _, _, curves in groups for curve in curves]
    title = window.tr("Delete series") if len(groups) == 1 else window.tr("Delete selected series")

    try:
        window.project.validate_curve_removal(curve_ids)
    except ConstraintError as exc:
        window._show_error(title, exc)
        return
    if curve_ids:
        if len(groups) == 1:
            message = window.tr(
                'Delete series "{name}"?\n\n'
                "Are you sure? This will also unload all data in this series from the project. "
                "This action can be undone."
            ).format(name=groups[0][1].name)
        else:
            message = window.tr(
                "Delete {series} selected series and unload their {spectra} spectra from the project? "
                "This action can be undone."
            ).format(series=len(groups), spectra=len(curve_ids))
        answer = QMessageBox.question(
            window, title, message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

    saved_models = {
        curve_id: window.project.models[curve_id]
        for curve_id in curve_ids
        if curve_id in window.project.models
    }
    saved_results = copy_result_maps(window.project.results)
    saved_states = {curve.id: curve.state for curve in window.project.curves}
    previous_active = window.active_curve_id
    previous_component = window.selected_component_id

    def redo() -> None:
        available = {curve.id for curve in window.project.curves}
        window.project.remove_curves([identity for identity in curve_ids if identity in available])
        window.project.dataset.series[:] = [
            series for series in window.project.dataset.series if series.id not in selected
        ]
        if window.active_curve_id in curve_ids:
            window.active_curve_id = (
                window.project.curves[0].id if window.project.curves else None
            )
            window.selected_component_id = None

    def undo() -> None:
        current_ids = {series.id for series in window.project.dataset.series}
        for series_index, series, saved_curves in groups:
            if series.id in current_ids:
                continue
            series.curves = list(saved_curves)
            window.project.dataset.series.insert(
                min(series_index, len(window.project.dataset.series)), series
            )
        window.project.models.update(saved_models)
        window.project.results = copy_result_maps(saved_results)
        for curve in window.project.curves:
            if curve.id in saved_states:
                curve.state = saved_states[curve.id]
        if previous_active is not None and any(
            curve.id == previous_active for curve in window.project.curves
        ):
            window.active_curve_id = previous_active
            window.selected_component_id = previous_component

    window._push_change(
        title,
        redo,
        undo,
        modified_curve_ids=set(),
    )


class MoveToSeriesDialog(QDialog):
    """Choose the destination using the same choices as the import dialog."""

    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.setWindowTitle(self.tr("Move to series"))
        layout = QFormLayout(self)
        self.destination = QComboBox()
        self.destination.addItem(self.tr("Create a new series"), None)
        self.existing = {series.name for series in window.project.dataset.series}
        for series in window.project.dataset.series:
            self.destination.addItem(series.name, series.id)
        self.name = QLineEdit(window._next_series_name())
        layout.addRow(self.tr("Destination:"), self.destination)
        layout.addRow(self.tr("Series name:"), self.name)
        self.destination.currentIndexChanged.connect(
            lambda: layout.setRowVisible(self.name, self.destination.currentData() is None)
        )
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def accept(self) -> None:
        name = self.name.text().strip()
        if self.destination.currentData() is None and (not name or name in self.existing):
            QMessageBox.warning(
                self, self.tr("Series name"),
                self.tr("Enter a non-empty series name that is not already in use."),
            )
            self.name.setFocus()
            return
        super().accept()


def _choose_move_destination(window: MainWindow, curve_ids: list[str]) -> None:
    if not window._ensure_editable(prepare_plot=False):
        return
    with transient_widget(MoveToSeriesDialog(window)) as dialog:
        if dialog.exec() == QDialog.DialogCode.Accepted:
            window.move_curves_to_series(
                curve_ids, dialog.destination.currentData(), new_series_name=dialog.name.text(),
            )


def _copy_name(window: MainWindow, name: str, used: set[str]) -> str:
    base = window.tr("{name} (copy)").format(name=name)
    candidate = base
    number = 2
    while candidate in used:
        candidate = f"{base} {number}"
        number += 1
    used.add(candidate)
    return candidate


def _duplicate_data(window: MainWindow, curve_ids: list[str], series_ids: list[str]) -> None:
    if not window._ensure_editable(prepare_plot=False):
        return
    if window._thread is not None:
        window._notify(window.tr("Wait for the current task to finish before duplicating data."))
        return
    selected_curves = set(curve_ids)
    selected_series = set(series_ids)
    groups = window.project.dataset.series
    if not any(
        series.id in selected_series or any(curve.id in selected_curves for curve in series.curves)
        for series in groups
    ):
        return

    title = window.tr("Duplicate data")
    choices = [window.tr("Processed data with applied operations"), window.tr("Original RAW data")]
    choice, accepted = QInputDialog.getItem(window, title, window.tr("Copy:"), choices, 0, False)
    if not accepted:
        return
    raw = choice == choices[1]
    names = {series.name for series in groups}
    copied_series = {}
    copied_curves = {}
    copied_models = {}
    try:
        for series in groups:
            if series.id in selected_series:
                name = _copy_name(window, series.name, names)
                metadata = copy.deepcopy(series.metadata)
                metadata.pop(IMPORT_PROCESSOR_KEY, None)
                metadata.pop(IMPORT_DESTINATION_KEY, None)
                group = Series(name, [curve.duplicate(curve.name, raw=raw) for curve in series.curves], metadata=metadata)
                copied_series[series.id] = (group, tuple(group.curves))
                new_curves = group.curves
            else:
                curve_names = {curve.name for curve in series.curves}
                new_curves = []
                for curve in series.curves:
                    if curve.id in selected_curves:
                        name = _copy_name(window, curve.name, curve_names)
                        duplicate = curve.duplicate(name, raw=raw)
                        copied_curves[curve.id] = duplicate
                        new_curves.append(duplicate)
            copied_models.update((curve.id, Model(name=f"Model for {curve.name}")) for curve in new_curves)
        added_series_ids = {group.id for group, _ in copied_series.values()}
        existing_ids = {series.id for series in groups} | {curve.id for curve in window.project.curves}
        added_ids = added_series_ids | copied_models.keys()
        num_copies = len(copied_curves) + sum(len(curves) for _, curves in copied_series.values())
        if len(added_ids) != len(copied_series) + num_copies or added_ids & existing_ids:
            raise DataValidationError("The copies conflict with existing dataset identifiers.")
    except (DataValidationError, ValueError, ArithmeticError) as exc:
        window._show_error(title, exc)
        return

    def redo() -> None:
        layout = []
        existing = {series.id: series for series in window.project.dataset.series}
        for series in window.project.dataset.series:
            layout.append(series)
            if series.id in copied_series:
                group, curves = copied_series[series.id]
                retained = existing.get(group.id)
                if retained is None:
                    group.curves[:] = curves
                    layout.append(group)
                else:
                    retained.curves[0:0] = curves
            else:
                series.curves[:] = [
                    item for curve in series.curves
                    for item in ((curve, copied_curves[curve.id]) if curve.id in copied_curves else (curve,))
                ]
        window.project.dataset.series[:] = layout
        window.project.models.update(copied_models)

    def undo() -> None:
        # Remove only the copies, even if the user has imported other data since.
        window.project.remove_curves(copied_models)
        window.project.dataset.series[:] = [
            series for series in window.project.dataset.series if series.id not in added_series_ids or series.curves
        ]
        if window.active_curve_id in copied_models:
            window.active_curve_id = window.project.curves[0].id if window.project.curves else None
            window.selected_component_id = None

    window._push_change(title, redo, undo, modified_curve_ids=set())


def _show_context_menu(tree: CurveTree, position: Any) -> None:
    """Extended tree menu with explicit generic-data rename and series deletion."""
    item = tree.itemAt(position)
    project = tree._project
    with transient_widget(QMenu(tree)) as menu:
        new_series_action = menu.addAction(tree.tr("New series…"))
        new_series_action.triggered.connect(
            lambda checked=False: tree.newSeriesRequested.emit()
        )
        if item is None or project is None:
            menu.exec(tree.viewport().mapToGlobal(position))
            return
        metadata = item.data(1, Qt.ItemDataRole.UserRole)
        if not metadata:
            menu.exec(tree.viewport().mapToGlobal(position))
            return

        window = tree.window()
        parent = item.parent()
        if not item.isSelected() and (parent is None or not parent.isSelected()):
            tree.clearSelection()
            item.setSelected(True)
            tree.setCurrentItem(item)
        menu.addSeparator()
        if metadata[0] == "curve":
            curve_id = str(metadata[1])
            selected_ids = tree.ordered_selected_curve_ids() or [curve_id]

            rename_action = menu.addAction(tree.tr("Rename data…"))
            rename_action.setEnabled(not project.read_only and isinstance(window, MainWindow))
            if isinstance(window, MainWindow):
                rename_action.triggered.connect(
                    lambda checked=False, curve_id=curve_id: window.rename_data(curve_id)
                )

            description_action = menu.addAction(tree.tr("Add description…"))
            description_action.setEnabled(not project.read_only)
            description_action.triggered.connect(
                lambda checked=False, curve_id=curve_id: tree.curveDescriptionRequested.emit(curve_id)
            )

            move = menu.addAction(tree.tr("Move to series…"))
            duplicate = menu.addAction(tree.tr("Duplicate data…"))
            for action in (move, duplicate):
                action.setEnabled(not project.read_only and isinstance(window, MainWindow))
            if isinstance(window, MainWindow):
                move.triggered.connect(lambda: _choose_move_destination(window, selected_ids))
                duplicate.triggered.connect(lambda: _duplicate_data(window, selected_ids, []))
            menu.addAction(tree.tr("Move selected up")).triggered.connect(
                lambda checked=False, ids=list(selected_ids): tree.curvesReorderRequested.emit(ids, -1)
            )
            menu.addAction(tree.tr("Move selected down")).triggered.connect(
                lambda checked=False, ids=list(selected_ids): tree.curvesReorderRequested.emit(ids, 1)
            )
            menu.addSeparator()
            colour_action = menu.addAction(tree.tr("Choose data colour…"))
            colour_action.triggered.connect(
                lambda checked=False, curve_id=curve_id: tree.curveColourRequested.emit(curve_id)
            )
            if len(selected_ids) > 1:
                palette_menu = menu.addMenu(tree.tr("Selected spectra palette"))
                palette_menu.setEnabled(not project.read_only)
                for palette_name in SERIES_PALETTES:
                    action = palette_menu.addAction(palette_name)
                    action.triggered.connect(
                        lambda checked=False, ids=tuple(selected_ids), name=palette_name: (
                            tree.curvesPaletteRequested.emit(list(ids), name)
                        )
                    )
        elif metadata[0] == "series":
            series_id = str(metadata[1])
            selected_series = tree.selected_series_ids() or [series_id]
            rename_action = menu.addAction(tree.tr("Rename series…"))
            rename_action.triggered.connect(
                lambda checked=False, series_id=series_id: tree.seriesRenameRequested.emit(series_id)
            )
            description_action = menu.addAction(tree.tr("Add description…"))
            description_action.setEnabled(not project.read_only)
            description_action.triggered.connect(
                lambda checked=False, series_id=series_id: tree.seriesDescriptionRequested.emit(series_id)
            )
            tree._add_series_merge_menu(menu, series_id)
            palette_menu = menu.addMenu(tree.tr("Series palette"))
            for palette_name in SERIES_PALETTES:
                action = palette_menu.addAction(palette_name)
                action.triggered.connect(
                    lambda checked=False, series_id=series_id, palette_name=palette_name: (
                        tree.seriesPaletteRequested.emit(series_id, palette_name)
                    )
                )
            menu.addSeparator()
            if len(selected_series) > 1:
                duplicate = menu.addAction(tree.tr("Duplicate selected series…"))
                delete_action = menu.addAction(tree.tr("Delete selected series…"))
            else:
                duplicate = menu.addAction(tree.tr("Duplicate series…"))
                delete_action = menu.addAction(tree.tr("Delete series…"))
            for action in (duplicate, delete_action):
                action.setEnabled(not project.read_only and isinstance(window, MainWindow))
            if isinstance(window, MainWindow):
                duplicate.triggered.connect(lambda: _duplicate_data(window, [], selected_series))
                delete_action.triggered.connect(lambda: _delete_selected_series(window, selected_series))

        menu.exec(tree.viewport().mapToGlobal(position))


def _install() -> None:
    if getattr(MainWindow, "_curvemole_data_series_management", False):
        return
    MainWindow.rename_data = _rename_data
    MainWindow.delete_series = _delete_series
    MainWindow.delete_selected_series = _delete_selected_series
    CurveTree._show_context_menu = _show_context_menu
    MainWindow._curvemole_data_series_management = True


_install()
