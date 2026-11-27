"""CurveMole's single, dockable desktop workspace."""

from __future__ import annotations

import copy
import json
import math
import os
import re
from collections import Counter
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
from platformdirs import user_cache_path
from PySide6.QtCore import (
    QEvent,
    QItemSelectionModel,
    QObject,
    QPersistentModelIndex,
    QSettings,
    QSignalBlocker,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QPalette,
    QPixmap,
    QUndoStack,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionTab,
    QTabBar,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import getCppPointer

from curvemole.core.calculator import (
    apply_column_formula,
    apply_curve_operation,
    apply_custom_formula,
    apply_scalar,
)
from curvemole.core.data import Curve, CurveState, Series
from curvemole.core.errors import ConstraintError
from curvemole.core.export import export_bundle, export_function_parameters
from curvemole.core.fitting import (
    FitPlan,
    FitResult,
    FitSettings,
)
from curvemole.core.importers import ImportColumnError, ImportPreview, import_file
from curvemole.core.initialization import (
    PeakSuggestion,
    initialise_peak_component,
    initialise_spline_component,
)
from curvemole.core.models import Component, Model, area_for_height
from curvemole.core.parameters import resolve_parameter_values
from curvemole.core.plugins import PluginManager
from curvemole.core.project import Project
from curvemole.core.recovery import RecoveryManager
from curvemole.core.registry import default_registry
from curvemole.core.serialization import ProjectLock, save_project
from curvemole.core.state import copy_result_maps
from curvemole.core.transactions import ModelEdit, restore_model_state
from curvemole.core.uncertainty import AdaptiveReplicateSettings
from curvemole.core.uncertainty_status import uncertainty_warning
from curvemole.gui.colours import (
    DEFAULT_SERIES_PALETTE,
    SERIES_PALETTES,
    series_palette_colours,
    spectrum_colour_allowed,
)
from curvemole.gui.dialogs import (
    AboutDialog,
    AddComponentDialog,
    # Public injection point: background subtraction resolves its dialog through
    # this module so plugins and tests can substitute it.
    BackgroundComponentsDialog,  # noqa: F401
    CopyFitDialog,
    ExportBundleDialog,
    ImportMappingDialog,
    PluginManagerDialog,
)
from curvemole.gui.dock_collapse import DockCollapseControls, DockViewport
from curvemole.gui.external import open_with_host_application
from curvemole.gui.legacy_updates import _update_notification_due  # noqa: F401
from curvemole.gui.panels import (
    CalculatorPanel,
    DiagnosticsPanel,
    FunctionBuilderPanel,
    ModelPanel,
    UncertaintyPanel,
    WorksheetPanel,
)
from curvemole.gui.plot import PlotWorkspace
from curvemole.gui.plot_appearance import PlotAppearanceDialog, normalize_plot_appearance
from curvemole.gui.row_drag import RowDragMixin, RowDrop, row_block_order
from curvemole.gui.updates import semantic_version as _semantic_version  # noqa: F401
from curvemole.gui.updates import update_kind as _update_kind  # noqa: F401
from curvemole.gui.windowing import transient_widget
from curvemole.version import __version__

PALETTE = list(SERIES_PALETTES[DEFAULT_SERIES_PALETTE])
_DEFAULT_PALETTE_SETTING = "plot/default_series_palette"


def _resource_icon(
    filename: str, crop: tuple[int, int, int, int] | None = None,
    checked_filename: str | None = None,
) -> QIcon:
    """Return an icon bundled with CurveMole."""
    if filename.endswith(".svg") and crop is None:
        from curvemole.gui.icons import vector_icon

        return vector_icon(filename, checked_filename)
    pixmap = QPixmap(str(resources.files("curvemole.resources").joinpath(filename)))
    if crop is not None:
        pixmap = pixmap.copy(*crop)
    return QIcon(pixmap)


from curvemole.gui import window_extensions  # noqa: E402
from curvemole.gui.task_runner import TaskCallbacks, TaskRunner, Worker  # noqa: E402,F401
from curvemole.gui.undo_commands import CallbackCommand  # noqa: E402,F401 - public import path


def _curve_state_presentation(
    project: Project, curve: Curve, uncertainty_method: str | None = None,
) -> tuple[str, str]:
    """Show completion for the chosen uncertainty method, retaining all saved reports."""
    reports_by_curve = project.results.get("uncertainty_reports_by_curve", {})
    reports = reports_by_curve.get(curve.id, {}) if isinstance(reports_by_curve, dict) else {}
    methods = [method for method, report in reports.items() if report]
    selected_method = ("parametric_monte_carlo" if uncertainty_method == "monte_carlo"
                       else uncertainty_method)
    failure = project.results.get("uncertainty_failures_by_curve", {}).get(
        curve.id, {}).get(selected_method)
    if failure:
        timeout = failure.get("reason") == "timeout" or "timeout" in failure.get("message", "").lower()
        suffix = " (timeout)" if timeout else ""
        return (f"{curve.state.value}  ·  ⚠ Uncertainty analysis failed{suffix}",
                f"{selected_method}: {failure['message']}")
    if not methods:
        return curve.state.value, ""

    from curvemole.core.analysis_errors import DISPLAY_METHODS

    labels = {
        method: "Fit covariance" if method == "covariance" else DISPLAY_METHODS.get(method, method)
        for method in methods
    }
    tooltip = "Saved uncertainty analyses: " + ", ".join(labels[method] for method in methods)
    if uncertainty_method is not None:
        uncertainty_method = (
            "parametric_monte_carlo" if uncertainty_method == "monte_carlo" else uncertainty_method
        )
        chosen_label = ("Fit covariance" if uncertainty_method == "covariance"
                        else DISPLAY_METHODS.get(uncertainty_method, uncertainty_method))
        if uncertainty_method not in methods:
            return curve.state.value, f"{chosen_label}: not analysed.\n{tooltip}"
        tooltip = f"Selected uncertainty method: {chosen_label}.\n{tooltip}"
    analysis_state = (
        "Uncertainty analysed"
        if curve.state == CurveState.FITTED
        else "Uncertainty analysis outdated"
    )
    from curvemole.core.background_uncertainty import (
        background_uncertainty_is_current,
        background_uncertainty_record,
    )

    report = reports.get(selected_method or methods[-1], {})
    treatment = background_uncertainty_record(report.get("baseline", {}))
    if treatment:
        analysis_state = ("Separate uncertainty analysis" if background_uncertainty_is_current(project, treatment)
                          else "Uncertainty analysis outdated")
    warning = uncertainty_warning(project, curve.id, uncertainty_method)
    if warning:
        analysis_state = ("⚠ Uncertainty warning" if analysis_state == "Uncertainty analysed"
                          else analysis_state + "  ·  ⚠ Uncertainty warning")
        tooltip = warning + "\n" + tooltip
    return f"{curve.state.value}  ·  {analysis_state}", tooltip


class CurveTree(RowDragMixin, QTreeWidget):
    noteRequested = Signal(object)
    activeCurveChanged = Signal(object)
    offscreenActiveSpectrumChanged = Signal(str)
    curveVisibilityChanged = Signal(str, bool)
    curveRenamed = Signal(str, str)
    seriesRenamed = Signal(str, str)
    seriesRenameRequested = Signal(str)
    seriesDescriptionRequested = Signal(str)
    curveDescriptionRequested = Signal(str)
    seriesActivated = Signal(str)
    curveColourRequested = Signal(str)
    seriesPaletteRequested = Signal(str, str)
    curvesPaletteRequested = Signal(object, str)
    newSeriesRequested = Signal()
    curvesMoveRequested = Signal(object, str)
    curvesReorderRequested = Signal(object, int)
    seriesMergeRequested = Signal(object, str)
    rowMoveRequested = Signal(object, object, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderLabels([self.tr("Visible"), self.tr("Series / Curve"), self.tr("State")])
        self.setTreePosition(1)
        self.setSelectionMode(self.SelectionMode.ExtendedSelection)
        self.setup_row_drag()
        self.setAlternatingRowColors(True)
        self._updating = False
        self._project: Project | None = None
        self._uncertainty_method: str | None = None
        self._items_by_key: dict[tuple[str, str], QTreeWidgetItem] = {}
        self._marked_spectrum: QTreeWidgetItem | None = None
        self._activation_click = QPersistentModelIndex()
        self._multiselection_click = QPersistentModelIndex()
        self._offscreen_active_name = ""
        self._active_visibility_timer = QTimer(self)
        self._active_visibility_timer.setSingleShot(True)
        self._active_visibility_timer.timeout.connect(self._update_active_visibility)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.currentItemChanged.connect(self._active_changed)
        self.itemChanged.connect(self._item_changed)
        self.setEditTriggers(self.EditTrigger.DoubleClicked | self.EditTrigger.EditKeyPressed)
        from curvemole.gui.note_indicators import (
            NoteIndicatorDelegate,
            checkbox_indicator_size,
        )

        # macOS styles may draw an 18px item checkbox even when PM_IndicatorWidth
        # reports 14px. Match the actual checkbox geometry, not the generic metric.
        self.setIconSize(checkbox_indicator_size(self))
        self.setItemDelegate(NoteIndicatorDelegate(self, self.noteRequested.emit))

    def scrollTo(self, index, hint=QTreeWidget.ScrollHint.EnsureVisible) -> None:
        # Follow the current row vertically without panning away from its controls.
        horizontal = self.horizontalScrollBar()
        offset = horizontal.value()
        super().scrollTo(index, hint)
        horizontal.setValue(offset)

    def mousePressEvent(self, event) -> None:
        self._activation_click = QPersistentModelIndex()
        self._multiselection_click = QPersistentModelIndex()
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.position().toPoint())
            if index.column() > 0 and index.parent().isValid():
                if self._has_multiple_selected_rows():
                    self._multiselection_click = QPersistentModelIndex(index)
                if event.modifiers() == Qt.KeyboardModifier.NoModifier:
                    item = self.itemFromIndex(index)
                    if item is not self._marked_spectrum and (item.isSelected() or item.parent().isSelected()):
                        self._activation_click = QPersistentModelIndex(index)
        super().mousePressEvent(event)

    def _has_multiple_selected_rows(self) -> bool:
        rows = self.selectedItems()
        return len(rows) > 1 or bool(rows and rows[0].childCount() > 1)

    def mouseDoubleClickEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        if (
            event.button() == Qt.MouseButton.LeftButton
            and index.column() > 0 and index.parent().isValid()
            and (index == self._multiselection_click or self._has_multiple_selected_rows())
        ):
            # Qt reports the second press as a double-click. Apply the ordinary
            # click rules even if the first press already reduced the selection.
            self.mousePressEvent(event)
            return
        super().mouseDoubleClickEvent(event)

    def selectionCommand(self, index, event=None):
        if (
            event is not None
            and event.type() in (
                QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick,
            )
            and index.isValid()
            and index == self._activation_click
        ):
            # Qt updates the current row on press, then can clear the selection on release.
            return QItemSelectionModel.SelectionFlag.NoUpdate
        return super().selectionCommand(index, event)

    def _row_drag_sources(self, source):
        if not source.isValid():
            return ()
        item = self.itemFromIndex(source)
        parent = item.parent()
        if parent is None and item.isSelected():
            keys = [("series", identity) for identity in self.selected_series_ids()]
        elif parent is not None and (item.isSelected() or parent.isSelected()):
            keys = [("curve", identity) for identity in self.selected_curve_ids()]
        else:
            return (source,)
        return tuple(self.indexFromItem(self._items_by_key[key], source.column()) for key in keys)

    def _row_drop_at(self, source, position):
        if self._project is None or self._project.read_only:
            return None
        source_item = self.itemFromIndex(source)
        target = self.itemAt(position)
        if target is None:
            target = self.topLevelItem(self.topLevelItemCount() - 1)
            if target is None:
                return None
            target = self._last_visible_series_row(target)
            if position.y() <= self.visualItemRect(target).bottom():
                return None
        rect = self.visualItemRect(target)
        if source_item.parent() is None:
            series = target.parent() or target
            first = self.visualItemRect(series).top()
            last = self.visualItemRect(self._last_visible_series_row(series)).bottom() + 1
            after = position.y() - first >= last - position.y()
            y = last if after else first
            if not 0 <= y <= self.viewport().height():
                return None
            return RowDrop(self.indexFromItem(series, 1), after, 3, y)
        after = position.y() >= rect.center().y() or target.parent() is None
        y = rect.bottom() + 1 if after else rect.top()
        x = max(3, self.columnViewportPosition(1) + 2 * self.indentation())
        return RowDrop(self.indexFromItem(target, 1), after, x, y)

    @staticmethod
    def _last_visible_series_row(series):
        if series.isExpanded() and series.childCount():
            return series.child(series.childCount() - 1)
        return series

    def _request_row_move(self, source, drop, sources=()):
        source_item = self.itemFromIndex(source)
        target_item = self.itemFromIndex(drop.target)
        if source_item.parent() is not None and target_item.parent() is None:
            target_item.setExpanded(True)
        keys = tuple(self.itemFromIndex(index).data(1, Qt.ItemDataRole.UserRole) for index in (sources or (source,)))
        self.rowMoveRequested.emit(keys[0] if len(keys) == 1 else keys, drop.target.data(Qt.ItemDataRole.UserRole),
                                   drop.after)

    def populate(self, project: Project, active_curve_id: str | None) -> set[str]:
        # Rebuild atomically: selection signals during clear() otherwise redraw
        # an empty selected-only plot and discard multi-selection on every edit.
        preserve = self._project is project
        selected_keys = {
            tuple(item.data(1, Qt.ItemDataRole.UserRole)) for item in self.selectedItems()
        }
        current = self.currentItem()
        current_key = tuple(current.data(1, Qt.ItemDataRole.UserRole)) if current else None
        current_column = max(0, self.currentColumn())
        previous_active = getattr(self, "_populated_active_curve_id", None)
        expanded = {
            self.topLevelItem(index).data(1, Qt.ItemDataRole.UserRole)[1]:
            self.topLevelItem(index).isExpanded()
            for index in range(self.topLevelItemCount())
        } if preserve else {}
        scroll_x = self.horizontalScrollBar().value()
        scroll_y = self.verticalScrollBar().value()
        self._project = project
        self.setDragEnabled(not project.read_only)
        self._populated_active_curve_id = active_curve_id
        self._updating = True
        try:
            with QSignalBlocker(self):
                self._marked_spectrum = None
                self.clear()
                active_item: QTreeWidgetItem | None = None
                items: dict[tuple[str, str], QTreeWidgetItem] = {}
                for series in project.dataset.series:
                    from curvemole.gui.note_indicators import (
                        attach_note,
                        spectrum_colour_icon,
                    )

                    parent = QTreeWidgetItem(["", series.name, ""])
                    font = parent.font(1)
                    font.setBold(True)
                    parent.setFont(1, font)
                    dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
                    parent.setForeground(1, QColor("#66B5FF" if dark else "#075B9A"))
                    attach_note(parent, project, "series", series.id, column=1)
                    parent.setData(1, Qt.ItemDataRole.UserRole, ("series", series.id))
                    parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsEditable)
                    self.addTopLevelItem(parent)
                    items[("series", series.id)] = parent
                    for curve in series.curves:
                        state_text, state_tooltip = _curve_state_presentation(
                            project, curve, self._uncertainty_method,
                        )
                        child = QTreeWidgetItem(["", curve.name, state_text])
                        if state_tooltip:
                            child.setToolTip(2, state_tooltip)
                        attach_note(child, project, "spectrum", curve.id, column=1)
                        child.setData(1, Qt.ItemDataRole.UserRole, ("curve", curve.id))
                        child.setFlags(
                            child.flags()
                            | Qt.ItemFlag.ItemIsUserCheckable
                            | Qt.ItemFlag.ItemIsEditable
                            | Qt.ItemFlag.ItemIsSelectable
                        )
                        child.setCheckState(0, Qt.CheckState.Checked if curve.visible else Qt.CheckState.Unchecked)
                        child.setIcon(0, spectrum_colour_icon(self, curve.colour))
                        self._style_curve_visibility(child)
                        child.setToolTip(0, self.tr(
                            "Checked: show this spectrum in Overlay and Waterfall.\n"
                            "Unchecked: hide it from these views without deleting its data or fit.\n"
                            "Click the coloured square to choose the spectrum colour "
                            "without changing visibility. Row highlighting selects spectra "
                            "for operations; the checkbox controls visibility. Hidden spectra "
                            "are excluded from fit plans."
                            " Up/Down navigation skips hidden spectra."
                        ))
                        self._style_uncertainty_state(child, curve)
                        parent.addChild(child)
                        items[("curve", curve.id)] = child
                        if curve.id == active_curve_id:
                            active_item = child
                    parent.setExpanded(expanded.get(series.id, True))
                self.resizeColumnToContents(0)
                self.resizeColumnToContents(1)
                current_item = items.get(current_key) if preserve else None
                if current_item is None or active_curve_id != previous_active:
                    current_item = active_item
                if current_item is not None:
                    self.setCurrentItem(current_item, current_column, QItemSelectionModel.SelectionFlag.NoUpdate)
                # A single selected active spectrum follows explicit navigation;
                # multi-selection and an intentionally empty selection stay intact.
                if (active_item is not None and active_curve_id != previous_active
                        and selected_keys == {("curve", previous_active)}):
                    selected_keys = {("curve", active_curve_id)}
                if preserve:
                    for key in selected_keys:
                        if key in items:
                            items[key].setSelected(True)
                elif active_item is not None:
                    active_item.setSelected(True)
                if preserve:
                    self.verticalScrollBar().setValue(scroll_y)
                    self.horizontalScrollBar().setValue(scroll_x)
                self._items_by_key = items
        finally:
            self._updating = False

        self.mark_active_spectrum(active_curve_id)
        return self.selected_curve_ids()

    def mark_active_spectrum(self, curve_id: str | None) -> None:
        item = self._items_by_key.get(("curve", curve_id)) if curve_id is not None else None
        if item is not self._marked_spectrum:
            index = self.indexFromItem(item, 1) if item is not None else None
            width = self.columnWidth(1)
            name_fits = index is not None and self.sizeHintForIndex(index).width() <= width
            with QSignalBlocker(self):
                for row, bold in ((self._marked_spectrum, False), (item, True)):
                    if row is not None:
                        font = row.font(1)
                        font.setBold(bold)
                        row.setFont(1, font)
            if name_fits:
                # Keep the full name readable when bold makes it slightly wider.
                self.setColumnWidth(1, max(width, self.sizeHintForIndex(index).width()))
            self._marked_spectrum = item
            self.viewport().update()
        self._active_visibility_timer.start(0)

    def drawRow(self, painter, option, index) -> None:
        super().drawRow(painter, option, index)
        item = self._marked_spectrum
        if item is not None and self.itemFromIndex(index) is item:
            dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
            accent = QColor("#FFD166" if dark else "#995000")
            rect = option.rect
            x = self.columnViewportPosition(1) + 2
            painter.fillRect(x, rect.top() + 2, 3, max(1, rect.height() - 4), accent)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._marked_spectrum is not None and not self._active_visibility_timer.isActive():
            # Check after scrolling, resizing or collapsing rows has updated their geometry.
            self._active_visibility_timer.start(0)

    def _update_active_visibility(self) -> None:
        item = self._marked_spectrum
        name = ""
        if item is not None:
            row = self.visualItemRect(item)
            if not self.viewport().rect().intersects(row):
                name = item.text(1) or self.tr("Unnamed spectrum")
        if name != self._offscreen_active_name:
            self._offscreen_active_name = name
            self.offscreenActiveSpectrumChanged.emit(name)

    def set_uncertainty_method(self, method: str) -> None:
        self._uncertainty_method = method
        if self._project is None:
            return
        curves = {curve.id: curve for curve in self._project.curves}
        with QSignalBlocker(self):
            for index in range(self.topLevelItemCount()):
                parent = self.topLevelItem(index)
                for child_index in range(parent.childCount()):
                    item = parent.child(child_index)
                    metadata = item.data(1, Qt.ItemDataRole.UserRole)
                    curve = curves.get(metadata[1]) if metadata else None
                    if curve is not None:
                        text, tooltip = _curve_state_presentation(self._project, curve, method)
                        item.setText(2, text)
                        item.setToolTip(2, tooltip)
                        self._style_uncertainty_state(item, curve)

    def _style_uncertainty_state(self, item: QTreeWidgetItem, curve: Curve) -> None:
        warning = uncertainty_warning(self._project, curve.id, self._uncertainty_method)
        dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
        item.setForeground(2, QColor("#ffd166" if dark else "#9b6500") if warning else _state_colour(curve.state))
        item.setIcon(2, self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning) if warning else QIcon())

    def _style_curve_visibility(self, item: QTreeWidgetItem) -> None:
        visible = item.checkState(0) == Qt.CheckState.Checked
        colour = self.palette().color(QPalette.ColorRole.Text)
        if not visible:
            background = self.palette().color(QPalette.ColorRole.Base)
            colour = QColor(
                (colour.red() + background.red()) // 2,
                (colour.green() + background.green()) // 2,
                (colour.blue() + background.blue()) // 2,
            )
        with QSignalBlocker(self):
            item.setForeground(1, colour)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            for index in range(self.topLevelItemCount()):
                parent = self.topLevelItem(index)
                for child_index in range(parent.childCount()):
                    self._style_curve_visibility(parent.child(child_index))

    def moveCursor(self, cursor_action, modifiers):
        if cursor_action not in (self.CursorAction.MoveUp, self.CursorAction.MoveDown):
            return super().moveCursor(cursor_action, modifiers)
        index = super().moveCursor(cursor_action, modifiers)
        item = self.itemFromIndex(index)
        step = self.itemAbove if cursor_action == self.CursorAction.MoveUp else self.itemBelow
        while item is not None:
            metadata = item.data(1, Qt.ItemDataRole.UserRole)
            if (not metadata or metadata[0] != "curve"
                    or item.checkState(0) == Qt.CheckState.Checked):
                return self.indexFromItem(item, index.column())
            item = step(item)
        return self.currentIndex()

    def selected_curve_ids(self) -> set[str]:
        result: set[str] = set()
        for item in self.selectedItems():
            metadata = item.data(1, Qt.ItemDataRole.UserRole)
            if metadata and metadata[0] == "curve":
                result.add(str(metadata[1]))
            elif metadata and metadata[0] == "series":
                result.update(
                    str(item.child(index).data(1, Qt.ItemDataRole.UserRole)[1])
                    for index in range(item.childCount())
                )
        return result

    def selected_series_ids(self) -> list[str]:
        return [
            str(item.data(1, Qt.ItemDataRole.UserRole)[1])
            for item in self.selectedItems() if item.parent() is None
        ]

    def ordered_selected_curve_ids(self) -> list[str]:
        selected = self.selected_curve_ids()
        return [
            str(child.data(1, Qt.ItemDataRole.UserRole)[1])
            for top_index in range(self.topLevelItemCount())
            for child in (
                self.topLevelItem(top_index).child(child_index)
                for child_index in range(self.topLevelItem(top_index).childCount())
            )
            if child.data(1, Qt.ItemDataRole.UserRole)
            and child.data(1, Qt.ItemDataRole.UserRole)[0] == "curve"
            and str(child.data(1, Qt.ItemDataRole.UserRole)[1]) in selected
        ]

    def select_all_curves(self) -> None:
        self.clearSelection()
        for top_index in range(self.topLevelItemCount()):
            parent = self.topLevelItem(top_index)
            if parent.isHidden():
                continue
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                if not child.isHidden():
                    child.setSelected(True)

    def deselect_all_curves(self) -> None:
        self.clearSelection()

    def _add_series_merge_menu(self, menu: QMenu, clicked_id: str) -> None:
        selected = self.selected_series_ids()
        source_ids = tuple(selected) if clicked_id in selected else (clicked_id,)
        multiple = len(source_ids) > 1
        title = self.tr("Merge selected series into") if multiple else self.tr("Merge series into")
        submenu = menu.addMenu(title)
        targets = [series for series in self._project.dataset.series if multiple or series.id != clicked_id]
        submenu.setEnabled(bool(targets) and not self._project.read_only)
        for target in targets:
            submenu.addAction(target.name).triggered.connect(
                lambda checked=False, target_id=target.id: self.seriesMergeRequested.emit(source_ids, target_id)
            )

    def _show_context_menu(self, position: Any) -> None:
        item = self.itemAt(position)
        project = self._project
        with transient_widget(QMenu(self)) as menu:
            new_series_action = menu.addAction(self.tr("New series…"))
            new_series_action.triggered.connect(lambda checked=False: self.newSeriesRequested.emit())
            if item is None or project is None:
                menu.exec(self.viewport().mapToGlobal(position))
                return
            metadata = item.data(1, Qt.ItemDataRole.UserRole)
            if not metadata:
                menu.exec(self.viewport().mapToGlobal(position))
                return

            menu.addSeparator()
            if metadata[0] == "curve":
                curve_id = str(metadata[1])
                if not item.isSelected():
                    self.clearSelection()
                    item.setSelected(True)
                    self.setCurrentItem(item)
                selected_ids = self.ordered_selected_curve_ids() or [curve_id]

                description_action = menu.addAction(self.tr("Add description…"))
                description_action.setEnabled(not project.read_only)
                description_action.triggered.connect(
                    lambda checked=False, curve_id=curve_id: self.curveDescriptionRequested.emit(curve_id)
                )

                move_menu = menu.addMenu(self.tr("Move selected to series"))
                for series in project.dataset.series:
                    action = move_menu.addAction(series.name)
                    action.triggered.connect(
                        lambda checked=False, ids=list(selected_ids), target_id=series.id: (
                            self.curvesMoveRequested.emit(ids, target_id)
                        )
                    )
                menu.addAction(self.tr("Move selected up")).triggered.connect(
                    lambda checked=False, ids=list(selected_ids): self.curvesReorderRequested.emit(ids, -1)
                )
                menu.addAction(self.tr("Move selected down")).triggered.connect(
                    lambda checked=False, ids=list(selected_ids): self.curvesReorderRequested.emit(ids, 1)
                )
                menu.addSeparator()
                colour_action = menu.addAction(self.tr("Choose spectrum colour…"))
                colour_action.triggered.connect(
                    lambda checked=False, curve_id=curve_id: self.curveColourRequested.emit(curve_id)
                )
            elif metadata[0] == "series":
                series_id = str(metadata[1])
                rename_action = menu.addAction(self.tr("Rename series…"))
                rename_action.triggered.connect(
                    lambda checked=False, series_id=series_id: self.seriesRenameRequested.emit(series_id)
                )
                description_action = menu.addAction(self.tr("Add description…"))
                description_action.setEnabled(not project.read_only)
                description_action.triggered.connect(
                    lambda checked=False, series_id=series_id: self.seriesDescriptionRequested.emit(series_id)
                )
                self._add_series_merge_menu(menu, series_id)
                palette_menu = menu.addMenu(self.tr("Series palette"))
                for palette_name in SERIES_PALETTES:
                    action = palette_menu.addAction(palette_name)
                    action.triggered.connect(
                        lambda checked=False, series_id=series_id, palette_name=palette_name: (
                            self.seriesPaletteRequested.emit(series_id, palette_name)
                        )
                    )
            menu.exec(self.viewport().mapToGlobal(position))

    def _active_changed(self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:
        if self._updating or current is None:
            return
        metadata = current.data(1, Qt.ItemDataRole.UserRole)
        if metadata and metadata[0] == "series":
            self.seriesActivated.emit(str(metadata[1]))
            return
        self.activeCurveChanged.emit(metadata[1] if metadata and metadata[0] == "curve" else None)

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating:
            return
        metadata = item.data(1, Qt.ItemDataRole.UserRole)
        if not metadata:
            return
        if metadata[0] == "series":
            if column == 1:
                self.seriesRenamed.emit(str(metadata[1]), item.text(1))
            return
        if metadata[0] != "curve":
            return
        curve_id = str(metadata[1])
        if column == 0:
            self._style_curve_visibility(item)
            self.curveVisibilityChanged.emit(curve_id, item.checkState(0) == Qt.CheckState.Checked)
        elif column == 1:
            self.curveRenamed.emit(curve_id, item.text(1))


class DockTabTitleFilter(QObject):
    """Reapply labels when Qt refreshes its own dock tabs during layout."""

    SCROLLER_WIDTH = 58

    @staticmethod
    def _text_width(bar: QTabBar) -> int:
        style = bar.style()
        option = QStyleOptionTab()
        option.initFrom(bar)
        option.shape = bar.shape()
        option.documentMode = bar.documentMode()
        horizontal = style.pixelMetric(QStyle.PixelMetric.PM_TabBarTabHSpace, option, bar)
        vertical = style.pixelMetric(QStyle.PixelMetric.PM_TabBarTabVSpace, option, bar)
        frame = style.sizeFromContents(
            QStyle.ContentsType.CT_TabBarTab, option,
            QSize(horizontal, bar.fontMetrics().height() + vertical), bar,
        ).width()
        edges = sum(
            style.subElementRect(element, option, bar).width()
            for element in (
                QStyle.SubElement.SE_TabBarTearIndicatorLeft,
                QStyle.SubElement.SE_TabBarTearIndicatorRight,
            )
        )
        # Qt's right arrow can stall if a single tab is wider than the
        # viewport between the indicators and the scroll buttons.
        return bar.width() - DockTabTitleFilter.SCROLLER_WIDTH - frame - edges - 1

    def format_titles(self, bar: QTabBar) -> None:
        window = self.parent()
        # Qt stores the dock identity in tabData. Tab order can differ from
        # tabifiedDockWidgets() after dragging or restoring the layout.
        docks = {
            getCppPointer(dock)[0]: dock for dock in window.findChildren(
                QDockWidget, options=Qt.FindChildOption.FindDirectChildrenOnly,
            )
        }
        available = self._text_width(bar)
        metrics = bar.fontMetrics()
        for index in range(bar.count()):
            dock = docks.get(bar.tabData(index))
            full = (
                dock.property("curvemole_full_tab_title") or dock.windowTitle()
                if dock is not None else bar.tabToolTip(index) or bar.tabText(index)
            )
            label = full if len(full) <= 25 else full[:22] + "..."
            icon_width = 0 if bar.tabIcon(index).isNull() else bar.iconSize().width() + 4
            if available > 0 and metrics.size(Qt.TextFlag.TextShowMnemonic, label).width() > available - icon_width:
                prefix = full[:22]
                while prefix and metrics.size(Qt.TextFlag.TextShowMnemonic, prefix + "...").width() > available - icon_width:
                    prefix = prefix[:-1]
                label = prefix + "..."
            if dock is not None and not dock.isFloating() and dock.windowTitle() != label:
                # QMainWindow restores the caption from the dock on relayout.
                window._prepare_tool_dock(dock)
                window._set_tool_dock_caption(dock, label)
            if bar.tabText(index) != label:
                bar.setTabText(index, label)
            if bar.tabToolTip(index) != full:
                bar.setTabToolTip(index, full)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (isinstance(watched, QTabBar)
                and event.type() in (QEvent.Type.Paint, QEvent.Type.LayoutRequest, QEvent.Type.Resize)):
            self.format_titles(watched)
        return False


class MainWindow(QMainWindow):
    plugins_ready = Signal()
    # Emitted whenever the window's Project object is replaced (new, open,
    # recovery, plugin or fit Undo snapshots). Prefer it over polling.
    projectReplaced = Signal(object)

    @property
    def project(self) -> Project:
        return self._project

    @project.setter
    def project(self, value: Project) -> None:
        previous = getattr(self, "_project", None)
        self._project = value
        if previous is not None and previous is not value:
            self.projectReplaced.emit(value)
    _LAYOUT_SCHEMA_VERSION = 2

    def __init__(self, project: Project | None = None, *, defer_plugins: bool = False) -> None:
        from curvemole.gui.garbage_collection import ensure_gui_garbage_collection
        ensure_gui_garbage_collection()
        super().__init__()
        self.registry = default_registry().copy()
        self.project = project or Project()
        from curvemole.core.analysis_errors import restore_uncertainty_reports
        restore_uncertainty_reports(self.project)
        self.active_curve_id: str | None = self.project.curves[0].id if self.project.curves else None
        self.selected_component_id: str | None = None
        self.fit_settings = FitSettings()
        self.last_fit_plan: FitPlan | None = None
        self._paused_result: FitResult | None = None
        self.task_runner = TaskRunner(self)
        self._project_lock: ProjectLock | None = None
        self._project_disk_digest: str | None = None
        self._transfer_request: dict | None = None
        self._transfer_path: Path | None = None
        self._transfer_timeout_warned = False
        self._transfer_monitor = QTimer(self)
        self._transfer_monitor.setInterval(5000)
        self._transfer_monitor.timeout.connect(self._poll_project_transfer)
        self._lock_monitor = QTimer(self)
        self._lock_monitor.setInterval(60 * 1000)
        self._lock_monitor.timeout.connect(self._poll_project_lock)
        self._session_finished = False
        self._startup_pending = False
        self._plugin_startup = None
        self._pending_component: Component | None = None
        self._pending_component_curve_id: str | None = None
        self.settings = QSettings("CurveMole", "CurveMole")
        self.last_peak_function_id = str(
            self.settings.value("last_peak_function", "gaussian")
        )
        from curvemole.gui.project_session import ProjectSession
        self.session = ProjectSession(self)
        from curvemole.gui.uncertainty_controller import UncertaintyController
        self.uncertainty_controller = UncertaintyController(self)
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(20)
        from curvemole.gui.undo_service import UndoService
        self.undo_service = UndoService(self, self.undo_stack)
        self.projectReplaced.connect(self.undo_service.project_replaced)
        self.recovery = RecoveryManager(user_cache_path("CurveMole") / "recovery")
        from curvemole.gui.autosave import AutosaveController
        self._autosave_controller = AutosaveController(self)
        from curvemole.gui.manual_save import ManualSaveController
        self._manual_save_controller = ManualSaveController(self)
        self._tool_docks: list[QDockWidget] = []
        self._tool_tab_filter = DockTabTitleFilter(self)
        self._tab_refresh_pending = False
        self._notebook_widget = None
        self._notebook_placeholder: QWidget | None = None

        self.setWindowTitle(self._title())
        self.setMinimumSize(960, 640)
        from curvemole.gui.screen_fit import default_window_size
        self.resize(default_window_size(self, QSize(1440, 900)))
        self.setAcceptDrops(True)
        icon_path = _resource_path("curvemole.png")
        if icon_path:
            self.setWindowIcon(QIcon(str(icon_path)))

        self.plot_workspace = PlotWorkspace(self.registry)
        self.setCentralWidget(self.plot_workspace)
        # Docked tools may shrink the plot, but never below a usable size.
        self.plot_workspace.setMinimumSize(360, 280)
        self._build_docks()
        self.dock_collapse = DockCollapseControls(self)
        self.statusBar().addPermanentWidget(self.dock_collapse)
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._connect_signals()
        from curvemole.gui.background_controller import BackgroundController
        self.background_controller = BackgroundController(self)
        self.background_controller.install_actions()
        from curvemole.gui.action_shortcuts import install_action_shortcuts
        install_action_shortcuts(self)
        from curvemole.gui.calculator_equation_library import CalculatorEquationLibrary
        self.calculator_equations = CalculatorEquationLibrary(self)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage(self.tr("Ready"), 4000)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(10 * 60 * 1000)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start()
        self.recovery_monitor_timer = QTimer(self)
        self.recovery_monitor_timer.setInterval(60 * 1000)
        self.recovery_monitor_timer.timeout.connect(self._monitor_recovery_count)
        self.recovery_monitor_timer.start()
        self._lock_monitor.start()
        from platformdirs import user_config_path
        self.plugin_manager = PluginManager(self.registry, storage=user_config_path("CurveMole") / "plugins")
        plugin_recovery = self.plugin_manager.start_session()
        self._load_custom_functions()
        # Existing callers passing a project need its plugin functions immediately.
        self._startup_pending = (defer_plugins and not self.project.curves
                                 and os.environ.get("CURVEMOLE_DISABLE_PLUGINS") != "1"
                                 and any(record.get("enabled") for record in self.plugin_manager.installed.values()))
        plugin_load_failures = set() if self._startup_pending else self.plugin_manager.autoload()
        from curvemole.gui.plugin_host import PluginHost
        self.plugin_host = PluginHost(self)
        from curvemole.gui.automation import AutomationRunner
        self.automation_runner = AutomationRunner(self)
        from curvemole.gui.folder_import import FolderImportController
        self.folder_import = FolderImportController(self)
        self._normalise_component_names()
        self._normalise_spectrum_colours()
        if self._startup_pending:
            geometry = self.settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)
            self.apply_theme(str(self.settings.value("theme", "system")))
            self.refresh_all()
            from curvemole.gui.plugin_startup import PluginStartup
            self._plugin_startup = PluginStartup(self, plugin_recovery)
        else:
            self._complete_plugin_startup(plugin_recovery, plugin_load_failures)
        from curvemole.gui.updates import UpdateController
        self._release_update_controller = UpdateController(self)
        from curvemole.gui.fit_undo import FitLifecycleController
        self.fit_lifecycle = FitLifecycleController(self)
        from curvemole.gui.fit_controller import FitController
        self.fit_controller = FitController(self)
        self.fit_controller.install()

    def export_spectra_data(self) -> None:
        """Quick export: one numeric file per selected spectrum with its fit curves."""
        from curvemole.gui.spectrum_export_ui import _export_spectra_data

        _export_spectra_data(self)

    def subtract_background(self) -> None:
        """Subtract model background from the active spectrum (or all, from the dialog)."""
        # Resolved through this module so plugins and tests can substitute the dialog.
        self.background_controller.subtract_current(BackgroundComponentsDialog)

    def subtract_all_backgrounds(self, mark_current_component_ids: list[str] | None = None) -> None:
        self.background_controller.subtract_all(mark_current_component_ids)

    def revert_backgrounds(self, curve_ids: list[str] | None = None) -> None:
        self.background_controller.revert(curve_ids)

    def _complete_plugin_startup(self, recovered: bool, failures: set[str]) -> None:
        if self._session_finished:
            return
        self.plugin_host.refresh()
        self.plugin_host.startup_notice(recovered, failures)
        self.plugin_host.emit("startup")
        if self._session_finished:
            return
        # Plugin docks must exist before restoreState(), especially on Windows.
        self.plugin_host.finish_startup()
        if self._session_finished:
            return
        self._restore_layout()
        self.refresh_all()
        self._startup_pending = False
        self.statusBar().showMessage(self.tr("Ready"), 4000)
        self.plugins_ready.emit()

    def _build_docks(self) -> None:
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(3, 3, 3, 3)
        self.curve_filter = QLineEdit()
        self.curve_filter.setPlaceholderText(self.tr("Search curves…"))
        self.curve_filter.textChanged.connect(self._filter_curves)
        self.curve_tree = CurveTree()
        self.offscreen_active_spectrum = QLabel()
        self.offscreen_active_spectrum.setTextFormat(Qt.TextFormat.PlainText)
        self.offscreen_active_spectrum.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.offscreen_active_spectrum.hide()
        self.curve_tree.offscreenActiveSpectrumChanged.connect(self._show_offscreen_active_spectrum)
        left_layout.addWidget(self.offscreen_active_spectrum)
        left_layout.addWidget(self.curve_filter)
        selection_row = QHBoxLayout()
        self.select_all_curves_button = QPushButton(self.tr("Select all"))
        self.deselect_all_curves_button = QPushButton(self.tr("Deselect all"))
        self.remove_curves_button = QPushButton(self.tr("Remove selected"))
        self.new_series_button = QPushButton(self.tr("New series"))
        self.new_series_button.setToolTip(
            self.tr("Create an empty series. Curves can then be moved into it from the tree menu.")
        )
        self.remove_curves_button.setToolTip(
            self.tr("Remove the selected curve(s) from the project. This can be undone.")
        )
        self.select_all_curves_button.clicked.connect(self.curve_tree.select_all_curves)
        self.deselect_all_curves_button.clicked.connect(self.curve_tree.deselect_all_curves)
        self.remove_curves_button.clicked.connect(self.remove_selected_curves)
        self.new_series_button.clicked.connect(self.create_series)
        selection_row.addWidget(self.select_all_curves_button)
        selection_row.addWidget(self.deselect_all_curves_button)
        selection_row.addWidget(self.remove_curves_button)
        selection_row.addWidget(self.new_series_button)
        selection_row.addStretch(1)
        left_layout.addLayout(selection_row)
        left_layout.addWidget(self.curve_tree)
        self.series_dock = self._dock(self.tr("Series and curves"), left_container, Qt.DockWidgetArea.LeftDockWidgetArea)

        self.model_panel = ModelPanel(self.registry)
        self.model_dock = self._dock(self.tr("Model and parameters"), self.model_panel, Qt.DockWidgetArea.RightDockWidgetArea)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log_dock = self._dock(self.tr("Log"), self.log, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.log_dock.hide()

        self.worksheet = WorksheetPanel()
        self.worksheet_dock = self._dock(self.tr("Worksheet"), self.worksheet, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.worksheet_dock.hide()

        self.diagnostics = DiagnosticsPanel()
        self.diagnostics_dock = self._dock(self.tr("Diagnostics"), self.diagnostics, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.diagnostics_dock.hide()

        self.calculator = CalculatorPanel()
        self.calculator_dock = self._dock(self.tr("Data Calculator"), self.calculator, Qt.DockWidgetArea.RightDockWidgetArea)
        self.calculator_dock.hide()

        self.function_builder = FunctionBuilderPanel(self.registry)
        self.function_dock = self._dock(
            self.tr("Function Builder"), self.function_builder, Qt.DockWidgetArea.RightDockWidgetArea,
        )
        self.function_dock.hide()

        self.uncertainty_panel = UncertaintyPanel()
        # Tabbed beside Model and parameters: at the bottom it took the full
        # window width and squeezed the plot to a few pixels on laptops.
        self.uncertainty_dock = self._dock(self.tr("Uncertainty Analysis"), self.uncertainty_panel, Qt.DockWidgetArea.RightDockWidgetArea)
        self.uncertainty_dock.hide()

        # Keep a Python owner for the initial dock widget.  Passing a temporary
        # QWidget directly to QDockWidget.setWidget() can leave PySide with a
        # dangling wrapper and crash in QLayout::addChildWidget on some systems.
        self._notebook_placeholder = QWidget(self)
        self.notebook_dock = self._dock(
            self.tr("Laboratory notebook"),
            self._notebook_placeholder,
            Qt.DockWidgetArea.RightDockWidgetArea,
        )
        self.notebook_dock.hide()

        self._tool_docks.extend(
            [
                self.model_dock,
                self.calculator_dock,
                self.function_dock,
                self.worksheet_dock,
                self.diagnostics_dock,
                self.uncertainty_dock,
                self.log_dock,
                self.notebook_dock,
            ]
        )
        self.setDockNestingEnabled(True)
        self.setDocumentMode(True)
        self.setTabPosition(Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North)
        self.tabifiedDockWidgetActivated.connect(lambda _: self._queue_tool_tab_refresh())

    def _dock(self, title: str, widget: QWidget, area: Qt.DockWidgetArea) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(title.replace(" ", "_"))
        dock.setWidget(widget)
        self._ensure_dock_viewport(dock)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        if area == Qt.DockWidgetArea.RightDockWidgetArea:
            self._prepare_tool_dock(dock)
        self.addDockWidget(area, dock)
        return dock

    @staticmethod
    def _ensure_dock_viewport(dock: QDockWidget) -> None:
        content = dock.widget()
        if content is not None and not isinstance(content, DockViewport):
            dock.setWidget(DockViewport(content, dock))

    def _prepare_tool_dock(self, dock: QDockWidget) -> None:
        if dock.property("curvemole_full_tab_title") is not None:
            return
        dock.setProperty("curvemole_full_tab_title", dock.windowTitle())
        dock.windowTitleChanged.connect(lambda title, item=dock: self._tool_dock_title_changed(item, title))
        dock.topLevelChanged.connect(lambda floating, item=dock: self._display_tool_dock_title(item, floating))
        self._display_tool_dock_title(dock, dock.isFloating())

    def _tool_dock_title_changed(self, dock: QDockWidget, title: str) -> None:
        if getattr(self, "_setting_tool_dock_title", False):
            return
        dock.setProperty("curvemole_full_tab_title", title)
        self._display_tool_dock_title(dock, dock.isFloating())
        self._queue_tool_tab_refresh()

    def _display_tool_dock_title(self, dock: QDockWidget, floating: bool) -> None:
        full = dock.property("curvemole_full_tab_title")
        visible = full if floating or len(full) <= 25 else full[:22] + "..."
        self._set_tool_dock_caption(dock, visible)
        dock.setToolTip(full)
        self._queue_tool_tab_refresh()

    def _set_tool_dock_caption(self, dock: QDockWidget, caption: str) -> None:
        if dock.windowTitle() != caption:
            self._setting_tool_dock_title = True
            try:
                dock.setWindowTitle(caption)
            finally:
                self._setting_tool_dock_title = False

    def register_tool_dock(self, dock: QDockWidget) -> None:
        """Add a native or plugin tool to the shared tabbed workspace."""
        self.dock_collapse.watch(dock)
        self._ensure_dock_viewport(dock)
        if dock not in self._tool_docks:
            self._tool_docks.append(dock)
        self._prepare_tool_dock(dock)
        if dock is self.model_dock:
            return
        if dock in self.tabifiedDockWidgets(self.model_dock):
            return
        dock.setFloating(False)
        if self.dockWidgetArea(dock) != Qt.DockWidgetArea.RightDockWidgetArea:
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        if dock.isHidden():
            return
        self.tabifyDockWidget(self.model_dock, dock)
        self._queue_tool_tab_refresh()

    def activate_tool_dock(self, dock: QDockWidget) -> None:
        dock.show()
        self.register_tool_dock(dock)
        dock.raise_()
        self._queue_tool_tab_refresh()

    def _queue_tool_tab_refresh(self) -> None:
        if not self._tab_refresh_pending:
            self._tab_refresh_pending = True
            QTimer.singleShot(0, self._configure_tool_tabs)

    def _configure_tool_tabs(self) -> None:
        self._tab_refresh_pending = False
        # QMainWindow owns its dock tab bars; QTabWidget bars inside panels are separate.
        for bar in self.findChildren(QTabBar):
            if bar.parent() is not self:
                continue
            if not bar.property("curvemole_tool_tabs"):
                bar.installEventFilter(self._tool_tab_filter)
                bar.setProperty("curvemole_tool_tabs", True)
                icons = resources.files("curvemole.resources")
                left_arrow = Path(str(icons.joinpath("chevron-left.svg"))).as_posix()
                right_arrow = Path(str(icons.joinpath("chevron-right.svg"))).as_posix()
                bar.setStyleSheet(f"""
                    QTabBar::scroller {{ width: {DockTabTitleFilter.SCROLLER_WIDTH}px; }}
                    QToolButton#ScrollLeftButton, QToolButton#ScrollRightButton {{
                        background: palette(button);
                        border: 1px solid palette(mid);
                        border-radius: 4px;
                        margin: 2px 1px;
                    }}
                    QToolButton#ScrollLeftButton:disabled,
                    QToolButton#ScrollRightButton:disabled {{
                        background: transparent;
                        border-color: transparent;
                    }}
                    QToolButton#ScrollLeftButton:enabled:hover,
                    QToolButton#ScrollRightButton:enabled:hover {{
                        background: palette(midlight);
                        border-color: palette(highlight);
                    }}
                    QToolButton#ScrollLeftButton:enabled:pressed,
                    QToolButton#ScrollRightButton:enabled:pressed {{
                        background: palette(mid);
                    }}
                    QToolButton#ScrollLeftButton::left-arrow {{
                        image: url("{left_arrow}");
                        width: 16px;
                        height: 16px;
                    }}
                    QToolButton#ScrollRightButton::right-arrow {{
                        image: url("{right_arrow}");
                        width: 16px;
                        height: 16px;
                    }}
                """)
                for name, description in (
                    ("ScrollLeftButton", self.tr("Scroll tabs left")),
                    ("ScrollRightButton", self.tr("Scroll tabs right")),
                ):
                    button = bar.findChild(QToolButton, name)
                    if button is not None:
                        button.setAccessibleName(description)
                        button.setToolTip(description)
            bar.setExpanding(False)
            bar.setUsesScrollButtons(True)
            bar.setElideMode(Qt.TextElideMode.ElideNone)
            self._tool_tab_filter.format_titles(bar)

    def _apply_tabbed_tool_layout(self) -> None:
        """Create the shared tabs without transiently showing every dock.

        Showing and immediately hiding a group of native dock windows while the
        main window is still being constructed can crash some Linux Qt window
        system plugins.  QMainWindow can tabify hidden docks directly, so keep
        their visibility stable throughout the migration.
        """
        hidden = {dock: dock.isHidden() for dock in self._tool_docks}
        for dock in self._tool_docks:
            dock.setFloating(False)
            if self.dockWidgetArea(dock) != Qt.DockWidgetArea.RightDockWidgetArea:
                self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        for dock in self._tool_docks:
            if dock is not self.model_dock and not hidden[dock]:
                self.tabifyDockWidget(self.model_dock, dock)
        for dock, was_hidden in hidden.items():
            dock.setVisible(not was_hidden)
        self.model_dock.show()
        self._queue_tool_tab_refresh()

    def _tool_action(self, dock: QDockWidget, text: str) -> QAction:
        action = dock.toggleViewAction()
        action.setText(text)
        action.triggered.connect(
            lambda visible, item=dock: self.activate_tool_dock(item) if visible else None
        )
        return action

    def _open_tool_action(
        self, dock: QDockWidget, text: str, open_tool: Callable[[], None] | None = None,
    ) -> QAction:
        action = QAction(text, self, checkable=True)
        dock.visibilityChanged.connect(action.setChecked)

        def show_and_sync() -> None:
            if open_tool is None:
                self._show_tool_dock(dock)
            else:
                open_tool()
            # Clicking a checked QAction flips it before triggered(). Its
            # check state follows the dock tab, including repeated clicks.
            action.setChecked(dock.isVisible() and not dock.visibleRegion().isEmpty())

        action.triggered.connect(show_and_sync)
        return action

    def _show_tool_dock(self, dock: QDockWidget) -> None:
        """Open or select a tool in its current dock area."""
        if dock.isHidden():
            if (not dock.isFloating()
                    and self.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea
                    and not self.tabifiedDockWidgets(dock)):
                self.activate_tool_dock(dock)
                return
            dock.show()
        if dock.isFloating():
            if not dock.isActiveWindow():
                dock.raise_()
                dock.activateWindow()
        elif dock.visibleRegion().isEmpty():
            dock.raise_()

    def _build_actions(self) -> None:
        self.new_action = QAction(_resource_icon("new-project.svg"), self.tr("New project"), self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.new_project)
        self.open_action = QAction(_resource_icon("open-project.svg"), self.tr("Open project…"), self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(lambda checked=False: self.open_project())
        self.import_action = QAction(_resource_icon("import-data.svg"), self.tr("Import data…"), self)
        self.import_action.setShortcut("Ctrl+I")
        self.import_action.triggered.connect(lambda checked=False: self.import_data())
        self.save_action = QAction(_resource_icon("save-project.svg"), self.tr("Save project"), self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_project)
        self.save_as_action = QAction(self.tr("Save project as…"), self)
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.save_as_action.triggered.connect(lambda: self.save_project(save_as=True))
        self.portable_action = QAction(self.tr("Save portable copy…"), self)
        self.portable_action.triggered.connect(self.save_portable_copy)
        self.export_action = QAction(self.tr("Export analysis bundle…"), self)
        self.export_action.setShortcut("Ctrl+E")
        self.export_action.triggered.connect(self.export_analysis)
        self.export_parameters_action = QAction(self.tr("Quick export: function parameters…"), self)
        self.export_parameters_action.triggered.connect(self.export_parameters)
        self.export_view_action = QAction(self.tr("Quick export: current view with Matplotlib…"), self)
        self.export_view_action.triggered.connect(self.export_current_view)
        self.export_view_action.setToolTip(self.tr("Save the visible curves, offsets, background display, log scales and zoom as PNG, SVG or PDF."))
        self.notebook_action = self._open_tool_action(
            self.notebook_dock, self.tr("Laboratory notebook"), self.open_notebook,
        )
        self.notebook_action.setIcon(_resource_icon("laboratory-notebook.svg"))
        self.notebook_action.setToolTip(self.tr("Project notes and descriptions of series, spectra and fit functions"))
        self.notebook_dock.visibilityChanged.connect(self._notebook_visibility_changed)
        self.recovery_action = QAction(self.tr("Recoverable sessions…"), self)
        self.recovery_action.triggered.connect(lambda checked=False: self.show_recovery_sessions())
        self.recent_projects_menu = QMenu(self.tr("Recent projects"), self)
        self.recent_projects_menu.aboutToShow.connect(self._refresh_recent_projects)
        self.quit_action = QAction(self.tr("Quit"), self)
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_action.triggered.connect(self.close)

        self.undo_action = self.undo_stack.createUndoAction(self, self.tr("Undo"))
        self.undo_action.setIcon(_resource_icon("undo.svg"))
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.redo_action = self.undo_stack.createRedoAction(self, self.tr("Redo"))
        self.redo_action.setIcon(_resource_icon("redo.svg"))
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)

        self.model_action = self._open_tool_action(self.model_dock, self.tr("Model and parameters"))
        self.model_action.setIcon(_resource_icon("model-parameters.svg"))
        self.calculator_action = self._open_tool_action(self.calculator_dock, self.tr("Data Calculator"))
        self.calculator_action.setIcon(_resource_icon("calculator.svg"))
        self.calculator_action.setToolTip(self.tr("Data Calculator"))
        self.edit_data_points_action = QAction(self.tr("Edit data points…"), self, checkable=True)
        self.edit_data_points_action.setToolTip(self.tr(
            "Select, drag or delete individual points of the active dataset. Changes support Undo/Redo."))
        self.edit_data_points_action.toggled.connect(self._set_data_point_edit_mode)
        editor = self.plot_workspace.point_editor
        editor.activeChanged.connect(self._data_point_edit_mode_changed)
        editor.moveRequested.connect(self._move_data_point)
        editor.deleteRequested.connect(self._delete_data_point)
        self.worksheet_action = self._tool_action(self.worksheet_dock, self.tr("Worksheet"))
        self.function_action = self._open_tool_action(self.function_dock, self.tr("Function Builder"))
        self.uncertainty_action = self._open_tool_action(
            self.uncertainty_dock, self.tr("Uncertainty Analysis")
        )
        self.function_action.setIcon(_resource_icon("function-builder.svg"))
        self.function_action.setToolTip(self.tr("Function Builder"))
        self.uncertainty_action.setIcon(_resource_icon("uncertainty-analysis.svg"))
        self.uncertainty_action.setToolTip(self.tr("Uncertainty Analysis"))
        self.diagnostics_action = self._tool_action(self.diagnostics_dock, self.tr("Diagnostics"))
        self.log_action = self._tool_action(self.log_dock, self.tr("Log"))
        self.plugins_action = QAction(self.tr("Plugin Manager…"), self)
        self.plugins_action.triggered.connect(self.show_plugin_manager)

        self.add_component_action = QAction(self.tr("Add component…"), self)
        self.add_component_action.setIcon(_resource_icon("add-peak.svg"))
        self.add_component_action.setToolTip(self.tr("Add component…"))
        self.add_component_action.setShortcut("Ctrl++")
        self.add_component_action.triggered.connect(self.add_component)
        self.edit_points_action = QAction(self.tr("Edit function points…"), self)
        self.edit_points_action.setToolTip(self.tr(
            "Edit function points\nReopen saved control points to move, add or delete them. "
            "For background functions, temporarily show data without background subtraction. "
            "Recorded data operations remain unchanged; Cancel discards point edits."
        ))
        self.edit_points_action.triggered.connect(lambda checked=False: self.edit_component_points(self.selected_component_id))
        self.model_panel.edit_points_action = self.edit_points_action
        self.model_panel.editPointsRequested.connect(
            lambda curve_id, component_id: self.edit_component_points(component_id))
        self.edit_points_action.setEnabled(False)
        self.quick_peak_action = QAction(self.tr("Quick Peak"), self)
        self.quick_peak_action.setIcon(_resource_icon("add-peak.svg"))
        self.quick_peak_action.setToolTip(
            self.tr("Quick Peak\nAdd the last selected peak function without reopening the component dialog.")
        )
        self.quick_peak_action.triggered.connect(self.quick_peak)
        self.copy_fit_action = QAction(self.tr("Copy fit…"), self)
        self.copy_fit_action.triggered.connect(self.copy_fit)
        self.copy_fit_next_action = QAction(self.tr("Copy fit to next…"), self)
        self.copy_fit_next_action.triggered.connect(lambda: self.copy_fit(next_only=True))
        self.find_peaks_action = QAction(self.tr("Find peaks…"), self)
        self.find_peaks_action.triggered.connect(self.find_peaks)
        self.mask_tolerance_action = QAction(self.tr("Mask transfer tolerance…"), self)
        self.mask_tolerance_action.triggered.connect(self.set_mask_tolerance)
        self.subtract_background_action = QAction(self.tr("Subtract background…"), self)
        self.subtract_background_action.setIcon(_resource_icon("subtract-background.svg"))
        self.subtract_background_action.setToolTip(
            self.tr("Subtract background…\nSubtract selected model functions that are marked as background.")
        )
        self.subtract_background_action.triggered.connect(self.subtract_background)

        self.fit_action = QAction(self.tr("Fit…"), self)
        self.fit_action.setIcon(_resource_icon("fit.svg"))
        self.fit_action.setToolTip(self.tr("Fit…"))
        self.fit_action.setShortcut("F5")
        self.fit_action.triggered.connect(self.start_fit)
        self.quick_fit_action = QAction(self.tr("Quick Fit"), self)
        self.quick_fit_action.setIcon(_resource_icon("quick-fit.svg"))
        self.quick_fit_action.setToolTip(
            self.tr("Quick Fit\nAlways use Single/Independent fitting with the current "
                    "solver, loss and algorithm settings, or defaults on first use.")
        )
        self.quick_fit_action.triggered.connect(self.quick_fit)
        self.resume_action = QAction(self.tr("Continue sequential fit"), self)
        self.resume_action.setIcon(_resource_icon("resume.svg"))
        self.resume_action.setEnabled(False)
        self.resume_action.triggered.connect(self.resume_sequence)
        self.cancel_action = QAction(self.tr("Cancel running task"), self)
        self.cancel_action.setIcon(_resource_icon("cancel.svg"))
        self.cancel_action.setEnabled(False)
        self.cancel_action.triggered.connect(self.cancel_task)

        self.reset_layout_action = QAction(self.tr("Reset layout"), self)
        self.reset_layout_action.triggered.connect(self.reset_layout)
        self.auto_axes_action = QAction(self.tr("View all"), self)
        mask_icon = _resource_icon("mask.svg", checked_filename="mask-active.svg")
        self.plot_workspace.mask_action.setIcon(mask_icon)
        self.auto_axes_action.setIcon(_resource_icon("view-all.svg"))
        self.auto_axes_action.setToolTip(self.tr("View all\nFrame all experimental data, including masked regions."))
        self.plot_workspace.view_active_action.setIcon(_resource_icon("view-active.svg"))
        self.plot_workspace.view_active_action.setToolTip(self.tr("View unmasked\nFrame only unmasked experimental data."))
        self.auto_axes_action.triggered.connect(self.plot_workspace.auto_range)
        self.log_x_action = QAction(self.tr("Logarithmic x"), self, checkable=True)
        self.log_x_action.toggled.connect(self.plot_workspace.set_log_x)
        self.log_y_action = QAction(self.tr("Logarithmic y"), self, checkable=True)
        self.log_y_action.toggled.connect(self.plot_workspace.set_log_y)
        self.reverse_x_action = QAction(self.tr("Reverse x"), self, checkable=True)
        self.reverse_x_action.toggled.connect(self.plot_workspace.set_reverse_x)
        self.reverse_y_action = QAction(self.tr("Reverse y"), self, checkable=True)
        self.reverse_y_action.toggled.connect(self.plot_workspace.set_reverse_y)
        self.lock_view_action = QAction(self.tr("Lock plot view"), self, checkable=True)
        self.lock_view_action.toggled.connect(self.plot_workspace.set_view_locked)
        self.plot_appearance_action = QAction(self.tr("Plot appearance…"), self)
        self.plot_appearance_action.setToolTip(
            self.tr("Customize lines, points, symbols, colours, residuals and grid rendering.")
        )
        self.plot_appearance_action.triggered.connect(self.configure_plot_appearance)
        self.system_theme_action = QAction(self.tr("System theme"), self, checkable=True)
        self.light_theme_action = QAction(self.tr("Light theme"), self, checkable=True)
        self.dark_theme_action = QAction(self.tr("Dark theme"), self, checkable=True)
        for action, theme in (
            (self.system_theme_action, "system"),
            (self.light_theme_action, "light"),
            (self.dark_theme_action, "dark"),
        ):
            action.triggered.connect(lambda checked=False, selected=theme: self.apply_theme(selected))

        self.quick_start_action = QAction(self.tr("Quick Start"), self)
        self.quick_start_action.setShortcut(QKeySequence.StandardKey.HelpContents)
        self.quick_start_action.triggered.connect(lambda: self.open_documentation("quick-start.md"))
        self.manual_action = QAction(self.tr("User manual"), self)
        self.manual_action.triggered.connect(lambda: self.open_documentation("manual.md"))
        self.shortcuts_action = QAction(self.tr("Shortcuts…"), self)
        self.shortcuts_action.setToolTip(self.tr("Browse mouse gestures and current keyboard shortcuts."))
        self.shortcuts_action.triggered.connect(self.show_shortcuts)
        self.update_action = QAction(self.tr("Check for updates"), self)
        self.update_action.triggered.connect(
            lambda checked=False: self.check_for_updates(force=True)
        )
        self.report_action = QAction(self.tr("Report a problem"), self)
        self.report_action.triggered.connect(
            lambda: self._open_external("https://github.com/SebRoLENS/curvemole/issues")
        )
        self.about_action = QAction(self.tr("About CurveMole"), self)
        self.about_action.triggered.connect(self.show_about)
        # Contributions registered by extension modules (gui.window_extensions).
        window_extensions.run(self, "actions")

    def configure_plot_appearance(self) -> None:
        with transient_widget(PlotAppearanceDialog(self.plot_workspace.plot_appearance(), self)) as dialog:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.plot_workspace.set_plot_appearance(dialog.settings())

    def _build_menus(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu(self.tr("&File"))
        file_menu.addActions([self.new_action, self.open_action, self.import_action])
        file_menu.addMenu(self.recent_projects_menu)
        file_menu.addSeparator()
        file_menu.addActions([self.save_action, self.save_as_action, self.portable_action])
        file_menu.addAction(self.export_action)
        file_menu.addAction(self.export_parameters_action)
        file_menu.addAction(self.export_view_action)
        file_menu.addAction(self.recovery_action)
        file_menu.addAction(self.plugins_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        edit_menu = menu.addMenu(self.tr("&Edit"))
        edit_menu.addActions([self.undo_action, self.redo_action])

        # Each command lives in one menu; the toolbar may repeat it.
        data_menu = menu.addMenu(self.tr("&Data"))
        self.data_menu = data_menu
        data_menu.addActions(
            [
                self.edit_data_points_action,
                self.subtract_background_action,
                self.calculator_action,
            ]
        )
        data_menu.addSeparator()
        data_menu.addActions([self.plot_workspace.mask_action, self.mask_tolerance_action])

        model_menu = menu.addMenu(self.tr("&Model"))
        model_menu.addActions(
            [
                self.add_component_action,
                self.edit_points_action,
                self.quick_peak_action,
                self.copy_fit_action,
                self.copy_fit_next_action,
                self.find_peaks_action,
                self.function_action,
            ]
        )

        fit_menu = menu.addMenu(self.tr("&Fit"))
        fit_menu.addActions(
            [
                self.fit_action,
                self.quick_fit_action,
                self.resume_action,
                self.cancel_action,
                self.uncertainty_action,
            ]
        )

        view_menu = menu.addMenu(self.tr("&View"))
        view_menu.addActions(
            [
                self.series_dock.toggleViewAction(),
                self.model_dock.toggleViewAction(),
                self.worksheet_action,
                self.diagnostics_action,
                self.log_action,
            ]
        )
        view_menu.addSeparator()
        view_menu.addAction(self.plot_appearance_action)
        themes = view_menu.addMenu(self.tr("Theme"))
        themes.addActions([self.system_theme_action, self.light_theme_action, self.dark_theme_action])
        axes = view_menu.addMenu(self.tr("Axes"))
        axes.addActions(
            [
                self.auto_axes_action,
                self.plot_workspace.view_active_action,
                self.log_x_action,
                self.log_y_action,
                self.reverse_x_action,
                self.reverse_y_action,
                self.lock_view_action,
            ]
        )
        view_menu.addSeparator()
        view_menu.addAction(self.reset_layout_action)

        self.tools_menu = menu.addMenu(self.tr("&Tools"))
        # Calculator (Data), Function Builder (Model) and Uncertainty Analysis
        # (Fit) are listed once, in their workflow menus. Tools holds the
        # notebook and commands added by plugins.
        self.tools_menu.addAction(self.notebook_action)

        self.help_menu = menu.addMenu(self.tr("&Help"))
        self.help_menu.addActions(
            [self.quick_start_action, self.manual_action, self.shortcuts_action,
             self.update_action, self.report_action, self.about_action]
        )
        # Contributions registered by extension modules (gui.window_extensions).
        window_extensions.run(self, "menus")

    def _build_toolbar(self) -> None:
        toolbar = QToolBar(self.tr("Main toolbar"), self)
        toolbar.setObjectName("Main_toolbar")
        toolbar.setMovable(True)
        toolbar.setIconSize(QSize(40, 40))
        self.addToolBar(toolbar)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        toolbar.addActions([self.open_action, self.import_action, self.save_action])
        toolbar.addSeparator()
        toolbar.addActions([self.undo_action, self.redo_action])
        toolbar.addSeparator()
        toolbar.addActions([
            self.auto_axes_action, self.plot_workspace.view_active_action,
        ])
        toolbar.addSeparator()
        toolbar.addAction(self.subtract_background_action)
        # Background controls inserted later stay inside this group.
        self._background_toolbar_separator = toolbar.addSeparator()
        toolbar.addAction(self.plot_workspace.mask_action)
        toolbar.addSeparator()
        toolbar.addActions([self.add_component_action, self.quick_peak_action])
        # The quick-function selector is inserted before this separator.
        self._fit_toolbar_separator = toolbar.addSeparator()
        toolbar.addActions([
            self.fit_action, self.quick_fit_action, self.cancel_action,
        ])
        spacer = QWidget(toolbar)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        toolbar.addWidget(spacer)
        toolbar.addSeparator()
        tools = [
            self.model_action, self.notebook_action, self.calculator_action,
            self.function_action, self.uncertainty_action,
        ]
        toolbar.addActions(tools)
        for action in tools:
            toolbar.widgetForAction(action).setStyleSheet(
                "QToolButton:checked { background: palette(button); "
                "border: 2px solid palette(highlight); border-radius: 6px; }"
            )
        # Contributions registered by extension modules (gui.window_extensions).
        window_extensions.run(self, "toolbar")

    def _connect_signals(self) -> None:
        self.curve_tree.activeCurveChanged.connect(self._activate_tree_curve)
        self.curve_tree.noteRequested.connect(self.open_attached_note)
        self.curve_tree.seriesActivated.connect(self._set_active_series)
        self.curve_tree.itemSelectionChanged.connect(self._selection_changed)
        self.curve_tree.curveVisibilityChanged.connect(self._set_visibility)
        self.curve_tree.curveRenamed.connect(self._rename_curve)
        self.curve_tree.seriesRenamed.connect(self._rename_series)
        self.curve_tree.seriesRenameRequested.connect(self._prompt_rename_series)
        self.curve_tree.seriesDescriptionRequested.connect(self.describe_series)
        self.curve_tree.curveDescriptionRequested.connect(self.describe_spectrum)
        self.curve_tree.curveColourRequested.connect(self.choose_curve_colour)
        self.curve_tree.seriesPaletteRequested.connect(self.apply_series_palette)
        self.curve_tree.curvesPaletteRequested.connect(self.apply_selected_palette)
        self.curve_tree.newSeriesRequested.connect(self.create_series)
        self.curve_tree.curvesMoveRequested.connect(self.move_curves_to_series)
        self.curve_tree.curvesReorderRequested.connect(self.reorder_curves)
        self.curve_tree.seriesMergeRequested.connect(self.merge_series)
        self.curve_tree.rowMoveRequested.connect(self.move_data_row)
        self.model_panel.componentSelected.connect(self._set_component)
        self.model_panel.addRequested.connect(self.add_component)
        self.model_panel.duplicateRequested.connect(self.duplicate_component)
        self.model_panel.deleteRequested.connect(self.delete_component)
        self.model_panel.moveRequested.connect(self.move_component)
        self.model_panel.components.rowMoveRequested.connect(self.move_function_row)
        self.model_panel.enabledRequested.connect(self.enable_component)
        self.model_panel.backgroundRequested.connect(self.set_component_background)
        self.model_panel.compositionRequested.connect(self.set_component_operator)
        self.model_panel.compositionOrderRequested.connect(self.edit_calculation_order)
        self.model_panel.parameterChangeRequested.connect(self.change_parameter)
        self.model_panel.parameterLinkRequested.connect(self.edit_parameter_link)
        self.model_panel.bulkFixedRequested.connect(self.set_component_fixed)
        self.model_panel.copyFitRequested.connect(self.copy_fit)
        self.model_panel.copyFitNextRequested.connect(lambda: self.copy_fit(next_only=True))
        self.model_panel.descriptionRequested.connect(self.describe_function)
        self.model_panel.noteRequested.connect(self.open_attached_note)
        self.plot_workspace.componentSelected.connect(self._set_component)
        self.plot_workspace.componentOnCurveSelected.connect(self._set_component_on_curve)
        self.plot_workspace.maskPointRequested.connect(self.mask_point)
        self.plot_workspace.maskRangeRequested.connect(self.mask_range)
        self.plot_workspace.unmaskPointRequested.connect(lambda x: self.mask_point(x, unmask=True))
        self.plot_workspace.unmaskRangeRequested.connect(lambda a, b: self.mask_range(a, b, unmask=True))
        self.plot_workspace.peakDragged.connect(self.drag_peak)
        self.plot_workspace.widthDragged.connect(self.drag_width)
        self.plot_workspace.splineNodeDragged.connect(self.drag_spline_node)
        self.plot_workspace.peakPlacementFinished.connect(self._graphical_peak_placed)
        self.plot_workspace.splinePlacementFinished.connect(self._graphical_spline_placed)
        self.plot_workspace.placementCancelled.connect(self._graphical_placement_cancelled)
        self.calculator.applyRequested.connect(self.apply_calculator)
        self.calculator.saveFormulaRequested.connect(self.save_custom_formula)
        self.function_builder.functionAdded.connect(lambda _: self._notify(self.tr("Function library updated.")))
        self.worksheet_dock.visibilityChanged.connect(self.refresh_worksheet)
        self.uncertainty_panel.runRequested.connect(self.start_uncertainty)
        self.uncertainty_panel.deleteRequested.connect(self.delete_uncertainty_analysis)
        self.model_panel.displayMethodChanged.connect(self._select_uncertainty_display)
        self.model_panel.uncertaintyRequested.connect(self._show_uncertainty_analysis)
        self.uncertainty_panel.method.currentIndexChanged.connect(self._uncertainty_method_changed)
        self._sync_uncertainty_method()
        self.model_panel.renameRequested.connect(self.rename_function)
        self.model_panel.reorderRequested.connect(self.reorder_functions)
        self.model_panel.reorderRulesRequested.connect(self.edit_reorder_rules)
        # Contributions registered by extension modules (gui.window_extensions).
        window_extensions.run(self, "signals")

    def _update_uncertainty_tags(self) -> None:
        return self.uncertainty_controller._update_uncertainty_tags()

    def _sync_uncertainty_method(self) -> None:
        return self.uncertainty_controller._sync_uncertainty_method()

    def _uncertainty_method_changed(self, _index: int) -> None:
        return self.uncertainty_controller._uncertainty_method_changed(_index)

    def refresh_all(self) -> None:
        previous_project = getattr(self, "_displayed_project_id", id(self.project))
        self._sync_uncertainty_method()
        # A hidden notebook is lazy but may still own the previous project.
        # Dispose its stale panel without rebuilding another hidden notebook.
        notebook = self._notebook_widget
        if (notebook is not None and notebook.project is not self.project
                and self.notebook_dock.isHidden()):
            self._notebook_widget = None
            self._notebook_placeholder = QWidget(self)
            self.notebook_dock.widget().setWidget(self._notebook_placeholder)
        # Restoring Qt's dock state can expose the lazy placeholder without the
        # toolbar action running. Also rebind an open notebook on project changes.
        if not self.notebook_dock.isHidden():
            self._ensure_notebook_widget()
        self.setWindowTitle(self._title())
        selected = self.curve_tree.populate(self.project, self.active_curve_id)
        self.model_panel.set_context(
            self.project,
            self.active_curve_id,
            len(selected),
            self.selected_component_id,
        )
        self.copy_fit_next_action.setEnabled(self.model_panel.copy_fit_next_button.isEnabled())
        self.plot_workspace.set_context(
            self.project,
            self.active_curve_id,
            selected,
            self.selected_component_id,
        )
        self.calculator_equations.refresh()
        self.calculator.set_curves(self.project, self.active_curve_id, selected)
        if hasattr(self, "restore_original_controller"):
            self.restore_original_controller.sync()
        self.function_builder.set_project(self.project)
        self.uncertainty_panel.set_parameters(self.project, self.active_curve_id)
        self.refresh_worksheet()
        self._refresh_diagnostics()
        if hasattr(self, "plugin_host"):
            self.plugin_host.emit("project_refreshed")
        self._displayed_project_id = id(self.project)
        if previous_project != self._displayed_project_id:
            from curvemole.gui.garbage_collection import ensure_gui_garbage_collection

            ensure_gui_garbage_collection().retire_project()
        controller = getattr(self, "fit_controller", None)
        if controller is not None:
            controller.sync()

    def new_project(self) -> None:
        return self.session.new_project()

    def open_project(self, path: str | Path | None = None) -> None:
        return self.session.open_project(path)

    def _can_replace_project(self) -> bool:
        return self.session._can_replace_project()

    def _clear_project_session_state(self) -> None:
        return self.session._clear_project_session_state()

    def import_data(self, paths: list[str] | None = None, *, preview_columns=None) -> None:
        if not self._ensure_editable():
            return
        if paths is None:
            from curvemole.gui.import_file_picker import choose_import_files
            paths, preview_columns = choose_import_files(self)
        if not paths:
            return
        series = Series(self._next_series_name())
        series.metadata["palette"] = self.default_series_palette()
        default_palette = self._automatic_palette(series.metadata["palette"])
        colour_offset = len(self.project.curves)
        imported_ids = set()
        destination_id = None
        shared_mapping = None
        shared_config = None
        position_mapping = None
        use_positions = False
        apply_all = False
        batch = getattr(self, "_external_import_batch", None)
        if batch is not None and paths is not batch.paths:
            batch = None
        try:
            for index, path in enumerate(paths):
                if batch is not None:
                    batch.index = index
                curves = None
                file_mapping = shared_mapping
                missing_column = None
                remember_choice = False
                if apply_all:
                    preview = ImportPreview(path, shared_config)
                    try:
                        curves = preview.curves(position_mapping if use_positions else shared_mapping)
                    except ImportColumnError as exc:
                        missing_column = str(exc)
                        if not use_positions:
                            try:
                                preview.check_columns(position_mapping)
                            except ImportColumnError:
                                pass
                            else:
                                decision, remember_choice = self._ask_import_column_positions(
                                    Path(path).name, missing_column,
                                )
                                if decision == "cancel":
                                    return
                                if decision == "position":
                                    use_positions = remember_choice
                                    curves = preview.curves(position_mapping)
                if curves is None:
                    with transient_widget(ImportMappingDialog(path, batch_size=len(paths), parent=self)) as dialog:
                        if missing_column is not None:
                            dialog.setWindowTitle(self.tr("Import data — check column mapping"))
                            warning = QLabel(self.tr("Check the X and Y columns for this file.") + "\n" + missing_column)
                            warning.setTextFormat(Qt.TextFormat.PlainText)
                            warning.setWordWrap(True)
                            dialog.layout().insertWidget(1, warning)
                        choice = (preview_columns or {}).get(str(Path(path).resolve()))
                        if choice:
                            xi, yi = choice
                            if xi < dialog.x_column.count() and yi < dialog.y_columns.count():
                                dialog.x_column.setCurrentIndex(xi)
                                for row in range(dialog.y_columns.count()):
                                    dialog.y_columns.item(row).setCheckState(
                                        Qt.CheckState.Checked if row == yi else Qt.CheckState.Unchecked)
                        dialog.series_name.setText(series.name)
                        dialog.set_series_destinations(self.project.dataset.series, destination_id)
                        if index > 0:
                            dialog.apply_all.setChecked(apply_all and missing_column is None)
                            dialog.destination_series.setEnabled(False)
                            dialog.series_name.setEnabled(False)
                        dialog.existing_series_names = {item.name for item in self.project.dataset.series}
                        if batch is not None:
                            batch.dialog = dialog
                        try:
                            accepted = dialog.exec() == dialog.DialogCode.Accepted
                        finally:
                            if batch is not None:
                                batch.dialog = None
                        if not accepted:
                            return
                        if index == 0:
                            destination_id = dialog.destination_series.currentData()
                            series.name = dialog.series_name.text().strip()
                        file_mapping = dialog.mapping()
                        file_config = dialog.config()
                        share_mapping = dialog.apply_all.isChecked()
                        if missing_column is None or remember_choice or share_mapping:
                            shared_mapping = file_mapping
                            shared_config = file_config
                            apply_all = share_mapping
                            use_positions = dialog.match_column_positions.isChecked()
                            if apply_all:
                                position_mapping = shared_mapping.by_position(dialog.inspection.columns)
                    curves = import_file(path, file_mapping, file_config)
                for curve in curves:
                    curve.colour = default_palette[
                        (colour_offset + len(series.curves)) % len(default_palette)
                    ]
                    if curve.id in imported_ids:
                        raise ValueError("Imported spectra contain duplicate identifiers.")
                    imported_ids.add(curve.id)
                    series.curves.append(curve)
            if batch is not None:
                batch.accepting = False
            destination = next((item for item in self.project.dataset.series if item.id == destination_id), None)
            if destination_id is not None and destination is None:
                raise ValueError("The destination series is no longer available.")
            if destination is not None:
                palette = self._palette_for_appending(destination)
                for index, curve in enumerate(series.curves):
                    curve.colour = palette[index % len(palette)]
            self._commit_import(series, destination)
            self._notify(self.tr("Imported ") + f"{len(series.curves)} " + self.tr("curve(s)."))
            from curvemole.core.importers import non_numeric_summary

            if (issues := non_numeric_summary(series.curves)) is not None:
                self._notify(issues, warning=True)
        except Exception as exc:
            self._show_error(self.tr("Import data"), exc)

    def _commit_import(self, series: Series, destination: Series | None) -> None:
        acquisition = Project()
        acquisition.add_series(series)
        self.folder_import.commit(
            acquisition, destination=destination, automatic=False, follow=True,
        )

    def _ask_import_column_positions(self, file_name: str, reason: str) -> tuple[str, bool]:
        with transient_widget(QMessageBox(self)) as prompt:
            prompt.setIcon(QMessageBox.Icon.Question)
            prompt.setWindowTitle(self.tr("Import data — different column headers"))
            prompt.setTextFormat(Qt.TextFormat.PlainText)
            prompt.setText(self.tr("The column headers in {file} do not match the batch mapping.").format(
                file=file_name,
            ))
            prompt.setInformativeText(self.tr(
                "Use the same column positions for this file, or choose columns manually?"
            ))
            remember = QCheckBox(self.tr("Apply this choice to the remaining files in this batch"), prompt)
            prompt.setCheckBox(remember)
            prompt.setDetailedText(reason)
            position = prompt.addButton(self.tr("Match columns by position"), QMessageBox.ButtonRole.AcceptRole)
            manual = prompt.addButton(self.tr("Choose columns manually"), QMessageBox.ButtonRole.ActionRole)
            prompt.addButton(QMessageBox.StandardButton.Cancel)
            prompt.setDefaultButton(manual)
            prompt.exec()
            if prompt.clickedButton() is position:
                return "position", remember.isChecked()
            if prompt.clickedButton() is manual:
                return "manual", remember.isChecked()
            return "cancel", False

    def save_project(self, *, save_as: bool = False) -> bool:
        if self._manual_save_controller.busy and not self._manual_save_controller.wait():
            return False
        if self.project.read_only and not save_as:
            save_as = True
        path = None if save_as else self.project.path
        if path is None:
            selected, _ = QFileDialog.getSaveFileName(
                self,
                self.tr("Save CurveMole project"),
                f"{self.project.name}.fitproj",
                self.tr("CurveMole projects (*.fitproj)"),
            )
            if not selected:
                return False
            path = Path(selected)
        return self._manual_save_controller.save(path, save_project)

    def save_portable_copy(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Save portable copy"),
            f"{self.project.name}-portable.fitproj",
            self.tr("CurveMole projects (*.fitproj)"),
        )
        if not selected:
            return
        self._manual_save_controller.save(selected, save_project, portable=True)

    def open_notebook(self) -> None:
        if self.notebook_dock.isHidden():
            self._ensure_notebook_widget(refresh=True)
        self._show_tool_dock(self.notebook_dock)

    def _notebook_visibility_changed(self, _visible: bool) -> None:
        # Qt reports False for an open dock behind another tab as well. Such a
        # dock still needs its contents ready when the user selects its tab.
        if not self.notebook_dock.isHidden():
            self._ensure_notebook_widget()

    def _ensure_notebook_widget(self, *, refresh: bool = False) -> None:
        """Populate the dock without changing its visibility or active tool tab."""
        from curvemole.gui.notebook import LaboratoryNotebookDialog

        editable = not self.task_running and not self.project.read_only
        current = self._notebook_widget
        if (
            current is None
            or current.project is not self.project
            or current.editable != editable
        ):
            panel = LaboratoryNotebookDialog(
                self.project, self.notebook_dock, editable=editable, embedded=True
            )
            # The viewport owns its content and deletes the previous widget.
            # Publish the new panel first in case replacing it triggers a refresh.
            self._notebook_widget = panel
            self._notebook_placeholder = None
            self.notebook_dock.widget().setWidget(panel)
        elif refresh:
            self.project.notebook.sync(self.project)
            current._populate()

    def open_attached_note(self, reference) -> None:
        kind, object_id, curve_id = reference
        if kind == "series":
            self.describe_series(object_id)
        elif kind == "spectrum":
            self.describe_spectrum(object_id)
        elif kind == "function":
            self.describe_function(curve_id, object_id)

    def describe_series(self, series_id: str) -> None:
        series = next((item for item in self.project.dataset.series if item.id == series_id), None)
        if series is not None:
            self._edit_description("series", series_id, series.name)

    def describe_spectrum(self, curve_id: str) -> None:
        curve = self.project.dataset.curve(curve_id)
        series = self.project.dataset.series_for(curve_id)
        self._edit_description("spectrum", curve_id, f"{series.name} / {curve.name}")

    def describe_function(self, curve_id: str, component_id: str) -> None:
        model = self.project.models.get(curve_id)
        component = next((item for item in model.components if item.id == component_id), None) if model else None
        if component is not None:
            curve = self.project.dataset.curve(curve_id)
            series = self.project.dataset.series_for(curve_id)
            self._edit_description("function", component_id,
                                   f"{series.name} / {curve.name} / {component.name} ({component.function_id})", curve_id)

    def _edit_description(self, kind: str, object_id: str, title: str, curve_id: str = "") -> None:
        from curvemole.core.notebook import description_key
        from curvemole.gui.notebook import DescriptionDialog

        if not self._ensure_editable():
            return
        if self.task_running:
            self._notify(self.tr("Wait for the current task to finish before editing descriptions."))
            return
        entry = self.project.notebook.descriptions.get(description_key(kind, object_id, curve_id))
        with transient_widget(DescriptionDialog(title, entry.text if entry else "", self)) as dialog:
            if dialog.exec() == dialog.DialogCode.Accepted:
                self.project.notebook.set_description(self.project, kind, object_id, dialog.editor.toPlainText(), curve_id)
                self.refresh_all()

    def export_analysis(self) -> None:
        if self.task_running:
            self._notify(self.tr("Wait for the current task to finish before exporting."), warning=True)
            return
        self.plot_workspace.point_editor.finish()
        from curvemole.gui.current_view_export import capture_plot_snapshot
        snapshot = capture_plot_snapshot(self.plot_workspace) if self.project.curves else None
        remembered = self.project.export_config.get("directory")
        with transient_widget(ExportBundleDialog(remembered, self, project_name=self.project.name)) as dialog:
            if dialog.exec() != dialog.DialogCode.Accepted:
                return
            overwrite = dialog.overwrite.isChecked()
            if overwrite:
                answer = QMessageBox.question(
                    self,
                    self.tr("Confirm export update"),
                    self.tr(
                        "CurveMole will overwrite only files previously recorded as belonging "
                        "to this project export. Unrelated files will be preserved. Continue?"
                    ),
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            try:
                result = self._last_fit_result()
                summary = export_bundle(
                    self.project,
                    dialog.destination(),
                    result=result,
                    current_view=snapshot,
                    versioned=dialog.versioned.isChecked(),
                    overwrite=overwrite,
                    include_uncertainty_samples=dialog.full_samples.isChecked(),
                    selection=dialog.selection(),
                )
                self.project.touch()
                self._notify(
                    self.tr("Export complete: ")
                    + f"{len(summary.created)} {self.tr('created')}, {len(summary.updated)} {self.tr('updated')}."
                )
            except Exception as exc:
                self._show_error(self.tr("Export analysis"), exc)

    def export_current_view(self) -> None:
        from curvemole.core.figure_export import export_plot_snapshot
        from curvemole.gui.current_view_export import capture_plot_snapshot

        self.plot_workspace.point_editor.finish()
        snapshot = capture_plot_snapshot(self.plot_workspace) if self.project.curves else None
        if snapshot is None or not snapshot.traces:
            self._notify(self.tr("There are no visible curves to export."), warning=True)
            return
        suggested = (self.project.path.parent if self.project.path else Path.cwd()) / "current_view.svg"
        selected, selected_filter = QFileDialog.getSaveFileName(
            self, self.tr("Quick export: current view with Matplotlib"), str(suggested),
            self.tr("SVG figure (*.svg);;PDF figure (*.pdf);;PNG image (*.png)"),
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.suffix.lower() not in {".svg", ".pdf", ".png"}:
            suffix = ".pdf" if "*.pdf" in selected_filter else (".png" if "*.png" in selected_filter else ".svg")
            destination = destination.with_suffix(suffix)
        try:
            export_plot_snapshot(snapshot, destination)
            self._notify(self.tr("Current view exported: ") + str(destination))
        except Exception as exc:
            self._show_error(self.tr("Export current view"), exc)

    def export_parameters(self) -> None:
        if not self.project.curves:
            self._notify(self.tr("There are no spectra to export."), warning=True)
            return
        suggested = (self.project.path.parent if self.project.path else Path.cwd()) / f"{self.project.name}-functions-parameters.csv"
        from PySide6.QtWidgets import QCheckBox, QGridLayout

        with transient_widget(QFileDialog(self, self.tr("Export function parameters"), str(suggested),
                             self.tr("CSV files (*.csv)"))) as dialog:
            dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
            dialog.setDefaultSuffix("csv")
            dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
            covariance = QCheckBox(self.tr("Also export covariance matrices"), dialog)
            covariance.setObjectName("export_covariance")
            covariance.setToolTip(self.tr(
                "Write fit covariance and, when available, a separate sample covariance "
                "for the selected bootstrap or Monte Carlo analysis."))
            layout = dialog.layout()
            if isinstance(layout, QGridLayout):
                layout.addWidget(covariance, layout.rowCount(), 0, 1, layout.columnCount())
            if dialog.exec() != dialog.DialogCode.Accepted:
                return
            selected = dialog.selectedFiles()[0]
            try:
                destination = export_function_parameters(
                    self.project, selected, include_covariance=covariance.isChecked())
                self._notify(self.tr("Functions parameters exported: ") + str(destination))
            except Exception as exc:
                self._show_error(self.tr("Export function parameters"), exc)

    def edit_component_points(self, component_id: str | None = None) -> None:
        from curvemole.gui.edit_function_points import FunctionPointEditor
        if not hasattr(self, "_function_point_editor"):
            self._function_point_editor = FunctionPointEditor(self)
        try:
            self._function_point_editor.start(component_id or self.selected_component_id)
        except Exception as exc:
            self._show_error(self.tr("Edit function points"), exc)

    def add_component(self) -> None:
        if not self._ensure_editable():
            return
        if not self.active_curve_id:
            self._notify(self.tr("Activate a curve first."), warning=True)
            return
        curve = self.project.dataset.curve(self.active_curve_id)
        self.plot_workspace.cancel_placement()
        with transient_widget(AddComponentDialog(self.registry, curve, self)) as dialog:
            if dialog.exec() != dialog.DialogCode.Accepted:
                return
            try:
                component = dialog.component()
                definition = self.registry.get(component.function_id)
                if definition.kind == "peak":
                    self.last_peak_function_id = component.function_id
                    self.settings.setValue("last_peak_function", component.function_id)
                    self._pending_component = component
                    self._pending_component_curve_id = self.active_curve_id
                    self.plot_workspace.begin_peak_placement(definition.display_name)
                    self._notify(
                        self.tr("Click the peak centre and drag horizontally to set its initial FWHM.")
                    )
                    return
                if component.function_id == "cubic_spline":
                    self._pending_component = component
                    self._pending_component_curve_id = self.active_curve_id
                    self.plot_workspace.begin_spline_placement(definition.display_name)
                    self._notify(
                        self.tr(
                            "Click background points anywhere on the graph, including masked regions; "
                            "finish after at least two points. Spline nodes are locked by default."
                        )
                    )
                    return
                self._commit_component(component, self.active_curve_id)
            except Exception as exc:
                self._show_error(self.tr("Add component"), exc)

    def _graphical_peak_placed(self, centre: float, _: float, fwhm: float) -> None:
        component = self._pending_component
        curve_id = self._pending_component_curve_id
        self._pending_component = None
        self._pending_component_curve_id = None
        if component is None or curve_id is None:
            return
        try:
            curve = self.project.dataset.curve(curve_id)
            from curvemole.gui.function_composition import insertion_signal, normalize_kernel
            residual = insertion_signal(self, curve, component.operator)
            finite = np.isfinite(curve.x) & np.isfinite(curve.y) & np.isfinite(residual) & ~curve.effective_mask
            if not np.any(finite):
                raise ValueError(self.tr("The active curve has no usable points."))
            indices = np.flatnonzero(finite)
            point_index = int(indices[np.argmin(np.abs(curve.x[finite] - centre))])
            residual_offset = float(np.nanmedian(residual[finite])) if component.operator in {"add", "subtract"} else 0.0
            height = float(residual[point_index] - residual_offset)
            scale = float(np.ptp(curve.y[finite]))
            minimum_height = max(scale * 0.02, np.finfo(float).eps)
            if not math.isfinite(height) or abs(height) <= np.finfo(float).eps:
                height = minimum_height
            width = max(float(fwhm), np.finfo(float).eps)
            suggestion = PeakSuggestion(
                x=float(centre),
                height=height,
                fwhm=width,
                prominence=height,
                sign=1 if height >= 0 else -1,
            )
            initialise_peak_component(component, suggestion, registry=self.registry)
            normalize_kernel(component)
            self._commit_component(component, curve_id)
        except Exception as exc:
            self._show_error(self.tr("Place peak"), exc)

    def _graphical_spline_placed(self, points: object) -> None:
        selected = [(float(x), float(y)) for x, y in list(points)]
        component = self._pending_component
        curve_id = self._pending_component_curve_id
        self._pending_component = None
        self._pending_component_curve_id = None
        if component is None or curve_id is None:
            return
        try:
            initialise_spline_component(component, selected, registry=self.registry)
            self._commit_component(component, curve_id)
        except Exception as exc:
            self._show_error(self.tr("Place spline background"), exc)

    def _graphical_placement_cancelled(self) -> None:
        if self._pending_component is not None:
            self._notify(self.tr("Component placement cancelled."), warning=True)
        self._pending_component = None
        self._pending_component_curve_id = None

    def _component_base_name(self, component: Component) -> str:
        definition = self.registry.get(component.function_id)
        base = re.sub(r"[\W_]+", "", definition.display_name, flags=re.UNICODE)
        return base or "Function"

    def _assign_component_name(
        self,
        component: Component,
        model: Model,
        *,
        exclude_component_id: str | None = None,
    ) -> None:
        if component.metadata.get("custom_name"):
            return
        base = self._component_base_name(component)
        pattern = re.compile(rf"^{re.escape(base)}(\d+)$")
        used: list[int] = []
        for existing in model.components:
            if existing.id == exclude_component_id or existing.function_id != component.function_id:
                continue
            match = pattern.fullmatch(existing.name)
            if match:
                used.append(int(match.group(1)))
        component.name = f"{base}{max(used, default=0) + 1}"

    def _normalise_component_names(self) -> None:
        from curvemole.core.background_status import restore_background_history
        restore_background_history(self.project, self.registry)
        for model in self.project.models.values():
            used: dict[str, set[int]] = {}
            pending: list[Component] = []
            for component in model.components:
                if component.metadata.get("custom_name"):
                    continue
                base = self._component_base_name(component)
                match = re.fullmatch(rf"{re.escape(base)}(\d+)", component.name)
                number = int(match.group(1)) if match else 0
                numbers = used.setdefault(component.function_id, set())
                if number > 0 and number not in numbers:
                    numbers.add(number)
                else:
                    pending.append(component)
            for component in pending:
                numbers = used.setdefault(component.function_id, set())
                number = max(numbers, default=0) + 1
                numbers.add(number)
                component.name = f"{self._component_base_name(component)}{number}"

    def default_series_palette(self) -> str:
        name = str(self.settings.value(_DEFAULT_PALETTE_SETTING, DEFAULT_SERIES_PALETTE))
        return name if name in SERIES_PALETTES else DEFAULT_SERIES_PALETTE

    def _automatic_palette(self, name: str) -> tuple[str, ...]:
        appearance = normalize_plot_appearance(self.project.ui_state.get("plot_appearance"))
        return series_palette_colours(name, str(appearance["model_sum_colour"]))

    def _palette_for_appending(self, series: Series) -> tuple[str, ...]:
        palette = self._automatic_palette(str(series.metadata.get("palette", ""))) or self._automatic_palette(
            self.default_series_palette(),
        )
        counts = Counter(curve.colour.upper() for curve in series.curves)
        # Fill unused colours first, even if existing spectra were recoloured or moved.
        return tuple(sorted(palette, key=counts.__getitem__))

    def _normalise_spectrum_colours(self) -> None:
        changed = False
        fallback = self._automatic_palette(self.default_series_palette())
        for series in self.project.dataset.series:
            palette = self._automatic_palette(str(series.metadata.get("palette", ""))) or fallback
            for index, curve in enumerate(series.curves):
                if spectrum_colour_allowed(curve.colour, model_sum_colour=None):
                    continue
                curve.colour = palette[index % len(palette)]
                changed = True
        if changed and not self.project.read_only:
            self.project.touch()

    def _commit_component(self, component: Component, curve_id: str) -> None:
        model = self.project.model_for(curve_id)
        before = model.to_dict()
        self._assign_component_name(component, model)
        model.add(component)
        after = model.to_dict()
        restore_model_state(self.project, curve_id, before)
        self.selected_component_id = component.id
        self._push_model_state(curve_id, before, after, self.tr("Add component"))

    def move_function_row(
        self, curve_id: str, sources: str | tuple[tuple[str, str], ...], target_id: str, after: bool,
    ) -> None:
        if self.task_running:
            return
        model = self.project.models.get(curve_id)
        if model is None:
            return
        current = [component.id for component in model.display_components]
        if target_id not in current:
            return
        gap = current.index(target_id) + int(after)
        refs = ((curve_id, sources),) if isinstance(sources, str) else sources
        selected: dict[str, set[str]] = {}
        for owner, function_id in refs:
            selected.setdefault(owner, set()).add(function_id)
        before, after_orders = {}, {}
        for owner, component_ids in selected.items():
            group_model = self.project.models.get(owner)
            if group_model is None:
                return
            order = [component.id for component in group_model.display_components]
            if not component_ids.issubset(order):
                return
            moved = [identity for identity in order if identity in component_ids]
            new_order = row_block_order(order, moved, min(gap, len(order)))
            if new_order != order:
                before[owner] = list(group_model.display_order)
                after_orders[owner] = new_order
        if not after_orders:
            return

        def restore(orders: dict[str, list[str]]) -> None:
            for owner, order in orders.items():
                self.project.model_for(owner).display_order = list(order)

        self._push_change(
            self.tr("Reorder functions"),
            lambda: restore(after_orders),
            lambda: restore(before),
            modified_curve_ids=set(),
        )

    def _can_fix_parameter(self, curve_id: str, component_id: str, name: str) -> bool:
        component = self.project.model_for(curve_id).component(component_id)
        parameter = component.parameters[name]
        if not parameter.link or parameter.link_relation != "equal":
            return True
        self._show_error(self.tr("Cannot fix linked parameter"), ValueError(self.tr(
            "{parameter} is controlled by an equality link and cannot be fixed to a value. "
            "Remove the link in the Link column first, then set the value and select Fixed."
        ).format(parameter=f"{component.name}.{name}")))
        self.model_panel.refresh_parameters()
        return False

    def _change_parameter_for_curve(self, curve_id, component_id, name, field, value) -> None:
        """One validation and undo path for single and multi-spectrum editors."""
        if field == "fixed" and value and not self._can_fix_parameter(curve_id, component_id, name):
            return
        parameter = self.project.model_for(curve_id).component(component_id).parameters[name]
        old = getattr(parameter, field)
        try:
            setattr(parameter, field, value)
            parameter.validate()
            self._validate_all_links()
            setattr(parameter, field, old)
        except Exception as exc:
            setattr(parameter, field, old)
            self._show_error(self.tr("Parameter constraint"), exc)
            self.model_panel.refresh_parameters()
            return
        def assign(value):
            target = self.project.model_for(curve_id).component(component_id).parameters[name]
            setattr(target, field, value)
        self._push_change(
            self.tr("Edit parameter"),
            lambda: assign(value),
            lambda: assign(old),
            modified_curve_ids={curve_id},
        )

    def apply_parameter_link(self, curve_id: str, component_id: str, name: str,
                             link: str | None, scope: str, *,
                             reference_scopes: list[str] | None = None,
                             relation: str = "equal", tolerance: float = 0.0,
                             tolerance_mode: str = "absolute") -> None:
        """Apply the expression and its copy behavior as one validated undoable edit."""
        parameter = self.project.model_for(curve_id).component(component_id).parameters[name]
        if link and relation == "equal" and parameter.fixed:
            self._show_error(self.tr("Cannot link fixed parameter"), ValueError(self.tr(
                "This parameter is fixed. Clear Fixed before adding an equality link, "
                "which determines the value from another parameter."
            )))
            return
        before = (parameter.link, parameter.link_scope, list(parameter.link_reference_scopes),
                  parameter.link_relation, parameter.link_tolerance, parameter.link_tolerance_mode,
                  parameter.value)
        after = (link, scope if link else "relative", list(reference_scopes or []) if link else [],
                 relation if link else "equal", tolerance if link else 0.0,
                 tolerance_mode if link else "absolute", parameter.value)
        if before == after:
            return

        def assign(value):
            target = self.project.model_for(curve_id).component(component_id).parameters[name]
            (target.link, target.link_scope, scopes, target.link_relation,
             target.link_tolerance, target.link_tolerance_mode, target.value) = value
            target.link_reference_scopes = list(scopes)

        try:
            source_values = self.project.resolved_parameter_values() if link and relation != "equal" else {}
            assign(after)
            parameter.validate()
            if link and relation != "equal":
                from curvemole.core.expressions import SafeExpression

                source_path = SafeExpression.compile(link).references[0]
                lower, upper = parameter.link_bounds(source_values[source_path])
                after = (*after[:-1], min(max(parameter.value, lower), upper))
                assign(after)
            self._validate_all_links()
        except Exception as exc:
            assign(before)
            self._show_error(self.tr("Parameter constraint"), exc)
            return
        assign(before)
        self._push_change(self.tr("Set parameter link"), lambda: assign(after), lambda: assign(before),
                          modified_curve_ids={curve_id})

    def edit_calculation_order(self, curve_id: str) -> None:
        if not self._ensure_editable():
            return
        from curvemole.gui.component_composition import CalculationOrderDialog

        model = self.project.model_for(curve_id)
        with transient_widget(CalculationOrderDialog(model, self.project.dataset.curve(curve_id).name, self)) as dialog:
            if dialog.exec() != dialog.DialogCode.Accepted:
                return
            order = dialog.choices()
            before = copy.deepcopy(model.to_dict())
            candidate = model.clone()
            candidate.operation_order = order
            try:
                candidate.validate_composition()
            except Exception as exc:
                self._show_error(self.tr("Calculation order"), exc)
                return
            after = candidate.to_dict()
            if before != after:
                self._push_change(
                    self.tr("Change calculation order"),
                    lambda: restore_model_state(self.project, curve_id, after),
                    lambda: restore_model_state(self.project, curve_id, before),
                    modified_curve_ids={curve_id},
                )

    def set_component_operator(self, curve_id: str, component_id: str, operator: str) -> None:
        if not self._ensure_editable():
            return
        model = self.project.model_for(curve_id)
        component = model.component(component_id)
        if component.operator == operator:
            return
        before = copy.deepcopy(model.to_dict())
        try:
            model.set_component_operator(component_id, operator)
            after = copy.deepcopy(model.to_dict())
        except Exception as exc:
            self._show_error(self.tr("Change function composition"), exc)
            return
        restore_model_state(self.project, curve_id, before)
        self._push_change(
            self.tr("Change function composition"),
            lambda: restore_model_state(self.project, curve_id, after),
            lambda: restore_model_state(self.project, curve_id, before),
            modified_curve_ids={curve_id},
        )

    def copy_fit(self, *, next_only: bool = False) -> None:
        if not self._ensure_editable():
            return
        if not self.active_curve_id:
            return
        next_id = None
        if next_only:
            series = self.project.dataset.series_for(self.active_curve_id)
            ids = [curve.id for curve in series.curves]
            index = ids.index(self.active_curve_id)
            if index + 1 >= len(ids):
                self._notify(self.tr("There is no next spectrum in this series."))
                return
            next_id = ids[index + 1]
        with transient_widget(CopyFitDialog(self.project, self.active_curve_id, self, next_curve_id=next_id)) as dialog:
            if dialog.exec() != dialog.DialogCode.Accepted:
                return
            targets, choices = dialog.choices()
            if not targets:
                return

            def capture():
                return {curve_id: {
                    "model": copy.deepcopy(self.project.model_for(curve_id).to_dict()),
                    "masks": copy.deepcopy(self.project.dataset.curve(curve_id).masks),
                    "active_mask": self.project.dataset.curve(curve_id).active_mask,
                    "fit_ranges": list(self.project.dataset.curve(curve_id).fit_ranges),
                } for curve_id in targets}

            def restore(states):
                for curve_id, state in states.items():
                    restore_model_state(self.project, curve_id, state["model"])
                    curve = self.project.dataset.curve(curve_id)
                    curve.masks = copy.deepcopy(state["masks"])
                    curve.active_mask = state["active_mask"]
                    curve.fit_ranges = list(state["fit_ranges"])

            before = capture()
            try:
                self.project.copy_fit(self.active_curve_id, targets, **choices)
                self._validate_all_links()
            except Exception as exc:
                restore(before)
                self._show_error(self.tr("Copy fit"), exc)
                return
            after = capture()
            restore(before)

            self._push_change(
                self.tr("Copy fit"),
                lambda: restore(after),
                lambda: restore(before),
                modified_curve_ids=set(targets),
                preserve_curve_ids={self.active_curve_id},
            )
            if next_id in targets:
                self._set_active_curve(next_id)

    def start_fit(self) -> None:
        return self.fit_controller.start_fit()

    def _quick_fit_core(self) -> None:
        return self.fit_controller._quick_fit_core()

    def quick_fit(self) -> None:
        self.fit_controller.quick_fit(self._quick_fit_core)

    def _run_fit(self, plan: FitPlan) -> None:
        return self.fit_controller._run_fit(plan)

    def _partial_fit_result(self, item: tuple[str, FitResult]) -> None:
        return self.fit_controller._partial_fit_result(item)

    def _apply_fit_result_to_project(self, result: FitResult) -> None:
        # Fitting runs in a worker thread. Commit the returned estimates explicitly
        # to the GUI-side project so the redraw never depends on worker-side mutation.
        return self.fit_controller._apply_fit_result_to_project(result)

    def _successful_fit_curve_ids(self, result: FitResult) -> set[str]:
        return self.fit_controller._successful_fit_curve_ids(result)

    def _fit_finished_core(self, result: FitResult) -> None:
        return self.fit_controller._fit_finished_core(result)

    def _fit_finished(self, result: FitResult) -> None:
        self.fit_controller.fit_finished(result, self._fit_finished_core)

    def show_sequential_pause_reason(self) -> None:
        return self.fit_controller.show_sequential_pause_reason()

    def resume_sequence(self) -> None:
        """Continue a paused sequential fit from the (corrected) current spectrum."""
        self.fit_controller.resume_sequence()

    def terminate_sequence(self) -> None:
        """Discard a paused sequence, keeping every existing fit and model edit."""
        self.fit_controller.terminate_sequence()

    def _set_sequential_resume_available(self, available: bool) -> None:
        self.fit_controller.set_resume_available(available)

    def cancel_task(self) -> None:
        if self.task_runner.cancel():
            self._notify(self.tr("Cancellation requested…"), warning=True)

    def rename_function(self, curve_id: str, component_id: str) -> None:
        if self.task_running or not self._ensure_editable():
            return
        from PySide6.QtWidgets import QInputDialog
        component = self.project.model_for(curve_id).component(component_id)
        name, accepted = QInputDialog.getText(self, self.tr("Rename function"),
                                             self.tr("Function name"), text=component.name)
        if not accepted or not name.strip() or name.strip() == component.name:
            return
        old, new = component.name, name.strip()
        old_custom = component.metadata.get("custom_name", False)
        def assign(value, custom):
            target = self.project.model_for(curve_id).component(component_id)
            target.name = value
            if custom:
                target.metadata["custom_name"] = True
            else:
                target.metadata.pop("custom_name", None)
        self._push_change(self.tr("Rename function"), lambda: assign(new, True), lambda: assign(old, old_custom),
                          modified_curve_ids=set())

    def edit_reorder_rules(self) -> None:
        if not self.active_curve_id or self.task_running:
            return
        from curvemole.gui.reorder import ReorderRulesDialog, load_reorder_rules

        with transient_widget(ReorderRulesDialog(
            self.project.model_for(self.active_curve_id), self.registry,
            load_reorder_rules(self.settings), self,
        )) as dialog:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                rules = load_reorder_rules(self.settings)
                rules.update(dialog.rules())
                self.settings.setValue("model/reorder_rules", json.dumps(rules))

    def reorder_functions(self) -> None:
        if self.task_running or not self.active_curve_id or not self._ensure_editable():
            return
        from curvemole.core.reorder import reorder_component_names
        from curvemole.gui.reorder import load_reorder_rules

        curve_id = self.active_curve_id
        model = self.project.model_for(curve_id)

        def snapshot():
            current = self.project.model_for(curve_id)
            return ({item.id: item.name for item in current.components}, list(current.display_order))

        def restore(state):
            names, order = state
            current = self.project.model_for(curve_id)
            for component in current.components:
                component.name = names[component.id]
            current.display_order = list(order)

        before = snapshot()
        reorder_component_names(model, self.registry, load_reorder_rules(self.settings))
        after = snapshot()
        if before == after:
            self._notify(self.tr("Functions and names are already in order."))
            return
        restore(before)
        self._push_change(
            self.tr("Reorder functions"),
            lambda: restore(after),
            lambda: restore(before),
            modified_curve_ids=set(),
        )
        self._notify(self.tr("Functions reordered and automatic names renumbered."))

    def _recover_missing_fit_records(self) -> None:
        return self.fit_controller._recover_missing_fit_records()

    def _fit_for_uncertainty(self, curve_id: str) -> tuple[FitResult, FitPlan] | None:
        return self.uncertainty_controller._fit_for_uncertainty(curve_id)

    def _choose_background_uncertainty(self, curves: list[Curve]) -> str | None:
        return self.uncertainty_controller._choose_background_uncertainty(curves)

    def start_uncertainty(self, method: str, replicates: int, option: Any,
                          scope: str = "active", workers: int = 1,
                          adaptive: AdaptiveReplicateSettings | None = None,
                          replica_timeout_seconds: float = 60.0) -> None:
        return self.uncertainty_controller.start_uncertainty(method, replicates, option, scope, workers, adaptive, replica_timeout_seconds)

    def _partial_uncertainty_result(self, completed: list[tuple[str, FitResult, Any]]) -> None:
        return self.uncertainty_controller._partial_uncertainty_result(completed)

    def _uncertainty_finished(self, result: Any) -> None:
        return self.uncertainty_controller._uncertainty_finished(result)

    def delete_uncertainty_analysis(self, method: str) -> None:
        return self.uncertainty_controller.delete_uncertainty_analysis(method)

    def _store_uncertainty_result(self, curve_id: str, baseline: FitResult, result: Any) -> None:
        return self.uncertainty_controller._store_uncertainty_result(curve_id, baseline, result)

    def _select_uncertainty_display(self, method: str) -> None:
        return self.uncertainty_controller._select_uncertainty_display(method)

    def _show_uncertainty_analysis(self) -> None:
        return self.uncertainty_controller._show_uncertainty_analysis()

    def mask_point(self, x_value: float, *, unmask: bool = False) -> None:
        x_offset, _ = self.plot_workspace._active_display_offsets()
        x_value -= x_offset
        self._apply_mask(
            lambda curve, transfer: _unmask_transfer_point(
                curve, x_value, self._mask_tolerance() if transfer else math.inf
            )
            if unmask
            else curve.mask_point(x_value)
            if not transfer
            else _mask_transfer_point(curve, x_value, self._mask_tolerance())
        )

    def mask_range(self, lower: float, upper: float, *, unmask: bool = False) -> None:
        x_offset, _ = self.plot_workspace._active_display_offsets()
        lower, upper = lower - x_offset, upper - x_offset

        def operation(curve: Curve, transfer: bool) -> int:
            return (
                curve.unmask_interval(lower, upper)
                if unmask
                else curve.mask_interval(lower, upper)
            )

        self._apply_mask(operation)

    def _apply_mask(self, operation: Callable[[Curve, bool], Any]) -> None:
        if not self._ensure_editable():
            return
        targets = self._mask_targets()
        if not targets:
            return
        before = {
            curve.id: {name: (mask.excluded.copy(), list(mask.ranges)) for name, mask in curve.masks.items()}
            for curve in targets
        }
        for curve in targets:
            operation(curve, curve.id != self.active_curve_id)
        after = {
            curve.id: {name: (mask.excluded.copy(), list(mask.ranges)) for name, mask in curve.masks.items()}
            for curve in targets
        }

        def restore(snapshot: dict[str, Any]) -> None:
            for curve_id, masks in snapshot.items():
                curve = self.project.dataset.curve(curve_id)
                for name, (excluded, ranges) in masks.items():
                    curve.masks[name].excluded[:] = excluded
                    curve.masks[name].ranges = list(ranges)

        restore(before)
        self._push_change(self.tr("Edit mask"), lambda: restore(after), lambda: restore(before),
                          modified_curve_ids=set(after))

    def set_mask_tolerance(self) -> None:
        value, ok = QInputDialog.getDouble(
            self,
            self.tr("Mask transfer tolerance"),
            self.tr("Maximum |x_target − x_source| for point-mask transfer:"),
            self._mask_tolerance(),
            0,
            1e100,
            12,
        )
        if ok:
            self.project.ui_state["mask_transfer_tolerance"] = value
            self.project.touch()

    def drag_peak(self, component_id: str, centre: float, height: float, control: bool) -> None:
        if not self.active_curve_id:
            return
        component = self.project.model_for(self.active_curve_id).component(component_id)
        centre_parameter = component.parameters.get("center")
        area_parameter = component.parameters.get("area")
        if centre_parameter and centre_parameter.link and centre_parameter.link_relation == "equal":
            self._linked_notice(centre_parameter.link)
            return
        if area_parameter and area_parameter.link and area_parameter.link_relation == "equal":
            self._linked_notice(area_parameter.link)
            return
        changes: list[tuple[Any, float, float]] = []
        if centre_parameter:
            if centre_parameter.fixed and not control:
                self._fixed_notice()
            else:
                lower, upper = self._parameter_edit_bounds(centre_parameter)
                new_centre = min(max(centre, lower), upper)
                changes.append((centre_parameter, centre_parameter.value, new_centre))
        if area_parameter:
            if area_parameter.fixed and not control:
                self._fixed_notice()
            else:
                try:
                    new_area = area_for_height(component, height, registry=self.registry)
                    lower, upper = self._parameter_edit_bounds(area_parameter)
                    new_area = min(max(new_area, lower), upper)
                    changes.append((area_parameter, area_parameter.value, new_area))
                except Exception as exc:
                    self._show_error(self.tr("Peak drag"), exc)
                    return
        if not changes:
            self.refresh_all()
            return
        self._apply_parameter_drag_changes(changes, self.tr("Drag peak"))

    def drag_width(self, component_id: str, fwhm: float, control: bool) -> None:
        if not self.active_curve_id or fwhm <= 0:
            return
        component = self.project.model_for(self.active_curve_id).component(component_id)
        names_and_values: list[tuple[str, float]]
        if component.function_id == "gaussian":
            names_and_values = [("sigma", fwhm / 2.354820045)]
        elif component.function_id == "lorentzian":
            names_and_values = [("gamma", fwhm / 2)]
        elif component.function_id == "pseudo_voigt":
            names_and_values = [("fwhm", fwhm)]
        elif component.function_id == "voigt":
            definition = self.registry.get("voigt")
            values = {name: parameter.value for name, parameter in component.parameters.items()}
            current = definition.derived_values(values, component.metadata).get("FWHM") or fwhm
            ratio = fwhm / current
            names_and_values = [("sigma", values["sigma"] * ratio), ("gamma", values["gamma"] * ratio)]
        else:
            return
        changes = []
        for name, value in names_and_values:
            parameter = component.parameters[name]
            if parameter.link and parameter.link_relation == "equal":
                self._linked_notice(parameter.link)
                return
            if parameter.fixed and not control:
                self._fixed_notice()
                return
            lower, upper = self._parameter_edit_bounds(parameter)
            changes.append((parameter, parameter.value, min(max(value, lower), upper)))
        self._apply_parameter_drag_changes(changes, self.tr("Drag peak width"))

    def drag_spline_node(
        self, component_id: str, node: int, value: float, control: bool
    ) -> None:
        if not self.active_curve_id:
            return
        component = self.project.model_for(self.active_curve_id).component(component_id)
        parameter = component.parameters.get(f"y{node}")
        if parameter is None:
            return
        if parameter.link and parameter.link_relation == "equal":
            self._linked_notice(parameter.link)
            return
        if parameter.fixed and not control:
            self._fixed_notice()
            self.refresh_all()
            return
        lower, upper = self._parameter_edit_bounds(parameter)
        value = min(max(value, lower), upper)
        old = parameter.value
        self._apply_parameter_drag_changes([(parameter, old, value)], self.tr("Drag spline node"))

    def _parameter_edit_bounds(self, parameter) -> tuple[float, float]:
        if parameter.link and parameter.link_relation != "equal":
            from curvemole.core.expressions import SafeExpression

            source = SafeExpression.compile(parameter.link).references[0]
            return parameter.link_bounds(self.project.resolved_parameter_values()[source])
        return parameter.minimum, parameter.maximum

    def _apply_parameter_drag_changes(self, changes, text: str) -> None:
        """Validate the entire dependency graph before committing a graphical edit."""
        # A plugin or model Undo can reconstruct parameters between executions.
        # Keep stable paths in the command, rather than retaining old instances.
        paths = {id(parameter): path for path, parameter in self.project.parameter_map().items()}
        edits = [(paths[id(parameter)].split(".", 2), old, new)
                 for parameter, old, new in changes]

        def assign(position):
            for (curve_id, component_id, name), old, new in edits:
                parameter = self.project.model_for(curve_id).component(component_id).parameters[name]
                parameter.value = (old, new)[position]

        try:
            assign(1)
            self._validate_all_links()
        except Exception as exc:
            assign(0)
            self._show_error(self.tr("Parameter constraint"), exc)
            self.refresh_all()
            return
        assign(0)
        self._push_change(text, lambda: assign(1), lambda: assign(0),
                          modified_curve_ids={key[0] for key, _old, _new in edits})

    def _set_data_point_edit_mode(self, enabled: bool) -> None:
        editor = self.plot_workspace.point_editor
        if not enabled:
            editor.finish()
            return
        if self.task_running:
            self._notify(self.tr("Wait for the current calculation before editing data points."))
            self._data_point_edit_mode_changed(False)
            return
        if not self._ensure_editable():
            self._data_point_edit_mode_changed(False)
            return
        if not editor.begin():
            self._notify(self.tr("Show an active dataset in the graph before editing its points."))
            self._data_point_edit_mode_changed(False)

    def _data_point_edit_mode_changed(self, enabled: bool) -> None:
        self.edit_data_points_action.blockSignals(True)
        self.edit_data_points_action.setChecked(enabled)
        self.edit_data_points_action.blockSignals(False)

    def _move_data_point(self, curve_id: str, row: int, x: float, y: float) -> None:
        self._apply_data_point_edit(curve_id, row, (x, y))

    def _delete_data_point(self, curve_id: str, row: int) -> None:
        self._apply_data_point_edit(curve_id, row, None)

    def _apply_data_point_edit(self, curve_id: str, row: int, coordinates) -> None:
        if self.task_running or not self._ensure_editable():
            return
        if curve_id != self.active_curve_id or not self.plot_workspace.point_editor.active:
            return
        try:
            curve = self.project.dataset.curve(curve_id)
            matches = np.flatnonzero(curve.row_indices == row)
            if not len(matches):
                return
            index = int(matches[0])
            before = copy.deepcopy((curve.transformations, curve.redo_transformations, curve.state))
            # Replay into detached current arrays while sharing immutable source
            # columns; a single-point edit must not duplicate a dense input file.
            trial = copy.copy(curve)
            trial.transformations = list(curve.transformations)
            trial.redo_transformations = list(curve.redo_transformations)
            trial.masks = copy.deepcopy(curve.masks)
            if coordinates is None:
                trial.delete_points([index])
                title = self.tr("Delete data point")
            else:
                trial.move_points([index], x=[coordinates[0]], y=[coordinates[1]])
                title = self.tr("Move data point")
            after = copy.deepcopy((trial.transformations, trial.redo_transformations, trial.state))

            def restore(state):
                curve = self.project.dataset.curve(curve_id)
                curve.transformations, curve.redo_transformations, curve.state = copy.deepcopy(state)
                curve._recompute()

            self._push_change(title, lambda: restore(after), lambda: restore(before),
                              modified_curve_ids={curve_id}, preserve_curve_ids={curve_id})
        except Exception as exc:
            self._notify(self.tr("Edit data points: ") + str(exc), warning=True)

    def apply_calculator(self, request: dict[str, Any]) -> None:
        if not self._ensure_editable():
            return
        targets = self._calculator_targets(request.get("scope", 0))
        if not targets:
            return
        # Stage the whole batch first: an incompatible column in one spectrum
        # must not leave the others changed or discard their redo history.
        def snapshot(curve):
            return copy.deepcopy((curve.transformations, curve.redo_transformations, curve.state))

        before = {curve.id: snapshot(curve) for curve in targets}
        after = {}
        try:
            operation = request.get("operation", "")
            operand = (self.project.dataset.curve(request["operand_curve_id"])
                       if str(operation).startswith("curve_") else None)
            for original in targets:
                curve = copy.deepcopy(original)
                try:
                    if request.get("restore"):
                        curve.restore_original()
                    elif operand is not None:
                        apply_curve_operation(curve, operand, operation,
                                              interpolation=request["interpolation"],
                                              extrapolate=request["extrapolate"])
                    elif operation == "custom_formula":
                        apply_custom_formula(curve, request.get("formula_axis", "x"), request.get("formula", ""))
                    elif operation == "column_formula":
                        apply_column_formula(curve, request.get("column_target", "y"), request.get("formula", ""))
                    else:
                        apply_scalar(curve, operation, request.get("value"))
                except Exception as exc:
                    raise ValueError(f"{original.name}: {exc}") from exc
                after[curve.id] = snapshot(curve)

            def restore(values):
                for curve_id, state in values.items():
                    curve = self.project.dataset.curve(curve_id)
                    curve.transformations, curve.redo_transformations, curve.state = copy.deepcopy(state)
                    curve._recompute()

            self._push_change(self.tr("Restore original data") if request.get("restore") else self.tr("Data calculation"),
                              lambda: restore(after), lambda: restore(before),
                              modified_curve_ids=set(after), preserve_curve_ids=set(after))
        except Exception as exc:
            self._show_error(self.tr("Data Calculator"), exc)

    def save_custom_formula(self, formula: dict[str, Any]) -> None:
        """Persist a named equation both in the library and in this project."""
        if not self._ensure_editable():
            return
        try:
            from curvemole.core.calculator_equations import normalize_equation
            equation = normalize_equation(formula)
            # Write first, so a failed library save cannot appear successful.
            destination = self.calculator_equations.save(equation)
            self.project.custom_formulas = [item for item in self.project.custom_formulas
                                            if item.get("name") != equation["name"]]
            self.project.custom_formulas.append(equation)
            self.project.touch()
            self.refresh_all()
            self._notify(self.tr("Custom formula saved in the project and formula library:")
                         + f"\n{destination}")
        except Exception as exc:
            self._show_error(self.tr("Save custom formula"), exc)

    def apply_theme(self, theme: str) -> None:
        app = QApplication.instance()
        if not app:
            return
        if theme == "system":
            app.setPalette(app.style().standardPalette())
            app.setStyleSheet("")
        elif theme == "light":
            app.setPalette(app.style().standardPalette())
            app.setStyleSheet("QToolTip { color:#111; background:#fffbe6; border:1px solid #777; }")
        else:
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor(45, 48, 51))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(235, 238, 240))
            palette.setColor(QPalette.ColorRole.Base, QColor(28, 31, 34))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(40, 43, 46))
            palette.setColor(QPalette.ColorRole.Text, QColor(235, 238, 240))
            palette.setColor(QPalette.ColorRole.Button, QColor(55, 58, 62))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(235, 238, 240))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 114, 178))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
            app.setPalette(palette)
            app.setStyleSheet("QToolTip { color:#fff; background:#25282b; border:1px solid #777; }")
        self.settings.setValue("theme", theme)
        self.system_theme_action.setChecked(theme == "system")
        self.light_theme_action.setChecked(theme == "light")
        self.dark_theme_action.setChecked(theme == "dark")
        if hasattr(self, "curve_tree"):
            colour = QColor("#66B5FF" if app.palette().color(QPalette.ColorRole.Base).lightness() < 128 else "#075B9A")
            blocked = self.curve_tree.blockSignals(True)
            for index in range(self.curve_tree.topLevelItemCount()):
                self.curve_tree.topLevelItem(index).setForeground(1, colour)
            self.curve_tree.blockSignals(blocked)
        if hasattr(self, "model_panel"):
            self.model_panel.refresh()
        controller = getattr(self, "fit_controller", None)
        if controller is not None:
            controller.style()

    def reset_layout(self) -> None:
        self.dock_collapse.restore({})
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.series_dock)
        self.series_dock.show()
        from curvemole.gui.screen_fit import default_window_size
        self.resize(default_window_size(self, QSize(1440, 900)))
        for dock in self._tool_docks:
            if dock is not self.model_dock:
                dock.hide()
        self._apply_tabbed_tool_layout()

    def _automatic_update_check(self) -> None:
        self.check_for_updates(force=False)

    def check_for_updates(self, *, force: bool = False) -> None:
        self._release_update_controller.check(force=force)

    def _update_check_finished(self, reply: Any, force: bool) -> None:
        """Compatibility entry point for integrations using the previous checker."""
        self._release_update_controller._release_finished(reply, force)
        self._update_reply = None

    def open_documentation(self, name: str) -> None:
        from curvemole.gui.documentation import show_markdown_document

        source_tree = Path(__file__).resolve().parents[3] / "docs" / name
        if source_tree.exists():
            show_markdown_document(self, source_tree, self.tr("CurveMole help"))
            return
        packaged = _resource_path(f"docs/{name}")
        if packaged and packaged.exists():
            show_markdown_document(self, packaged, self.tr("CurveMole help"))
            return
        self._open_external("https://github.com/SebRoLENS/curvemole/tree/main/docs")

    def _open_external(self, target: str | Path) -> None:
        value = str(target)
        try:
            opened = open_with_host_application(value)
            if not opened:
                url = QUrl.fromLocalFile(value) if isinstance(target, Path) else QUrl(value)
                opened = QDesktopServices.openUrl(url)
            if opened:
                return
        except OSError as exc:
            self._log(f"External opener failed: {exc}")
        QMessageBox.warning(
            self,
            self.tr("Open link"),
            self.tr("CurveMole could not open this item automatically. Copy it into your browser or file manager:")
            + f"\n\n{value}",
        )

    def show_shortcuts(self) -> None:
        from curvemole.gui.shortcuts_dialog import ShortcutsDialog

        guide = Path(__file__).resolve().parents[3] / "docs" / "mouse-shortcuts.md"
        if not guide.is_file():
            guide = _resource_path("docs/mouse-shortcuts.md")
        try:
            mouse_text = guide.read_text(encoding="utf-8") if guide is not None else ""
        except OSError:
            mouse_text = ""
        if not mouse_text:
            mouse_text = self.tr("Mouse shortcut guide is unavailable. See the user manual.")
        with transient_widget(ShortcutsDialog(self, mouse_text)) as dialog:
            dialog.exec()

    def show_about(self) -> None:
        with transient_widget(AboutDialog(_resource_path("curvemole.png"), self)) as dialog:
            dialog.exec()

    def show_plugin_manager(self) -> None:
        if self.task_running:
            QMessageBox.information(self, "Plugin Manager", "Wait for the running task to finish.")
            return
        from curvemole.gui.data_directories import library_directory
        with transient_widget(PluginManagerDialog(self.plugin_manager,
                                     library_directory(self.settings, "plugins"), self)) as dialog:
            dialog.exec()
            self.settings.setValue("plugin_directory", dialog.directory.text().strip())
            if hasattr(self, "plugin_update_controller"):
                self.plugin_update_controller.check()
            self.plugin_host.refresh()
            self.refresh_all()

    def _set_active_series(self, series_id: str) -> None:
        series = next((item for item in self.project.dataset.series if item.id == series_id), None)
        if series is None:
            return
        self.plot_workspace._active_series_id = series_id
        ids = [curve.id for curve in series.curves]
        self.plot_workspace.cancel_placement()
        curve_id = self.active_curve_id if self.active_curve_id in ids else (ids[0] if ids else None)
        self.selected_component_id = self._component_for_curve_navigation(curve_id)
        self.active_curve_id = curve_id
        # Keep the series header selected, including its multi-curve selection.
        self._selection_changed()

    def _activate_tree_curve(self, curve_id: str | None) -> None:
        if curve_id != self.active_curve_id:
            self.plot_workspace.cancel_placement()
        self.selected_component_id = self._component_for_curve_navigation(curve_id)
        self.active_curve_id = curve_id
        self._selection_changed()
        self.refresh_worksheet()
        self._refresh_diagnostics()

    def _set_active_curve(self, curve_id: str | None) -> None:
        if curve_id != self.active_curve_id:
            self.plot_workspace.cancel_placement()
        self.selected_component_id = self._component_for_curve_navigation(curve_id)
        self.active_curve_id = curve_id
        self.refresh_all()

    def _component_for_curve_navigation(self, curve_id: str | None) -> str | None:
        panel = self.model_panel
        if curve_id is None or panel.show_all_functions.isChecked():
            return None
        components = self.project.model_for(curve_id).display_components
        if not components:
            return None
        source_id = panel.selected_component_curve_id()
        component_id = panel.selected_component_id()
        if source_id is None or component_id is None or panel.project is not self.project:
            return None
        source = self.project.models.get(source_id)
        if source is None:
            return None
        position = next(
            (index for index, component in enumerate(source.display_components) if component.id == component_id),
            None,
        )
        return components[min(position, len(components) - 1)].id if position is not None else None

    def _selection_changed(self) -> None:
        selected = self.curve_tree.selected_curve_ids()
        self.curve_tree.mark_active_spectrum(self.active_curve_id)
        self.model_panel.set_context(
            self.project,
            self.active_curve_id,
            len(selected),
            self.selected_component_id,
        )
        self.copy_fit_next_action.setEnabled(self.model_panel.copy_fit_next_button.isEnabled())
        self.plot_workspace.set_context(
            self.project,
            self.active_curve_id,
            selected,
            self.selected_component_id,
        )
        self.calculator.set_selection_context(self.project, self.active_curve_id, selected)
        if hasattr(self, "restore_original_controller"):
            self.restore_original_controller.sync()
        self.uncertainty_panel.set_parameters(self.project, self.active_curve_id)

    def remove_selected_curves(self) -> None:
        series_ids = self.curve_tree.selected_series_ids()
        if series_ids and all(
            item.parent() is None or item.parent().isSelected() for item in self.curve_tree.selectedItems()
        ):
            self.delete_selected_series(series_ids)
            return
        if not self._ensure_editable():
            return
        if self.task_running:
            self._notify(self.tr("Wait for the current task to finish before removing spectra."))
            return
        selected = self.curve_tree.selected_curve_ids()
        if not selected and self.active_curve_id:
            selected = {self.active_curve_id}
        if not selected:
            self._notify(self.tr("Select at least one curve to remove."), warning=True)
            return
        try:
            self.project.validate_curve_removal(selected)
        except ConstraintError as exc:
            self._show_error(self.tr("Remove curve"), exc)
            return
        count = len(selected)
        question = (
            self.tr("Remove the selected curve? This action can be undone.")
            if count == 1
            else self.tr("Remove the selected curves? This action can be undone.")
        )
        if QMessageBox.question(
            self, self.tr("Remove curve"), question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return

        records: list[tuple[str, str, int, Curve, dict[str, Any] | None]] = []
        for curve_id in [curve.id for curve in self.project.curves if curve.id in selected]:
            series = self.project.dataset.series_for(curve_id)
            curve = self.project.dataset.curve(curve_id)
            # Dataclass equality compares NumPy arrays for same-named spectra.
            # Resolve identity explicitly instead of list.index(curve).
            index = next(index for index, item in enumerate(series.curves) if item.id == curve_id)
            model = self.project.models.get(curve_id)
            model_state = model.to_dict() if model is not None else None
            records.append((curve_id, series.id, index, curve, model_state))
        active_before = self.active_curve_id
        saved_results = copy_result_maps(self.project.results)
        saved_states = {curve.id: curve.state for curve in self.project.curves}

        def redo() -> None:
            existing_ids = {curve.id for curve in self.project.curves}
            self.project.remove_curves([curve_id for curve_id, *_ in records if curve_id in existing_ids])
            if self.active_curve_id in selected:
                self.active_curve_id = self.project.curves[0].id if self.project.curves else None
            self.selected_component_id = None

        def undo() -> None:
            for curve_id, series_id, index, curve, model_state in sorted(
                records, key=lambda item: item[2]
            ):
                # Series layout Undo can recreate Series objects with the same ID.
                series = next(item for item in self.project.dataset.series if item.id == series_id)
                if all(existing.id != curve_id for existing in series.curves):
                    series.add(curve, index)
                if model_state is not None:
                    restore_model_state(self.project, curve_id, model_state)
            self.project.results = copy_result_maps(saved_results)
            for curve in self.project.curves:
                if curve.id in saved_states:
                    curve.state = saved_states[curve.id]
            self.active_curve_id = active_before if active_before else (self.project.curves[0].id if self.project.curves else None)
            self.selected_component_id = None

        self._push_change(
            self.tr("Remove curve") if count == 1 else self.tr("Remove curves"),
            redo,
            undo,
            modified_curve_ids=set(),
        )

    def _set_curve_colour(self, curve_id: str, colour: str) -> None:
        curve = self.project.dataset.curve(curve_id)
        curve.colour = colour.upper()
        self.project.touch()
        self._refresh_curve_colours()

    def _refresh_curve_colours(self) -> None:
        selected = self.curve_tree.populate(self.project, self.active_curve_id)
        self.plot_workspace.set_context(
            self.project, self.active_curve_id, selected, self.selected_component_id,
        )

    def choose_curve_colour(self, curve_id: str) -> None:
        if not self._ensure_editable(prepare_plot=False):
            return
        curve = self.project.dataset.curve(curve_id)
        model_sum_colour = str(self.plot_workspace.plot_appearance()["model_sum_colour"])
        while True:
            selected = QColorDialog.getColor(
                QColor(curve.colour),
                self,
                self.tr("Choose spectrum colour"),
            )
            if not selected.isValid():
                return
            colour = selected.name(QColor.NameFormat.HexRgb).upper()
            if spectrum_colour_allowed(colour, model_sum_colour):
                break
            QMessageBox.warning(
                self,
                self.tr("Colour too close to the fit"),
                self.tr("This colour is almost identical to the model-sum colour (%1). Choose a slightly different shade.")
                .replace("%1", model_sum_colour),
            )
        old = curve.colour.upper()
        if colour == old:
            return
        self.undo_service.push(
            self.tr("Change spectrum colour"),
            lambda: self._set_curve_colour(curve_id, colour),
            lambda: self._set_curve_colour(curve_id, old),
            refresh=False,
            check_editable=False,
        )

    def apply_selected_palette(self, curve_ids: list[str], palette_name: str) -> None:
        """Colour just the selected spectra in tree order, regardless of series."""
        if not self._ensure_editable():
            return
        palette = self._automatic_palette(palette_name)
        if not palette:
            return
        available = {curve.id: curve for curve in self.project.curves}
        ordered_ids = [
            curve_id for curve_id in dict.fromkeys(curve_ids) if curve_id in available
        ]
        if len(ordered_ids) < 2:
            return
        self.settings.setValue(_DEFAULT_PALETTE_SETTING, palette_name)
        before = {curve_id: available[curve_id].colour for curve_id in ordered_ids}
        after = {
            curve_id: palette[index % len(palette)]
            for index, curve_id in enumerate(ordered_ids)
        }
        if before == after:
            return

        def restore(colours: dict[str, str]) -> None:
            for curve_id, colour in colours.items():
                try:
                    self.project.dataset.curve(curve_id).colour = colour.upper()
                except KeyError:
                    continue
            # This operation changes individual colours, not any series palette.
            self.project.touch()
            self._refresh_curve_colours()

        self.undo_service.push(
            self.tr("Change selected spectra palette"),
            lambda: restore(after),
            lambda: restore(before),
            refresh=False,
            check_editable=False,
        )

    def apply_series_palette(self, series_id: str, palette_name: str) -> None:
        if not self._ensure_editable():
            return
        palette = self._automatic_palette(palette_name)
        if not palette:
            return
        series = next((item for item in self.project.dataset.series if item.id == series_id), None)
        if series is None:
            return
        self.settings.setValue(_DEFAULT_PALETTE_SETTING, palette_name)
        before_colours = [curve.colour for curve in series.curves]
        before_palette = series.metadata.get("palette")
        after_colours = [palette[index % len(palette)] for index in range(len(series.curves))]

        def restore(colours: list[str], marker: Any) -> None:
            series = next(item for item in self.project.dataset.series if item.id == series_id)
            for curve, colour in zip(series.curves, colours, strict=True):
                curve.colour = colour.upper()
            if marker is None:
                series.metadata.pop("palette", None)
            else:
                series.metadata["palette"] = marker
            self.project.touch()
            self._refresh_curve_colours()

        self.undo_service.push(
            self.tr("Change series palette"),
            lambda: restore(after_colours, palette_name),
            lambda: restore(before_colours, before_palette),
            refresh=False,
            check_editable=False,
        )

    def _series_layout_snapshot(self) -> list[tuple[Series, str, dict[str, Any], list[str]]]:
        return [
            (
                series,
                series.name,
                copy.deepcopy(series.metadata),
                [curve.id for curve in series.curves],
            )
            for series in self.project.dataset.series
        ]

    def _restore_series_layout(
        self, snapshot: list[tuple[Series, str, dict[str, Any], list[str]]], *, refresh: bool = True,
    ) -> None:
        # Keep the original Series objects alive across Undo/Redo. This matters for
        # GUI and external references, and also allows a merged-away series to be
        # restored as the very same object rather than a replacement with the same id.
        curve_map = {curve.id: curve for curve in self.project.curves}
        restored: list[Series] = []
        for series, name, metadata, curve_ids in snapshot:
            series.name = name
            series.metadata = copy.deepcopy(metadata)
            series.curves = [curve_map[curve_id] for curve_id in curve_ids]
            restored.append(series)
        self.project.dataset.series = restored
        if refresh:
            self.project.touch()
            self.refresh_all()

    def _push_series_layout_change(self, text: str, operation: Callable[[], None]) -> None:
        if not self._ensure_editable():
            return
        before = self._series_layout_snapshot()
        operation()
        after = self._series_layout_snapshot()
        before_order = [(group.id, ids) for group, _, _, ids in before]
        after_order = [(group.id, ids) for group, _, _, ids in after]
        if before_order == after_order:
            return
        self._restore_series_layout(before, refresh=False)
        self.undo_service.push(
            text,
            lambda: self._restore_series_layout(after),
            lambda: self._restore_series_layout(before),
            refresh=False,
            check_editable=False,
        )

    def move_data_row(
        self, source: tuple[str, str] | tuple[tuple[str, str], ...], target: tuple[str, str], after: bool,
    ) -> None:
        if not source or self.task_running:
            return
        dataset = self.project.dataset
        sources = (source,) if isinstance(source[0], str) else source
        source_kind = sources[0][0]
        requested = {identity for kind, identity in sources if kind == source_kind}
        target_kind, target_id = target
        series_by_id = {group.id: group for group in dataset.series}
        if source_kind == "series":
            if target_kind != "series" or target_id not in series_by_id or not requested.issubset(series_by_id):
                return
            current = list(series_by_id)
            moved = [identity for identity in current if identity in requested]
            order = row_block_order(current, moved, current.index(target_id) + int(after))

            def reorder_series() -> None:
                dataset.series[:] = [series_by_id[identity] for identity in order]

            self._push_series_layout_change(self.tr("Reorder series"), reorder_series)
            return

        curve_locations = {curve.id: (group, curve) for group in dataset.series for curve in group.curves}
        if not requested or not requested.issubset(curve_locations):
            return
        if target_kind == "curve":
            if target_id not in curve_locations:
                return
            destination = curve_locations[target_id][0]
            current = [curve.id for curve in destination.curves]
            gap = current.index(target_id) + int(after)
        else:
            destination = series_by_id.get(target_id)
            if destination is None:
                return
            current = [curve.id for curve in destination.curves]
            gap = 0
        moved = [identity for identity in curve_locations if identity in requested]
        order = row_block_order(current, moved, gap)
        source_groups = {curve_locations[identity][0].id for identity in moved}

        def operation() -> None:
            for identity in source_groups - {destination.id}:
                group = series_by_id[identity]
                group.curves[:] = [curve for curve in group.curves if curve.id not in requested]
            destination.curves[:] = [curve_locations[identity][1] for identity in order]

        title = self.tr("Reorder spectra") if source_groups == {destination.id} else self.tr("Move spectra to series")
        self._push_series_layout_change(title, operation)

    def _next_series_name(self) -> str:
        number = len(self.project.dataset.series) + 1
        names = {series.name for series in self.project.dataset.series}
        while self.tr("Series ") + str(number) in names:
            number += 1
        return self.tr("Series ") + str(number)

    def create_series(self) -> None:
        if not self._ensure_editable():
            return
        default_name = self._next_series_name()
        name, accepted = QInputDialog.getText(
            self, self.tr("New series"), self.tr("Series name:"), text=default_name
        )
        if not accepted:
            return
        name = name.strip()
        if not name:
            self._notify(self.tr("Series name cannot be empty."), warning=True)
            return
        if any(series.name == name for series in self.project.dataset.series):
            self._notify(self.tr("A series with that name already exists."), warning=True)
            return

        def operation() -> None:
            self.project.dataset.add_series(
                Series(name, metadata={"palette": self.default_series_palette()})
            )

        self._push_series_layout_change(self.tr("Create series"), operation)

    def move_curves_to_series(
        self, curve_ids: object, target_series_id: str | None, *, new_series_name: str = "",
    ) -> None:
        if not self._ensure_editable():
            return
        if self.task_running:
            self._notify(self.tr("Wait for the current task to finish before moving data."))
            return
        dataset = self.project.dataset
        if target_series_id is None:
            name = new_series_name.strip()
            if not name or any(series.name == name for series in dataset.series):
                self._notify(self.tr("Enter a non-empty series name that is not already in use."), warning=True)
                return
            target = Series(name, metadata={"palette": self.default_series_palette()})
        else:
            target = next((series for series in dataset.series if series.id == target_series_id), None)
            if target is None:
                return
        requested = {str(value) for value in curve_ids}
        moved = [
            curve for series in dataset.series if series is not target
            for curve in series.curves if curve.id in requested
        ]
        if not moved:
            return

        def operation() -> None:
            if target_series_id is None:
                dataset.add_series(target)
            for series in dataset.series:
                if series is not target:
                    series.curves[:] = [curve for curve in series.curves if curve.id not in requested]
            target.curves.extend(moved)

        self._push_series_layout_change(self.tr("Move spectra to series"), operation)

    def merge_series(self, source_series_ids: str | tuple[str, ...], target_series_id: str) -> None:
        if self.task_running:
            return
        dataset = self.project.dataset
        selected = {source_series_ids} if isinstance(source_series_ids, str) else set(source_series_ids)
        selected.discard(target_series_id)
        by_id = {series.id: series for series in dataset.series}
        target = by_id.get(target_series_id)
        if target is None or not selected or not selected.issubset(by_id):
            return
        sources = [series for identity, series in by_id.items() if identity in selected]

        def operation() -> None:
            target.curves.extend(curve for series in sources for curve in series.curves)
            for series in sources:
                series.curves.clear()
            dataset.series[:] = [series for series in dataset.series if series.id not in selected]

        self._push_series_layout_change(self.tr("Merge series"), operation)

    def reorder_curves(self, curve_ids: object, delta: int) -> None:
        if not self._ensure_editable() or delta not in {-1, 1}:
            return
        selected = {str(value) for value in list(curve_ids)}
        if not selected:
            return
        parents = []
        for curve_id in selected:
            try:
                parents.append(self.project.dataset.series_for(curve_id).id)
            except KeyError:
                return
        if len(set(parents)) != 1:
            self._notify(
                self.tr("Spectra can be reordered together only when they belong to the same series."),
                warning=True,
            )
            return
        series = next(item for item in self.project.dataset.series if item.id == parents[0])

        def operation() -> None:
            curves = series.curves
            if delta < 0:
                for index in range(1, len(curves)):
                    if curves[index].id in selected and curves[index - 1].id not in selected:
                        curves[index - 1], curves[index] = curves[index], curves[index - 1]
            else:
                for index in range(len(curves) - 2, -1, -1):
                    if curves[index].id in selected and curves[index + 1].id not in selected:
                        curves[index], curves[index + 1] = curves[index + 1], curves[index]

        self._push_series_layout_change(self.tr("Reorder spectra"), operation)

    def _prompt_rename_series(self, series_id: str) -> None:
        if not self._ensure_editable():
            return
        series = next((item for item in self.project.dataset.series if item.id == series_id), None)
        if series is None:
            return
        name = series.name
        while True:
            name, accepted = QInputDialog.getText(
                self, self.tr("Rename series"), self.tr("Series name:"), text=name
            )
            if not accepted:
                return
            name = name.strip()
            if not name:
                QMessageBox.warning(self, self.tr("Rename series"), self.tr("Series name cannot be empty."))
                continue
            if any(item.id != series_id and item.name == name for item in self.project.dataset.series):
                QMessageBox.warning(self, self.tr("Rename series"), self.tr("A series with that name already exists."))
                continue
            self._rename_series(series_id, name)
            return

    def _rename_series(self, series_id: str, name: str) -> None:
        if not self._ensure_editable():
            self.refresh_all()
            return
        name = name.strip()
        series = next(
            (item for item in self.project.dataset.series if item.id == series_id), None
        )
        if series is None:
            return
        if not name or any(
            item.id != series_id and item.name == name for item in self.project.dataset.series
        ):
            self.refresh_all()
            return
        series.name = name
        self.project.touch()
        self.refresh_all()

    def _set_visibility(self, curve_id: str, visible: bool) -> None:
        curve = self.project.dataset.curve(curve_id)
        curve.visible = visible
        self.project.touch()
        self.plot_workspace.refresh()

    def _rename_curve(self, curve_id: str, name: str) -> None:
        name = name.strip()
        if not name:
            self.refresh_all()
            return
        self.project.dataset.curve(curve_id).name = name
        self.project.touch()
        self.refresh_all()

    def _set_component_on_curve(self, curve_id: str, component_id: str) -> None:
        model = self.project.models.get(curve_id)
        if model is None or not any(component.id == component_id for component in model.components):
            return
        if curve_id != self.active_curve_id:
            self._set_active_curve(curve_id)
        self.model_panel.select_component_ref(curve_id, component_id)
        self._set_component(component_id)

    def _model_mutation(self, text: str, operation: Callable[[Model], Any]) -> None:
        if not self.active_curve_id:
            return
        model = self.project.model_for(self.active_curve_id)
        before = model.to_dict()
        operation(model)
        after = model.to_dict()
        restore_model_state(self.project, self.active_curve_id, before)
        self._push_model_state(self.active_curve_id, before, after, text)

    def _push_model_state(
        self,
        curve_id: str,
        before: dict[str, Any],
        after: dict[str, Any],
        text: str,
    ) -> None:
        self.undo_service.push_model_edit(ModelEdit.single(curve_id, before, after), text)

    def _push_change(
        self,
        text: str,
        redo: Callable[[], None],
        undo: Callable[[], None],
        *,
        modified_curve_ids: set[str] | None = None,
        preserve_curve_ids: set[str] | None = None,
    ) -> None:
        self.undo_service.push(text, redo, undo, modified_curve_ids=modified_curve_ids,
                               preserve_curve_ids=preserve_curve_ids)

    def _after_edit(
        self,
        modified_curve_ids: set[str] | None = None,
        preserve_curve_ids: set[str] | None = None,
    ) -> None:
        try:
            self.project.touch()
        except PermissionError as exc:
            self._show_error(self.tr("Read-only project"), exc)
        if modified_curve_ids is None:
            modified_curve_ids = self.curve_tree.selected_curve_ids() or (
                {self.active_curve_id} if self.active_curve_id else set()
            )
        if modified_curve_ids:
            self.project.invalidate_fits(modified_curve_ids, preserve=preserve_curve_ids or ())
        self.refresh_all()

    def _validate_all_links(self) -> None:
        parameters = {
            path: parameter
            for curve_id, model in self.project.models.items()
            for path, parameter in model.parameter_map(curve_id).items()
        }
        resolve_parameter_values(parameters)

    def _run_background(
        self,
        operation: Callable[..., Any],
        finished: Callable[[Any], None],
        status: str,
        partial: Callable[[Any], None] | None = None,
    ) -> None:
        if self.task_running:
            self._notify(self.tr("Another task is already running."), warning=True)
            return
        self.plot_workspace.point_editor.finish()
        self.task_runner.start(operation, finished, partial)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_action.setEnabled(True)
        self.fit_action.setEnabled(False)
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
        self.uncertainty_panel.set_busy(True)
        self._notify(status)
        self.fit_controller.sync()

    def _poll_task(self) -> None:
        self.task_runner.poll()

    # Task state lives in the TaskRunner. These aliases keep the historical
    # attribute names working for extensions, plugins and tests; new code uses
    # ``task_running`` and ``task_runner``.
    @property
    def task_running(self) -> bool:
        """True while a fit or analysis task is running."""
        return self.task_runner.busy

    _thread = property(lambda self: self.task_runner.thread,
                       lambda self, value: setattr(self.task_runner, "thread", value))
    _worker = property(lambda self: self.task_runner.worker,
                       lambda self, value: setattr(self.task_runner, "worker", value))
    _task_callbacks = property(lambda self: self.task_runner.callbacks,
                               lambda self, value: setattr(self.task_runner, "callbacks", value))
    _cancellation = property(lambda self: self.task_runner.cancellation,
                             lambda self, value: setattr(self.task_runner, "cancellation", value))
    _cancel_requested_at = property(lambda self: self.task_runner.cancel_requested_at,
                                    lambda self, value: setattr(self.task_runner, "cancel_requested_at", value))
    _task_snapshot_safe = property(lambda self: self.task_runner.snapshot_safe,
                                   lambda self, value: setattr(self.task_runner, "snapshot_safe", value))
    _task_watchdog = property(lambda self: self.task_runner.watchdog)
    _TASK_CANCEL_GRACE_SECONDS = property(
        lambda self: self.task_runner.CANCEL_GRACE_SECONDS,
        lambda self, value: setattr(self.task_runner, "CANCEL_GRACE_SECONDS", value))

    def _task_progress(self, value: float | None, text: str) -> None:
        if value is None:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            # 100% of replicas is not yet a completed task: finalization and
            # result delivery must finish before the busy state is released.
            self.progress.setValue(min(99, int(max(0.0, min(value, 1.0)) * 100)))
        self.statusBar().showMessage(text)

    def _task_failed(self, message: str, details: str) -> None:
        self.fit_lifecycle.abort()
        self.plot_workspace._live_parameter_values = None
        self._log(details)
        task = getattr(self, "_uncertainty_task", None)
        timeout = message.startswith("Uncertainty replica timeout:")
        if task and (timeout or (task.get("background_treatment") and "cancelled" not in message.lower())):
            failures = self.project.results.setdefault("uncertainty_failures_by_curve", {})
            for curve_id in task["curve_ids"] - task["completed"]:
                failures.setdefault(curve_id, {})[task["method"]] = {
                    "message": message, "reason": "timeout" if timeout else "background_analysis",
                }
            self.project.touch()
        if "cancelled" in message.lower():
            self._notify(self.tr("Task cancelled; the previous valid result was retained."), warning=True)
        else:
            if getattr(self, "_fit_task_active", False):
                for curve_id in self._running_fit_plan.curve_ids:
                    self.project.dataset.curve(curve_id).state = CurveState.FAILED
                self.project.touch()
            self._show_error(self.tr("Task failed"), RuntimeError(message))
        self.refresh_all()

    def _task_done(self, *_: Any) -> None:
        try:
            self._reset_task_state()
            self.fit_lifecycle.done()
        finally:
            self.fit_controller.task_done()

    def _reset_task_state(self) -> None:
        """Idempotent busy-state cleanup, also used if a completion hook fails."""
        self.task_runner.reset()
        self.plot_workspace._live_parameter_values = None
        self._fit_task_active = False
        self._uncertainty_task = None
        self.progress.setVisible(False)
        self.cancel_action.setEnabled(False)
        self.fit_action.setEnabled(True)
        self.uncertainty_panel.set_busy(False)
        self.undo_action.setEnabled(self.undo_stack.canUndo())
        self.redo_action.setEnabled(self.undo_stack.canRedo())

    def _mask_targets(self) -> list[Curve]:
        if not self.active_curve_id:
            return []
        if self.plot_workspace.display_mode.currentIndex() == 0 or self.plot_workspace._mask_scope == "active":
            ids = {self.active_curve_id}
        else:
            ids = {curve.id for curve in self.plot_workspace.displayed_curves()}
        return [curve for curve in self.project.curves if curve.id in ids]

    def _calculator_targets(self, scope: int | str) -> list[Curve]:
        if scope == "selected":
            selected = self.curve_tree.selected_curve_ids()
            return [curve for curve in self.project.curves if curve.id in selected]
        if scope == 1 and self.project.curves:
            from curvemole.gui.series_groups import SpectrumSelectionDialog
            with transient_widget(SpectrumSelectionDialog(self.project, self.active_curve_id, self)) as dialog:
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return []
                return [self.project.dataset.curve(identifier) for identifier in dialog.selected_ids()]
        if not self.active_curve_id:
            return []
        if scope == 0:
            return [self.project.dataset.curve(self.active_curve_id)]
        if scope == 2:  # Retain the legacy programmatic whole-series scope.
            return list(self.project.dataset.series_for(self.active_curve_id).curves)
        return []

    def _mask_tolerance(self) -> float:
        return float(self.project.ui_state.get("mask_transfer_tolerance", 0.0))

    def _last_fit_result(self) -> FitResult | None:
        value = self.project.results.get("last_fit")
        return value if isinstance(value, FitResult) else None

    def _refresh_diagnostics(self) -> None:
        curve = self.project.dataset.curve(self.active_curve_id) if self.active_curve_id else None
        if curve is None:
            self.diagnostics.set_residual(None)
            return
        record = self.project.results.get("fit_by_curve", {}).get(self.active_curve_id, {})
        if "global_key" in record:
            result = self.project.results.get("global_fit_baselines", {}).get(record["global_key"])
        else:
            result = record.get("baseline")
        if isinstance(result, dict):
            result = FitResult.from_dict(result)
        if result is None:
            recorded = self.project.results.get(curve.id)
            result = recorded if isinstance(recorded, FitResult) else self._last_fit_result()
        output = result.curve_outputs.get(curve.id) if result else None
        if output is None:
            self.diagnostics.set_residual(None)
            return
        historical = (curve.state != CurveState.FITTED or output.indices.max(initial=-1) >= len(curve))
        rows = output.indices if historical else curve.row_indices[output.indices]
        standardized = bool(output.statistics.get("standardized_residuals"))
        self.diagnostics.set_residual(
            output.weighted_residual if standardized else output.residual,
            indices=rows, x=output.x, historical=historical, standardized=standardized,
        )

    def refresh_worksheet(self) -> None:
        if not self.worksheet_dock.isVisible():
            self.worksheet.set_curve(None)
            return
        curve = self.project.dataset.curve(self.active_curve_id) if self.active_curve_id else None
        self.worksheet.set_curve(curve)

    def _filter_curves(self, text: str) -> None:
        query = text.casefold().strip()
        for top in range(self.curve_tree.topLevelItemCount()):
            series = self.curve_tree.topLevelItem(top)
            visible_children = 0
            for child_index in range(series.childCount()):
                child = series.child(child_index)
                visible = not query or query in child.text(1).casefold()
                child.setHidden(not visible)
                visible_children += int(visible)
            series.setHidden(bool(query) and visible_children == 0)

    def _show_offscreen_active_spectrum(self, name: str) -> None:
        label = self.offscreen_active_spectrum
        caption = self.tr("Active spectrum: %1").replace("%1", name) if name else ""
        label.setText(caption)
        label.setToolTip(caption)
        label.setVisible(bool(name))

    def _load_custom_functions(self) -> None:
        self.registry.set_project_functions(self.project.custom_functions)

    def _autosave(self) -> None:
        return self.session._autosave()

    def _clear_recovery(self) -> None:
        return self.session._clear_recovery()

    def _remember_recent_project(self, path) -> None:
        return self.session._remember_recent_project(path)

    def _refresh_recent_projects(self) -> None:
        return self.session._refresh_recent_projects()

    def show_recovery_sessions(self, *, startup: bool = False) -> None:
        return self.session.show_recovery_sessions(startup=startup)

    def _monitor_recovery_count(self) -> None:
        return self.session._monitor_recovery_count()

    def _confirm_discard_or_save(self) -> bool:
        return self.session._confirm_discard_or_save()

    def _ensure_editable(self, *, prepare_plot: bool = True) -> bool:
        if getattr(self, "_project_loading", False):
            self._notify(self.tr("Wait for project loading to finish."), warning=True)
            return False
        if self.task_running:
            # A running fit or analysis works on a snapshot and writes its result
            # back on completion; edits made meanwhile would be overwritten or
            # leave a result marked current for data it never saw.
            self._notify(self.tr("Stop or wait for the running fit or analysis before editing."), warning=True)
            return False
        if self.project.read_only:
            QMessageBox.information(
                self,
                self.tr("Read-only project"),
                self.tr("This project is locked by another instance. Use Save As to create an editable copy."),
            )
            return False
        if prepare_plot:
            editor = getattr(self, "_function_point_editor", None)
            if editor is not None and editor.active and not editor.committing:
                self.plot_workspace.cancel_placement()
            self.plot_workspace.restore_data_view_for_editing()
        return True

    def _fixed_notice(self) -> None:
        self._notify(
            "🔒 " + self.tr("This parameter is fixed. Hold Ctrl and drag to change the fixed value."),
            warning=True,
        )

    def _linked_notice(self, link: str) -> None:
        QMessageBox.information(
            self,
            self.tr("Linked parameter"),
            self.tr("This parameter is controlled by the relation:") + f"\n{link}\n\n" + self.tr("Edit the relation in the parameter table."),
        )
        self.model_dock.raise_()

    def _notify(self, message: str, *, warning: bool = False) -> None:
        self.statusBar().showMessage(message, 8000)
        self._log(("WARNING: " if warning else "") + message)

    def _log(self, message: str) -> None:
        self.log.appendPlainText(message)

    def _show_error(self, title: str, error: Exception) -> None:
        self._log(f"{title}: {error}")
        QMessageBox.critical(self, title, str(error))

    def _title(self) -> str:
        marker = " *" if self.project.dirty else ""
        mode = " [read-only]" if self.project.read_only else ""
        source_file = self.project.ui_state.get("recovery_source_file", "")
        project_name = self.project.path.stem if self.project.path is not None else (
            Path(source_file).stem if source_file else self.project.name
        )
        return f"{project_name}{marker}{mode} — CurveMole {__version__}"

    def _restore_layout(self) -> None:
        geometry = self.settings.value("geometry")
        state = self.settings.value("window_state")
        layout_schema = self.settings.value("layout/schema_version", 0, type=int)
        if geometry:
            self.restoreGeometry(geometry)
        # QMainWindow state serialises the complete dock hierarchy.  Restoring
        # state written by the old, non-tabbed layout before rebuilding the new
        # hierarchy can crash inside Qt on Linux (and has also proved unsafe on
        # Windows).  Keep all other preferences, but migrate the window layout
        # once whenever its schema changes.
        if state and layout_schema == self._LAYOUT_SCHEMA_VERSION:
            self.restoreState(state)
        if layout_schema != self._LAYOUT_SCHEMA_VERSION:
            self._apply_tabbed_tool_layout()
            self.settings.setValue("layout/schema_version", self._LAYOUT_SCHEMA_VERSION)
            self.settings.remove("layout/tabbed_tools_v1")
        collapsed = self.settings.value("layout/collapsed_docks", {})
        self.dock_collapse.restore(collapsed if isinstance(collapsed, dict) else {})
        self.apply_theme(str(self.settings.value("theme", "system")))
        self._queue_tool_tab_refresh()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.automation_runner.process is not None:
            QMessageBox.information(self, "Automation running", "Stop the automation or wait for it to finish before closing.")
            event.ignore()
            return
        if self.task_running:
            QMessageBox.warning(self, self.tr("Task running"), self.tr("Cancel the running task before quitting."))
            event.ignore()
            return
        if not self._confirm_discard_or_save():
            event.ignore()
            return
        if not self._startup_pending:
            self.settings.setValue("geometry", self.saveGeometry())
            self.settings.setValue("window_state", self.saveState())
            self.settings.setValue("layout/collapsed_docks", self.dock_collapse.save())
        self._finish_session()
        event.accept()

    def _finish_session(self) -> None:
        """Release session markers on window close and on application quit."""
        if self._session_finished:
            return
        self.plot_workspace.cancel_placement()
        self._session_finished = True
        if self._plugin_startup is not None:
            self._plugin_startup.cancel()
        self.recovery_monitor_timer.stop()
        self._lock_monitor.stop()
        self._cancel_project_transfer()
        self.autosave_timer.stop()
        self._manual_save_controller.shutdown()
        self._autosave_controller.shutdown()
        self._release_lock()
        session = getattr(self, "_recovery_session", None)
        if session is not None:
            try:
                session.finish(preserve=True)
            except OSError as exc:
                self._log(f"Recovery session cleanup failed: {exc}")
        try:
            self.folder_import.shutdown()
            self.plugin_host.emit("shutdown")
        finally:
            self.plugin_manager.finish_session()

    def _cancel_project_transfer(self) -> None:
        return self.session._cancel_project_transfer()

    def _check_project_file_unchanged(self, path: Path, expected: str | None) -> None:
        return self.session._check_project_file_unchanged(path, expected)

    def _prepare_project_save_lock(self, path: Path):
        return self.session._prepare_project_save_lock(path)

    def _guard_project_commit(self, lock: ProjectLock, path: Path, expected: str | None) -> None:
        return self.session._guard_project_commit(lock, path, expected)

    def _adopt_saved_project_lock(self, lock: ProjectLock, path: Path) -> None:
        return self.session._adopt_saved_project_lock(lock, path)

    def _poll_project_lock(self) -> None:
        return self.session._poll_project_lock()

    def _poll_project_transfer(self) -> None:
        return self.session._poll_project_transfer()

    def _release_lock(self) -> None:
        return self.session._release_lock()

    def dragEnterEvent(self, event: Any) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: Any) -> None:
        # Import validity follows file contents rather than the filename suffix.
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        projects = [path for path in paths if Path(path).suffix.lower() == ".fitproj"]
        data = [path for path in paths
                if Path(path).is_file() and Path(path).suffix.lower() != ".fitproj"]
        if projects:
            ignored = len(projects) - 1 + len(data)
            self.open_project(projects[0])
            if ignored:
                self._notify(
                    self.tr("Opened ") + Path(projects[0]).name + self.tr("; ignored ")
                    + f"{ignored} " + self.tr("other dropped file(s). Drop a project on its own, "
                                              "then drop data files to import them."),
                    warning=True,
                )
        elif data:
            self.import_data(data)
        if paths:
            event.acceptProposedAction()


