"""Generic data renaming and safe, undoable series deletion."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QMenu, QMessageBox

from curvemole.gui.colours import SERIES_PALETTES
from curvemole.gui.main_window import CurveTree, MainWindow


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
    """Remove a series and all of its data, preserving a complete Undo snapshot."""
    if not window._ensure_editable():
        return
    series_index = next(
        (index for index, series in enumerate(window.project.dataset.series) if series.id == series_id),
        None,
    )
    if series_index is None:
        return
    series = window.project.dataset.series[series_index]
    curve_ids = [curve.id for curve in series.curves]

    if curve_ids:
        answer = QMessageBox.question(
            window,
            window.tr("Delete series"),
            window.tr(
                'Delete series "{name}"?\n\n'
                "Are you sure? This will also unload all data in this series from the project. "
                "This action can be undone."
            ).format(name=series.name),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

    saved_models = {
        curve_id: window.project.models[curve_id]
        for curve_id in curve_ids
        if curve_id in window.project.models
    }
    saved_results = {
        curve_id: window.project.results[curve_id]
        for curve_id in curve_ids
        if curve_id in window.project.results
    }
    previous_active = window.active_curve_id
    previous_component = window.selected_component_id

    def redo() -> None:
        current_index = next(
            (
                index
                for index, candidate in enumerate(window.project.dataset.series)
                if candidate.id == series_id
            ),
            None,
        )
        if current_index is not None:
            window.project.dataset.series.pop(current_index)
        for curve_id in curve_ids:
            window.project.models.pop(curve_id, None)
            window.project.results.pop(curve_id, None)
        if window.active_curve_id in curve_ids:
            window.active_curve_id = (
                window.project.curves[0].id if window.project.curves else None
            )
            window.selected_component_id = None

    def undo() -> None:
        if not any(candidate.id == series_id for candidate in window.project.dataset.series):
            window.project.dataset.series.insert(
                min(series_index, len(window.project.dataset.series)), series
            )
        window.project.models.update(saved_models)
        window.project.results.update(saved_results)
        if previous_active is not None and any(
            curve.id == previous_active for curve in window.project.curves
        ):
            window.active_curve_id = previous_active
            window.selected_component_id = previous_component

    window._push_change(
        window.tr("Delete series"),
        redo,
        undo,
        modified_curve_ids=set(),
    )


def _show_context_menu(tree: CurveTree, position: Any) -> None:
    """Extended tree menu with explicit generic-data rename and series deletion."""
    item = tree.itemAt(position)
    project = tree._project
    menu = QMenu(tree)
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
    menu.addSeparator()
    if metadata[0] == "curve":
        curve_id = str(metadata[1])
        if not item.isSelected():
            tree.clearSelection()
            item.setSelected(True)
            tree.setCurrentItem(item)
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

        move_menu = menu.addMenu(tree.tr("Move selected to series"))
        for series in project.dataset.series:
            action = move_menu.addAction(series.name)
            action.triggered.connect(
                lambda checked=False, ids=list(selected_ids), target_id=series.id: (
                    tree.curvesMoveRequested.emit(ids, target_id)
                )
            )
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
    elif metadata[0] == "series":
        series_id = str(metadata[1])
        rename_action = menu.addAction(tree.tr("Rename series…"))
        rename_action.triggered.connect(
            lambda checked=False, series_id=series_id: tree.seriesRenameRequested.emit(series_id)
        )
        description_action = menu.addAction(tree.tr("Add description…"))
        description_action.setEnabled(not project.read_only)
        description_action.triggered.connect(
            lambda checked=False, series_id=series_id: tree.seriesDescriptionRequested.emit(series_id)
        )
        merge_menu = menu.addMenu(tree.tr("Merge series into"))
        targets = [series for series in project.dataset.series if series.id != series_id]
        merge_menu.setEnabled(bool(targets))
        for target in targets:
            action = merge_menu.addAction(target.name)
            action.triggered.connect(
                lambda checked=False, source_id=series_id, target_id=target.id: (
                    tree.seriesMergeRequested.emit(source_id, target_id)
                )
            )
        palette_menu = menu.addMenu(tree.tr("Series palette"))
        for palette_name in SERIES_PALETTES:
            action = palette_menu.addAction(palette_name)
            action.triggered.connect(
                lambda checked=False, series_id=series_id, palette_name=palette_name: (
                    tree.seriesPaletteRequested.emit(series_id, palette_name)
                )
            )
        menu.addSeparator()
        delete_action = menu.addAction(tree.tr("Delete series…"))
        delete_action.setEnabled(not project.read_only and isinstance(window, MainWindow))
        if isinstance(window, MainWindow):
            delete_action.triggered.connect(
                lambda checked=False, series_id=series_id: window.delete_series(series_id)
            )

    menu.exec(tree.viewport().mapToGlobal(position))


def _install() -> None:
    if getattr(MainWindow, "_curvemole_data_series_management", False):
        return
    MainWindow.rename_data = _rename_data
    MainWindow.delete_series = _delete_series
    CurveTree._show_context_menu = _show_context_menu
    MainWindow._curvemole_data_series_management = True


_install()