def _state_colour(state: CurveState) -> QColor:
    return {
        CurveState.NOT_FITTED: QColor("#666666"),
        CurveState.READY: QColor("#0072B2"),
        CurveState.RUNNING: QColor("#E69F00"),
        CurveState.FITTED: QColor("#009E73"),
        CurveState.MODIFIED: QColor("#CC79A7"),
        CurveState.FAILED: QColor("#D55E00"),
    }[state]


def _mask_transfer_point(curve: Curve, x_value: float, tolerance: float) -> int:
    finite = np.isfinite(curve.x)
    if not np.any(finite):
        return 0
    indices = np.flatnonzero(finite)
    index = int(indices[np.argmin(np.abs(curve.x[finite] - x_value))])
    if abs(float(curve.x[index]) - x_value) > tolerance:
        return 0
    curve.masks[curve.active_mask].excluded[index] = True
    curve.masks[curve.active_mask].ranges.append((x_value - tolerance, x_value + tolerance))
    return 1


def _unmask_transfer_point(curve: Curve, x_value: float, tolerance: float) -> int:
    finite = np.isfinite(curve.x)
    if not np.any(finite):
        return 0
    indices = np.flatnonzero(finite)
    index = int(indices[np.argmin(np.abs(curve.x[finite] - x_value))])
    if abs(float(curve.x[index]) - x_value) > tolerance:
        return 0
    mask = curve.masks[curve.active_mask]
    changed = int(mask.excluded[index])
    mask.excluded[index] = False
    return changed


def _resource_path(name: str) -> Path | None:
    try:
        value = resources.files("curvemole.resources").joinpath(name)
        return Path(str(value))
    except Exception:
        return None
