"""CurveMole's single, dockable desktop workspace."""

from __future__ import annotations

import copy
import json
import math
import re
import time
import traceback
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
from platformdirs import user_cache_path
from PySide6.QtCore import QObject, QSettings, QSize, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QPalette,
    QPixmap,
    QUndoCommand,
    QUndoStack,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStyle,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.calculator import (
    apply_background_subtraction,
    apply_curve_operation,
    apply_scalar,
)
from curvemole.core.data import Curve, CurveState, Series
from curvemole.core.export import export_bundle
from curvemole.core.fitting import CancellationToken, FitPlan, FitResult, FitSettings, Fitter
from curvemole.core.functions import formula_definition
from curvemole.core.importers import import_file
from curvemole.core.initialization import (
    PeakSuggestion,
    component_from_suggestion,
    find_peak_suggestions,
    initialise_peak_component,
    initialise_spline_component,
)
from curvemole.core.models import Component, Model, area_for_height
from curvemole.core.parameters import resolve_parameter_values
from curvemole.core.plugins import PluginManager
from curvemole.core.project import Project
from curvemole.core.recovery import RecoveryManager
from curvemole.core.registry import default_registry
from curvemole.core.serialization import ProjectLock, load_project, save_project
from curvemole.core.uncertainty import UncertaintyAnalyzer
from curvemole.gui.colours import (
    DEFAULT_SERIES_PALETTE,
    SERIES_PALETTES,
    spectrum_colour_allowed,
)
from curvemole.gui.dialogs import (
    AboutDialog,
    AddComponentDialog,
    BackgroundComponentsDialog,
    CopyFitDialog,
    ExportBundleDialog,
    FitPlanDialog,
    ImportMappingDialog,
    ParameterLinkDialog,
    PluginManagerDialog,
)
from curvemole.gui.external import open_with_host_application
from curvemole.gui.panels import (
    CalculatorPanel,
    DiagnosticsPanel,
    FunctionBuilderPanel,
    ModelPanel,
    UncertaintyPanel,
    WorksheetPanel,
)
from curvemole.gui.plot import PlotWorkspace
from curvemole.version import __version__

PALETTE = list(SERIES_PALETTES[DEFAULT_SERIES_PALETTE])


def _resource_icon(filename: str, crop: tuple[int, int, int, int] | None = None) -> QIcon:
    """Return an icon bundled with CurveMole."""
    pixmap = QPixmap(str(resources.files("curvemole.resources").joinpath(filename)))
    if crop is not None:
        pixmap = pixmap.copy(*crop)
    return QIcon(pixmap)


class Worker(QObject):
    finished = Signal(object)
    failed = Signal(str, str)
    progress = Signal(object, str)

    def __init__(self, operation: Callable[[Callable[[float | None, str], None]], Any]) -> None:
        super().__init__()
        self.operation = operation

    @Slot()
    def run(self) -> None:
        try:
            result = self.operation(lambda value, text: self.progress.emit(value, text))
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc), traceback.format_exc())


class CallbackCommand(QUndoCommand):
    def __init__(
        self,
        text: str,
        redo: Callable[[], None],
        undo: Callable[[], None],
    ) -> None:
        super().__init__(text)
        self._redo = redo
        self._undo = undo

    def redo(self) -> None:
        self._redo()

    def undo(self) -> None:
        self._undo()


class CurveTree(QTreeWidget):
    activeCurveChanged = Signal(object)
    curveVisibilityChanged = Signal(str, bool)
    curveRenamed = Signal(str, str)
    seriesRenamed = Signal(str, str)
    curveColourRequested = Signal(str)
    seriesPaletteRequested = Signal(str, str)
    newSeriesRequested = Signal()
    curvesMoveRequested = Signal(object, str)
    curvesReorderRequested = Signal(object, int)
    seriesMergeRequested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderLabels([self.tr("Visible"), self.tr("Series / Curve"), self.tr("State")])
        self.setSelectionMode(self.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self._updating = False
        self._project: Project | None = None
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.currentItemChanged.connect(self._active_changed)
        self.itemChanged.connect(self._item_changed)

    def populate(self, project: Project, active_curve_id: str | None) -> None:
        self._project = project
        self._updating = True
        self.clear()
        active_item: QTreeWidgetItem | None = None
        for series in project.dataset.series:
            parent = QTreeWidgetItem(["", series.name, ""])
            parent.setData(1, Qt.ItemDataRole.UserRole, ("series", series.id))
            parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsEditable)
            self.addTopLevelItem(parent)
            for curve in series.curves:
                child = QTreeWidgetItem(["", curve.name, curve.state.value])
                child.setData(1, Qt.ItemDataRole.UserRole, ("curve", curve.id))
                child.setFlags(
                    child.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEditable
                    | Qt.ItemFlag.ItemIsSelectable
                )
                child.setCheckState(0, Qt.CheckState.Checked if curve.visible else Qt.CheckState.Unchecked)
                child.setForeground(2, _state_colour(curve.state))
                parent.addChild(child)
                if curve.id == active_curve_id:
                    active_item = child
            parent.setExpanded(True)
        self.resizeColumnToContents(0)
        self.resizeColumnToContents(1)
        if active_item is not None:
            self.setCurrentItem(active_item)
        self._updating = False

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

    def _show_context_menu(self, position: Any) -> None:
        item = self.itemAt(position)
        project = self._project
        menu = QMenu(self)
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
            merge_menu = menu.addMenu(self.tr("Merge series into"))
            targets = [series for series in project.dataset.series if series.id != series_id]
            merge_menu.setEnabled(bool(targets))
            for target in targets:
                action = merge_menu.addAction(target.name)
                action.triggered.connect(
                    lambda checked=False, source_id=series_id, target_id=target.id: (
                        self.seriesMergeRequested.emit(source_id, target_id)
                    )
                )
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
            self.curveVisibilityChanged.emit(curve_id, item.checkState(0) == Qt.CheckState.Checked)
        elif column == 1:
            self.curveRenamed.emit(curve_id, item.text(1))


class MainWindow(QMainWindow):
    def __init__(self, project: Project | None = None) -> None:
        super().__init__()
        self.registry = default_registry()
        self.project = project or Project()
        self.active_curve_id: str | None = self.project.curves[0].id if self.project.curves else None
        self.selected_component_id: str | None = None
        self.fit_settings = FitSettings()
        self.last_fit_plan: FitPlan | None = None
        self._paused_result: FitResult | None = None
        self._thread: QThread | None = None
        self._worker: Worker | None = None
        self._cancellation: CancellationToken | None = None
        self._project_lock: ProjectLock | None = None
        self._pending_component: Component | None = None
        self._pending_component_curve_id: str | None = None
        self.settings = QSettings("CurveMole", "CurveMole")
        self.last_peak_function_id = str(
            self.settings.value("last_peak_function", "gaussian")
        )
        self._update_manager = QNetworkAccessManager(self)
        self._update_reply: Any | None = None
        self.undo_stack = QUndoStack(self)
        self.recovery = RecoveryManager(user_cache_path("CurveMole") / "recovery")

        self.setWindowTitle(self._title())
        self.setMinimumSize(960, 640)
        self.resize(1440, 900)
        self.setAcceptDrops(True)
        icon_path = _resource_path("curvemole.png")
        if icon_path:
            self.setWindowIcon(QIcon(str(icon_path)))

        self.plot_workspace = PlotWorkspace(self.registry)
        self.setCentralWidget(self.plot_workspace)
        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._connect_signals()

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage(self.tr("Ready"), 4000)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(10 * 60 * 1000)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start()
        self._load_custom_functions()
        self._normalise_component_names()
        self._normalise_spectrum_colours()
        self._restore_layout()
        self.refresh_all()
        self.update_check_timer = QTimer(self)
        self.update_check_timer.setInterval(60 * 60 * 1000)
        self.update_check_timer.timeout.connect(self._automatic_update_check)
        self.update_check_timer.start()
        QTimer.singleShot(2500, self._automatic_update_check)

    def _build_docks(self) -> None:
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(3, 3, 3, 3)
        self.curve_filter = QLineEdit()
        self.curve_filter.setPlaceholderText(self.tr("Search curves…"))
        self.curve_filter.textChanged.connect(self._filter_curves)
        self.curve_tree = CurveTree()
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
        self.function_dock = self._dock(self.tr("Function Builder"), self.function_builder, Qt.DockWidgetArea.RightDockWidgetArea)
        self.function_dock.hide()

        self.uncertainty_panel = UncertaintyPanel()
        self.uncertainty_dock = self._dock(self.tr("Uncertainty Analysis"), self.uncertainty_panel, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.uncertainty_dock.hide()
        self.tabifyDockWidget(self.log_dock, self.worksheet_dock)
        self.tabifyDockWidget(self.worksheet_dock, self.diagnostics_dock)
        self.tabifyDockWidget(self.diagnostics_dock, self.uncertainty_dock)

    def _dock(self, title: str, widget: QWidget, area: Qt.DockWidgetArea) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(title.replace(" ", "_"))
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.addDockWidget(area, dock)
        return dock

    def _build_actions(self) -> None:
        style = self.style()
        self.new_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_FileIcon), self.tr("New project"), self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.new_project)
        self.open_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton), self.tr("Open project…"), self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(lambda checked=False: self.open_project())
        self.import_action = QAction(self.tr("Import data…"), self)
        self.import_action.setShortcut("Ctrl+I")
        self.import_action.triggered.connect(lambda checked=False: self.import_data())
        self.save_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), self.tr("Save project"), self)
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
        self.quit_action = QAction(self.tr("Quit"), self)
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_action.triggered.connect(self.close)

        self.undo_action = self.undo_stack.createUndoAction(self, self.tr("Undo"))
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.redo_action = self.undo_stack.createRedoAction(self, self.tr("Redo"))
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)

        self.calculator_action = self.calculator_dock.toggleViewAction()
        self.calculator_action.setText(self.tr("Data Calculator"))
        self.calculator_action.setIcon(_resource_icon("calculator.png"))
        self.calculator_action.setToolTip(self.tr("Data Calculator"))
        self.worksheet_action = self.worksheet_dock.toggleViewAction()
        self.worksheet_action.setText(self.tr("Worksheet"))
        self.function_action = self.function_dock.toggleViewAction()
        self.function_action.setText(self.tr("Function Builder"))
        self.uncertainty_action = self.uncertainty_dock.toggleViewAction()
        self.uncertainty_action.setText(self.tr("Uncertainty Analysis"))
        self.diagnostics_action = self.diagnostics_dock.toggleViewAction()
        self.diagnostics_action.setText(self.tr("Diagnostics"))
        self.log_action = self.log_dock.toggleViewAction()
        self.log_action.setText(self.tr("Log"))
        self.plugins_action = QAction(self.tr("Plugin Manager…"), self)
        self.plugins_action.triggered.connect(self.show_plugin_manager)

        self.add_component_action = QAction(self.tr("Add component…"), self)
        self.add_component_action.setIcon(_resource_icon("add-peak.png"))
        self.add_component_action.setToolTip(self.tr("Add component…"))
        self.add_component_action.setShortcut("Ctrl++")
        self.add_component_action.triggered.connect(self.add_component)
        self.quick_peak_action = QAction(self.tr("Quick Peak"), self)
        self.quick_peak_action.setIcon(_resource_icon("quick-add-peak.png"))
        self.quick_peak_action.setToolTip(
            self.tr("Quick Peak\nAdd the last selected peak function without reopening the component dialog.")
        )
        self.quick_peak_action.triggered.connect(self.quick_peak)
        self.copy_fit_action = QAction(self.tr("Copy fit…"), self)
        self.copy_fit_action.triggered.connect(self.copy_fit)
        self.find_peaks_action = QAction(self.tr("Find positive peaks…"), self)
        self.find_peaks_action.triggered.connect(self.find_peaks)
        self.mask_tolerance_action = QAction(self.tr("Mask transfer tolerance…"), self)
        self.mask_tolerance_action.triggered.connect(self.set_mask_tolerance)
        self.subtract_background_action = QAction(self.tr("Subtract background…"), self)
        self.subtract_background_action.setIcon(_resource_icon("subtract-background.png"))
        self.subtract_background_action.setToolTip(
            self.tr("Subtract background…\nSubtract selected model functions that are marked as background.")
        )
        self.subtract_background_action.triggered.connect(self.subtract_background)

        self.fit_action = QAction(self.tr("Fit…"), self)
        self.fit_action.setIcon(_resource_icon("fit.png", crop=(290, 120, 525, 525)))
        self.fit_action.setToolTip(self.tr("Fit…"))
        self.fit_action.setShortcut("F5")
        self.fit_action.triggered.connect(self.start_fit)
        self.quick_fit_action = QAction(self.tr("Quick Fit"), self)
        self.quick_fit_action.setIcon(_resource_icon("quick-fit.png"))
        self.quick_fit_action.setToolTip(
            self.tr("Quick Fit\nFit the current selection with the last accepted fit settings.")
        )
        self.quick_fit_action.triggered.connect(self.quick_fit)
        self.resume_action = QAction(self.tr("Continue paused sequence"), self)
        self.resume_action.setEnabled(False)
        self.resume_action.triggered.connect(self.resume_sequence)
        self.cancel_action = QAction(self.tr("Cancel running task"), self)
        self.cancel_action.setEnabled(False)
        self.cancel_action.triggered.connect(self.cancel_task)

        self.reset_layout_action = QAction(self.tr("Reset layout"), self)
        self.reset_layout_action.triggered.connect(self.reset_layout)
        self.auto_axes_action = QAction(self.tr("Auto axes"), self)
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

    def _build_menus(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu(self.tr("&File"))
        file_menu.addActions([self.new_action, self.open_action, self.import_action])
        file_menu.addSeparator()
        file_menu.addActions([self.save_action, self.save_as_action, self.portable_action])
        file_menu.addAction(self.export_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        edit_menu = menu.addMenu(self.tr("&Edit"))
        edit_menu.addActions([self.undo_action, self.redo_action])

        data_menu = menu.addMenu(self.tr("&Data"))
        data_menu.addActions(
            [
                self.import_action,
                self.subtract_background_action,
                self.calculator_action,
                self.worksheet_action,
            ]
        )
        data_menu.addSeparator()
        data_menu.addAction(self.mask_tolerance_action)

        model_menu = menu.addMenu(self.tr("&Model"))
        model_menu.addActions(
            [
                self.add_component_action,
                self.quick_peak_action,
                self.copy_fit_action,
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
        themes = view_menu.addMenu(self.tr("Theme"))
        themes.addActions([self.system_theme_action, self.light_theme_action, self.dark_theme_action])
        axes = view_menu.addMenu(self.tr("Axes"))
        axes.addActions(
            [
                self.auto_axes_action,
                self.log_x_action,
                self.log_y_action,
                self.reverse_x_action,
                self.reverse_y_action,
                self.lock_view_action,
            ]
        )
        view_menu.addSeparator()
        view_menu.addAction(self.reset_layout_action)

        tools_menu = menu.addMenu(self.tr("&Tools"))
        tools_menu.addActions(
            [self.calculator_action, self.function_action, self.uncertainty_action, self.plugins_action]
        )

        help_menu = menu.addMenu(self.tr("&Help"))
        help_menu.addActions(
            [self.quick_start_action, self.manual_action, self.update_action, self.report_action, self.about_action]
        )

    def _build_toolbar(self) -> None:
        toolbar = QToolBar(self.tr("Main toolbar"), self)
        toolbar.setObjectName("Main_toolbar")
        toolbar.setMovable(True)
        toolbar.setIconSize(QSize(40, 40))
        self.addToolBar(toolbar)
        toolbar.addActions(
            [
                self.open_action,
                self.import_action,
                self.save_action,
                self.undo_action,
                self.redo_action,
                self.calculator_action,
                self.subtract_background_action,
                self.add_component_action,
                self.quick_peak_action,
                self.fit_action,
                self.quick_fit_action,
                self.cancel_action,
                self.export_action,
            ]
        )
        for action in (
            self.calculator_action,
            self.subtract_background_action,
            self.add_component_action,
            self.quick_peak_action,
            self.fit_action,
            self.quick_fit_action,
        ):
            button = toolbar.widgetForAction(action)
            if isinstance(button, QToolButton):
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

    def _connect_signals(self) -> None:
        self.curve_tree.activeCurveChanged.connect(self._set_active_curve)
        self.curve_tree.itemSelectionChanged.connect(self._selection_changed)
        self.curve_tree.curveVisibilityChanged.connect(self._set_visibility)
        self.curve_tree.curveRenamed.connect(self._rename_curve)
        self.curve_tree.seriesRenamed.connect(self._rename_series)
        self.curve_tree.curveColourRequested.connect(self.choose_curve_colour)
        self.curve_tree.seriesPaletteRequested.connect(self.apply_series_palette)
        self.curve_tree.newSeriesRequested.connect(self.create_series)
        self.curve_tree.curvesMoveRequested.connect(self.move_curves_to_series)
        self.curve_tree.curvesReorderRequested.connect(self.reorder_curves)
        self.curve_tree.seriesMergeRequested.connect(self.merge_series)
        self.model_panel.componentSelected.connect(self._set_component)
        self.model_panel.addRequested.connect(self.add_component)
        self.model_panel.duplicateRequested.connect(self.duplicate_component)
        self.model_panel.deleteRequested.connect(self.delete_component)
        self.model_panel.moveRequested.connect(self.move_component)
        self.model_panel.enabledRequested.connect(self.enable_component)
        self.model_panel.backgroundRequested.connect(self.set_component_background)
        self.model_panel.parameterChangeRequested.connect(self.change_parameter)
        self.model_panel.parameterLinkRequested.connect(self.edit_parameter_link)
        self.model_panel.bulkFixedRequested.connect(self.set_component_fixed)
        self.model_panel.copyFitRequested.connect(self.copy_fit)
        self.plot_workspace.componentSelected.connect(self._set_component)
        self.plot_workspace.maskPointRequested.connect(self.mask_point)
        self.plot_workspace.maskRangeRequested.connect(self.mask_range)
        self.plot_workspace.peakDragged.connect(self.drag_peak)
        self.plot_workspace.widthDragged.connect(self.drag_width)
        self.plot_workspace.splineNodeDragged.connect(self.drag_spline_node)
        self.plot_workspace.peakPlacementFinished.connect(self._graphical_peak_placed)
        self.plot_workspace.splinePlacementFinished.connect(self._graphical_spline_placed)
        self.plot_workspace.placementCancelled.connect(self._graphical_placement_cancelled)
        self.calculator.applyRequested.connect(self.apply_calculator)
        self.function_builder.functionAdded.connect(lambda _: self._notify(self.tr("Function library updated.")))
        self.worksheet_dock.visibilityChanged.connect(lambda visible: self.refresh_worksheet() if visible else None)
        self.uncertainty_panel.runRequested.connect(self.start_uncertainty)

    def refresh_all(self) -> None:
        self.setWindowTitle(self._title())
        self.curve_tree.populate(self.project, self.active_curve_id)
        selected = self.curve_tree.selected_curve_ids()
        self.model_panel.set_context(
            self.project,
            self.active_curve_id,
            len(selected),
            self.selected_component_id,
        )
        self.plot_workspace.set_context(
            self.project,
            self.active_curve_id,
            selected,
            self.selected_component_id,
        )
        self.calculator.set_curves(self.project)
        self.function_builder.set_project(self.project)
        self.uncertainty_panel.set_parameters(self.project, self.active_curve_id)
        self.refresh_worksheet()
        self._refresh_diagnostics()

    def new_project(self) -> None:
        if not self._confirm_discard_or_save():
            return
        self._release_lock()
        self.project = Project()
        self.active_curve_id = None
        self.selected_component_id = None
        self.undo_stack.clear()
        self.refresh_all()

    def open_project(self, path: str | Path | None = None) -> None:
        if not self._confirm_discard_or_save():
            return
        if path is None:
            selected, _ = QFileDialog.getOpenFileName(
                self, self.tr("Open CurveMole project"), "", self.tr("CurveMole projects (*.fitproj)")
            )
            if not selected:
                return
            path = selected
        try:
            project = load_project(path)
            self._release_lock()
            lock = ProjectLock(Path(path))
            lock.__enter__()
            self._project_lock = lock
            if not lock.acquired:
                project.read_only = True
                self._notify(self.tr("Project is already open elsewhere; opened read-only."), warning=True)
            self.project = project
            self.active_curve_id = project.curves[0].id if project.curves else None
            self.selected_component_id = None
            self.undo_stack.clear()
            self._load_custom_functions()
            self._normalise_component_names()
            self._normalise_spectrum_colours()
            self.refresh_all()
            self._notify(self.tr("Project opened."))
        except Exception as exc:
            self._show_error(self.tr("Open project"), exc)

    def import_data(self, paths: list[str] | None = None) -> None:
        if not self._ensure_editable():
            return
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(
                self,
                self.tr("Import one-dimensional curves"),
                "",
                self.tr("Supported data (*.txt *.dat *.csv *.tsv);;All files (*)"),
            )
        if not paths:
            return
        series = Series(self.tr("Imported series"))
        series.metadata["palette"] = DEFAULT_SERIES_PALETTE
        shared_mapping = None
        shared_config = None
        apply_all = False
        try:
            for index, path in enumerate(paths):
                if index == 0 or not apply_all:
                    dialog = ImportMappingDialog(path, batch_size=len(paths), parent=self)
                    if dialog.exec() != dialog.DialogCode.Accepted:
                        return
                    shared_mapping = dialog.mapping()
                    shared_config = dialog.config()
                    apply_all = dialog.apply_all.isChecked()
                curves = import_file(path, shared_mapping, shared_config)
                for curve in curves:
                    curve.colour = PALETTE[(len(self.project.curves) + len(series.curves)) % len(PALETTE)]
                    if len(paths) > 1:
                        curve.name = f"{Path(path).stem}: {curve.name}"
                    series.add(curve)
            self.project.add_series(series)
            self.active_curve_id = series.curves[0].id
            self.selected_component_id = None
            self.refresh_all()
            self._notify(self.tr("Imported ") + f"{len(series.curves)} " + self.tr("curve(s)."))
        except Exception as exc:
            self._show_error(self.tr("Import data"), exc)

    def save_project(self, *, save_as: bool = False) -> bool:
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
        try:
            save_project(self.project, path)
            self.project.read_only = False
            self.recovery.clear(self.project.id)
            self.setWindowTitle(self._title())
            self._notify(self.tr("Project saved."))
            return True
        except Exception as exc:
            self._show_error(self.tr("Save project"), exc)
            return False

    def save_portable_copy(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Save portable copy"),
            f"{self.project.name}-portable.fitproj",
            self.tr("CurveMole projects (*.fitproj)"),
        )
        if not selected:
            return
        try:
            save_project(
                self.project,
                selected,
                portable=True,
                update_project_path=False,
            )
            self._notify(self.tr("Portable copy saved."))
        except Exception as exc:
            self._show_error(self.tr("Save portable copy"), exc)

    def export_analysis(self) -> None:
        remembered = self.project.export_config.get("directory")
        dialog = ExportBundleDialog(remembered, self)
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
                dialog.directory.text(),
                result=result,
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

    def add_component(self) -> None:
        if not self._ensure_editable():
            return
        if not self.active_curve_id:
            self._notify(self.tr("Activate a curve first."), warning=True)
            return
        curve = self.project.dataset.curve(self.active_curve_id)
        self.plot_workspace.cancel_placement()
        dialog = AddComponentDialog(self.registry, curve, self)
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

    def quick_peak(self) -> None:
        if not self._ensure_editable():
            return
        if not self.active_curve_id:
            self._notify(self.tr("Activate a curve first."), warning=True)
            return
        self.plot_workspace.cancel_placement()
        try:
            function_id = self._quick_peak_function_id()
            definition = self.registry.get(function_id)
            component = Component.create(function_id, registry=self.registry)
            self.last_peak_function_id = function_id
            self.settings.setValue("last_peak_function", function_id)
            self._pending_component = component
            self._pending_component_curve_id = self.active_curve_id
            self.plot_workspace.begin_peak_placement(definition.display_name)
            self._notify(
                self.tr("Quick Peak: click the peak centre and drag horizontally to set its initial FWHM.")
            )
        except Exception as exc:
            self._show_error(self.tr("Quick Peak"), exc)

    def _quick_peak_function_id(self) -> str:
        try:
            definition = self.registry.get(self.last_peak_function_id)
            if definition.kind == "peak":
                return definition.identifier
        except (KeyError, ValueError):
            pass
        for definition in self.registry.values():
            if definition.kind == "peak":
                return definition.identifier
        raise ValueError(self.tr("No peak function is available in the current registry."))

    def _graphical_peak_placed(self, centre: float, _: float, fwhm: float) -> None:
        component = self._pending_component
        curve_id = self._pending_component_curve_id
        self._pending_component = None
        self._pending_component_curve_id = None
        if component is None or curve_id is None:
            return
        try:
            curve = self.project.dataset.curve(curve_id)
            finite = np.isfinite(curve.x) & np.isfinite(curve.y) & ~curve.effective_mask
            if not np.any(finite):
                raise ValueError(self.tr("The active curve has no usable points."))
            indices = np.flatnonzero(finite)
            point_index = int(indices[np.argmin(np.abs(curve.x[finite] - centre))])
            model = self.project.model_for(curve_id)
            existing = np.asarray(
                model.evaluate(
                    curve.x,
                    curve_id=curve_id,
                    values=self.project.resolved_parameter_values(),
                    registry=self.registry,
                ),
                dtype=float,
            )
            residual = curve.y - existing
            residual_offset = float(np.nanmedian(residual[finite]))
            height = float(residual[point_index] - residual_offset)
            scale = float(np.ptp(curve.y[finite]))
            minimum_height = max(scale * 0.02, np.finfo(float).eps)
            if not math.isfinite(height) or height <= 0:
                height = minimum_height
            width = max(float(fwhm), np.finfo(float).eps)
            suggestion = PeakSuggestion(
                x=float(centre),
                height=height,
                fwhm=width,
                prominence=height,
                sign=1,
            )
            initialise_peak_component(component, suggestion, registry=self.registry)
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
        for model in self.project.models.values():
            used: dict[str, set[int]] = {}
            pending: list[Component] = []
            for component in model.components:
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

    def _normalise_spectrum_colours(self) -> None:
        changed = False
        fallback = SERIES_PALETTES[DEFAULT_SERIES_PALETTE]
        for series in self.project.dataset.series:
            palette = SERIES_PALETTES.get(str(series.metadata.get("palette", "")), fallback)
            for index, curve in enumerate(series.curves):
                if spectrum_colour_allowed(curve.colour):
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
        model.components = Model.from_dict(before).components
        self.selected_component_id = component.id
        self._push_model_state(curve_id, before, after, self.tr("Add component"))

    def duplicate_component(self, component_id: str) -> None:
        created_id: list[str] = []

        def operation(model: Model) -> None:
            duplicate = model.duplicate(component_id)
            self._assign_component_name(
                duplicate, model, exclude_component_id=duplicate.id
            )
            created_id.append(duplicate.id)

        self._model_mutation(self.tr("Duplicate component"), operation)
        if created_id:
            self.selected_component_id = created_id[-1]
            self.refresh_all()

    def delete_component(self, component_id: str) -> None:
        answer = QMessageBox.question(
            self,
            self.tr("Delete component"),
            self.tr("Delete the selected component? This action can be undone."),
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._model_mutation(self.tr("Delete component"), lambda model: model.remove(component_id))
            self.selected_component_id = None

    def move_component(self, component_id: str, delta: int) -> None:
        if not self.active_curve_id:
            return
        model = self.project.model_for(self.active_curve_id)
        index = next((i for i, item in enumerate(model.components) if item.id == component_id), 0)
        self._model_mutation(self.tr("Reorder component"), lambda value: value.move(component_id, index + delta))

    def enable_component(self, component_id: str, enabled: bool) -> None:
        if not self.active_curve_id:
            return
        component = self.project.model_for(self.active_curve_id).component(component_id)
        old = component.enabled
        self._push_change(
            self.tr("Enable/disable component"),
            lambda: setattr(component, "enabled", enabled),
            lambda: setattr(component, "enabled", old),
        )

    def set_component_background(self, component_id: str, marked: bool) -> None:
        if not self.active_curve_id:
            return
        component = self.project.model_for(self.active_curve_id).component(component_id)
        old = component.is_background
        if old == bool(marked):
            return
        self._push_change(
            self.tr("Mark background") if marked else self.tr("Unmark background"),
            lambda: setattr(component, "is_background", bool(marked)),
            lambda: setattr(component, "is_background", old),
        )

    def change_parameter(self, component_id: str, name: str, field: str, value: Any) -> None:
        if not self.active_curve_id:
            return
        parameter = self.project.model_for(self.active_curve_id).component(component_id).parameters[name]
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
        self._push_change(
            self.tr("Edit parameter"),
            lambda: setattr(parameter, field, value),
            lambda: setattr(parameter, field, old),
        )

    def set_component_fixed(self, component_id: str, fixed: bool) -> None:
        if not self.active_curve_id:
            return
        component = self.project.model_for(self.active_curve_id).component(component_id)
        before = {name: parameter.fixed for name, parameter in component.parameters.items()}
        after = {name: bool(fixed) for name in component.parameters}
        if before == after:
            return

        def restore(values: dict[str, bool]) -> None:
            for name, value in values.items():
                component.parameters[name].fixed = value

        text = self.tr("Lock all parameters") if fixed else self.tr("Unlock all parameters")
        self._push_change(text, lambda: restore(after), lambda: restore(before))

    def edit_parameter_link(self, component_id: str, name: str) -> None:
        if not self.active_curve_id:
            return
        parameter = self.project.model_for(self.active_curve_id).component(component_id).parameters[name]
        dialog = ParameterLinkDialog(
            self.project,
            self.active_curve_id,
            component_id,
            name,
            parameter.link,
            self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self.change_parameter(component_id, name, "link", dialog.selected_link())

    def copy_fit(self) -> None:
        if not self._ensure_editable():
            return
        if not self.active_curve_id:
            return
        dialog = CopyFitDialog(self.project, self.active_curve_id, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        targets, choices = dialog.choices()
        if not targets:
            return
        before = {curve_id: self.project.model_for(curve_id).to_dict() for curve_id in targets}
        self.project.copy_fit(self.active_curve_id, targets, **choices)
        after = {curve_id: self.project.model_for(curve_id).to_dict() for curve_id in targets}
        for curve_id, model in before.items():
            self.project.models[curve_id] = Model.from_dict(model)

        def restore(values: dict[str, dict[str, Any]]) -> None:
            for curve_id, model in values.items():
                self.project.models[curve_id] = Model.from_dict(copy.deepcopy(model))

        self._push_change(
            self.tr("Copy fit"),
            lambda: restore(after),
            lambda: restore(before),
        )

    def subtract_background(self) -> None:
        if not self._ensure_editable():
            return
        if not self.active_curve_id:
            self._notify(self.tr("Activate a curve first."), warning=True)
            return
        curve_id = self.active_curve_id
        curve = self.project.dataset.curve(curve_id)
        model = self.project.model_for(curve_id)
        if not model.components:
            self._notify(
                self.tr("Add at least one model function before subtracting a background."),
                warning=True,
            )
            return

        dialog = BackgroundComponentsDialog(self.project, curve_id, self.registry, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        component_ids = dialog.selected_component_ids()
        if not component_ids:
            self._notify(self.tr("Select at least one background function."), warning=True)
            return

        selected = [model.component(component_id) for component_id in component_ids]
        try:
            background = model.background(
                curve.x,
                curve_id=curve_id,
                values=self.project.resolved_parameter_values(),
                registry=self.registry,
                component_ids=set(component_ids),
            )
        except Exception as exc:
            self._show_error(self.tr("Subtract background"), exc)
            return
        if not np.all(np.isfinite(background)):
            self._notify(
                self.tr("The selected background functions produce non-finite values."),
                warning=True,
            )
            return

        states_before = {
            component.id: (component.is_background, component.enabled)
            for component in selected
        }
        states_after = {component.id: (True, False) for component in selected}
        transformation = apply_background_subtraction(
            curve,
            background,
            method="model_components",
            description=self.tr("Subtract marked model background"),
            parameters={
                "component_ids": list(component_ids),
                "component_names": [component.name for component in selected],
            },
        )
        curve.undo_transformation()

        def restore_states(states: dict[str, tuple[bool, bool]]) -> None:
            for component_id, (marked, enabled) in states.items():
                component = model.component(component_id)
                component.is_background = marked
                component.enabled = enabled

        def redo() -> None:
            if curve.redo_transformations and curve.redo_transformations[-1] is transformation:
                curve.redo_transformation()
            elif transformation not in curve.transformations:
                curve.apply_transformation(transformation)
            restore_states(states_after)

        def undo() -> None:
            if curve.transformations and curve.transformations[-1] is transformation:
                curve.undo_transformation()
            restore_states(states_before)

        self._push_change(self.tr("Subtract background"), redo, undo)
        self._notify(
            self.tr("Background subtracted. Selected background functions were disabled to avoid double-counting.")
        )

    def _apply_background_array(
        self,
        curve: Curve,
        background: np.ndarray,
        *,
        method: str,
        description: str,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        transformation = apply_background_subtraction(
            curve,
            background,
            method=method,
            description=description,
            parameters=parameters,
        )
        curve.undo_transformation()

        def redo() -> None:
            if curve.redo_transformations and curve.redo_transformations[-1] is transformation:
                curve.redo_transformation()
            elif transformation not in curve.transformations:
                curve.apply_transformation(transformation)

        def undo() -> None:
            if curve.transformations and curve.transformations[-1] is transformation:
                curve.undo_transformation()

        self._push_change(self.tr("Subtract background"), redo, undo)

    def find_peaks(self) -> None:
        if not self._ensure_editable():
            return
        if not self.active_curve_id:
            return
        curve = self.project.dataset.curve(self.active_curve_id)
        labels = [self.tr("Positive (default)"), self.tr("Negative"), self.tr("Both signs")]
        selected_sign, accepted = QInputDialog.getItem(
            self,
            self.tr("Find Peaks — Advanced"),
            self.tr("Peak sign:"),
            labels,
            0,
            False,
        )
        if not accepted:
            return
        sign = {
            labels[0]: "positive",
            labels[1]: "negative",
            labels[2]: "both",
        }[selected_sign]
        suggestions = find_peak_suggestions(curve, sign=sign)
        if not suggestions:
            self._notify(self.tr("No positive peak suggestion met the automatic threshold."), warning=True)
            return
        count, ok = QInputDialog.getInt(
            self,
            self.tr("Find Peaks"),
            self.tr("Suggested peaks found: ") + f"{len(suggestions)}\n" + self.tr("How many should be added?"),
            min(1, len(suggestions)),
            1,
            len(suggestions),
        )
        if not ok:
            return
        model = self.project.model_for(self.active_curve_id)
        before = model.to_dict()
        for suggestion in suggestions[:count]:
            model.add(component_from_suggestion(suggestion, "gaussian", registry=self.registry))
        after = model.to_dict()
        self.project.models[self.active_curve_id] = Model.from_dict(before)
        self._push_model_state(self.active_curve_id, before, after, self.tr("Add suggested peaks"))

    def start_fit(self) -> None:
        if not self._ensure_editable():
            return
        if self._thread is not None:
            return
        selected = self.curve_tree.selected_curve_ids()
        if not selected and self.active_curve_id:
            selected = {self.active_curve_id}
        dialog = FitPlanDialog(self.project, selected, self.fit_settings, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        plan = dialog.plan()
        self.fit_settings = plan.settings
        self.last_fit_plan = plan
        self._run_fit(plan)

    def quick_fit(self) -> None:
        if not self._ensure_editable():
            return
        if self._thread is not None:
            return
        if self.last_fit_plan is None:
            self._notify(
                self.tr("Run Fit… once to define the settings used by Quick Fit."),
                warning=True,
            )
            return
        selected = self.curve_tree.selected_curve_ids()
        if not selected and self.active_curve_id:
            selected = {self.active_curve_id}
        if not selected:
            self._notify(self.tr("Select or activate at least one curve first."), warning=True)
            return
        plan = copy.deepcopy(self.last_fit_plan)
        plan.curve_ids = [curve.id for curve in self.project.curves if curve.id in selected]
        plan.spectrum_weights = {
            curve_id: plan.spectrum_weights.get(curve_id, 1.0)
            for curve_id in plan.curve_ids
        }
        try:
            plan.validate()
        except Exception as exc:
            self._show_error(self.tr("Quick Fit"), exc)
            return
        self.fit_settings = copy.deepcopy(plan.settings)
        self.last_fit_plan = copy.deepcopy(plan)
        self._run_fit(plan)

    def _run_fit(self, plan: FitPlan) -> None:
        self._cancellation = CancellationToken()
        fitter = Fitter(self.registry)
        curve_map = {curve.id: curve for curve in self.project.curves}
        self._run_background(
            lambda progress: fitter.fit(
                plan,
                curve_map,
                self.project.models,
                cancellation=self._cancellation,
                progress=progress,
            ),
            self._fit_finished,
            self.tr("Fitting…"),
        )

    def _apply_fit_result_to_project(self, result: FitResult) -> None:
        # Fitting runs in a worker thread. Commit the returned estimates explicitly
        # to the GUI-side project so the redraw never depends on worker-side mutation.
        if result.success:
            fitted_curve_ids = set(result.curve_outputs) or {
                path.split(".", 1)[0] for path in result.parameters
            }
        elif result.paused_curve_id:
            fitted_curve_ids = set(result.curve_outputs)
        else:
            fitted_curve_ids = set()
        if not fitted_curve_ids:
            return

        parameter_map = self.project.parameter_map()
        for path, estimate in result.parameters.items():
            curve_id = path.split(".", 1)[0]
            if curve_id not in fitted_curve_ids or path not in parameter_map:
                continue
            parameter = parameter_map[path]
            parameter.value = float(estimate.value)
            parameter.standard_error = estimate.standard_error
            parameter.ci_low = estimate.ci_low
            parameter.ci_high = estimate.ci_high
        for curve_id in fitted_curve_ids:
            try:
                self.project.dataset.curve(curve_id).state = CurveState.FITTED
            except KeyError:
                continue

    def _fit_finished(self, result: FitResult) -> None:
        self._apply_fit_result_to_project(result)
        self.project.results["last_attempt"] = result
        if result.success:
            self.project.results["last_fit"] = result
        self.project.snapshot(
            "Fit",
            {
                "mode": result.mode.value,
                "settings": result.to_dict(arrays=False)["settings"],
                "result": result.to_dict(arrays=False),
            },
        )
        self.resume_action.setEnabled(bool(result.paused_curve_id))
        self._paused_result = result if result.paused_curve_id else None
        if result.paused_curve_id:
            self.active_curve_id = result.paused_curve_id
        self.refresh_all()
        if result.success or result.curve_outputs:
            self.plot_workspace.auto_range()
        if result.paused_curve_id:
            QMessageBox.warning(
                self,
                self.tr("Sequential fit paused"),
                result.message + "\n\n" + self.tr("Edit the model manually, then choose Continue paused sequence."),
            )
        elif result.success:
            self._notify(self.tr("Fit completed."))
        else:
            self._notify(result.message, warning=True)

    def resume_sequence(self) -> None:
        result = self._paused_result
        if not result or not result.paused_curve_id or not self.last_fit_plan:
            return
        try:
            start = self.last_fit_plan.curve_ids.index(result.paused_curve_id)
        except ValueError:
            return
        plan = copy.deepcopy(self.last_fit_plan)
        plan.curve_ids = plan.curve_ids[start:]
        self._run_fit(plan)

    def cancel_task(self) -> None:
        if self._cancellation:
            self._cancellation.cancel()
            self._notify(self.tr("Cancellation requested…"), warning=True)

    def start_uncertainty(self, method: str, replicates: int, option: Any) -> None:
        if not self._ensure_editable():
            return
        baseline = self._last_fit_result()
        if baseline is None or self.last_fit_plan is None:
            self._notify(self.tr("Run a fit before uncertainty analysis."), warning=True)
            return
        analyzer = UncertaintyAnalyzer(Fitter(self.registry))
        curve_map = {curve.id: curve for curve in self.project.curves}
        self._cancellation = CancellationToken()

        def operation(progress: Callable[[float | None, str], None]) -> Any:
            if method == "profile_likelihood":
                if not self.active_curve_id or not option:
                    raise RuntimeError(self.tr("Choose an active curve and profile parameter."))
                return analyzer.profile_parameter(
                    baseline,
                    self.project.dataset.curve(self.active_curve_id),
                    self.project.model_for(self.active_curve_id),
                    str(option),
                    cancellation=self._cancellation,
                    progress=progress,
                )
            arguments = dict(
                baseline=baseline,
                plan=self.last_fit_plan,
                curves=curve_map,
                models=self.project.models,
                replicates=replicates,
                cancellation=self._cancellation,
                progress=progress,
            )
            if method == "monte_carlo":
                return analyzer.parametric_monte_carlo(**arguments)
            if method == "block_bootstrap":
                return analyzer.block_bootstrap(**arguments, block_length=option)
            return analyzer.residual_bootstrap(**arguments)

        self._run_background(operation, self._uncertainty_finished, self.tr("Uncertainty analysis…"))

    def _uncertainty_finished(self, result: Any) -> None:
        method = getattr(result, "method", "profile_likelihood")
        self.project.results.setdefault("uncertainty", {})[method] = result
        self.project.touch()
        if method == "profile_likelihood":
            self.uncertainty_panel.status.setPlainText(
                f"Parameter: {result.parameter_path}\nConfidence: {result.confidence_level:.3f}\n"
                f"Interval: {result.interval}\nFailed grid points: {result.failed_points}"
            )
        else:
            self.uncertainty_panel.status.setPlainText(
                f"Method: {result.method}\nRequested: {result.requested}\n"
                f"Completed: {result.completed}\nFailed: {result.failed}\nSeed: {result.seed}\n"
                + "\n".join(f"{key}: {value}" for key, value in result.intervals.items())
            )
        self._notify(self.tr("Uncertainty analysis completed."))

    def mask_point(self, x_value: float) -> None:
        unmask = self.plot_workspace.mask_operation.currentData() == "unmask"
        self._apply_mask(
            lambda curve, transfer: _unmask_transfer_point(
                curve, x_value, self._mask_tolerance() if transfer else math.inf
            )
            if unmask
            else curve.mask_point(x_value)
            if not transfer
            else _mask_transfer_point(curve, x_value, self._mask_tolerance())
        )

    def mask_range(self, lower: float, upper: float) -> None:
        unmask = self.plot_workspace.mask_operation.currentData() == "unmask"

        def operation(curve: Curve, transfer: bool) -> int:
            return (
                curve.unmask_interval(lower, upper)
                if unmask
                else curve.mask_interval(lower, upper)
            )

        self._apply_mask(operation)

    def _apply_mask(self, operation: Callable[[Curve, bool], Any]) -> None:
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
        self._push_change(self.tr("Edit mask"), lambda: restore(after), lambda: restore(before))

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
        if centre_parameter and centre_parameter.link:
            self._linked_notice(centre_parameter.link)
            return
        if area_parameter and area_parameter.link:
            self._linked_notice(area_parameter.link)
            return
        changes: list[tuple[Any, float, float]] = []
        if centre_parameter:
            if centre_parameter.fixed and not control:
                self._fixed_notice()
            else:
                new_centre = min(max(centre, centre_parameter.minimum), centre_parameter.maximum)
                changes.append((centre_parameter, centre_parameter.value, new_centre))
        if area_parameter:
            if area_parameter.fixed and not control:
                self._fixed_notice()
            else:
                try:
                    new_area = area_for_height(component, height, registry=self.registry)
                    new_area = min(max(new_area, area_parameter.minimum), area_parameter.maximum)
                    changes.append((area_parameter, area_parameter.value, new_area))
                except Exception as exc:
                    self._show_error(self.tr("Peak drag"), exc)
                    return
        if not changes:
            self.refresh_all()
            return
        self.undo_stack.beginMacro(self.tr("Drag peak"))
        for parameter, old, new in changes:
            self.undo_stack.push(
                CallbackCommand(
                    self.tr("Drag peak parameter"),
                    lambda parameter=parameter, new=new: setattr(parameter, "value", new),
                    lambda parameter=parameter, old=old: setattr(parameter, "value", old),
                )
            )
        self.undo_stack.endMacro()
        self._after_edit()

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
            if parameter.link:
                self._linked_notice(parameter.link)
                return
            if parameter.fixed and not control:
                self._fixed_notice()
                return
            changes.append((parameter, parameter.value, min(max(value, parameter.minimum), parameter.maximum)))
        self.undo_stack.beginMacro(self.tr("Drag peak width"))
        for parameter, old, new in changes:
            self.undo_stack.push(
                CallbackCommand(
                    self.tr("Change width"),
                    lambda parameter=parameter, new=new: setattr(parameter, "value", new),
                    lambda parameter=parameter, old=old: setattr(parameter, "value", old),
                )
            )
        self.undo_stack.endMacro()
        self._after_edit()

    def drag_spline_node(
        self, component_id: str, node: int, value: float, control: bool
    ) -> None:
        if not self.active_curve_id:
            return
        component = self.project.model_for(self.active_curve_id).component(component_id)
        parameter = component.parameters.get(f"y{node}")
        if parameter is None:
            return
        if parameter.link:
            self._linked_notice(parameter.link)
            return
        if parameter.fixed and not control:
            self._fixed_notice()
            self.refresh_all()
            return
        value = min(max(value, parameter.minimum), parameter.maximum)
        old = parameter.value
        self._push_change(
            self.tr("Drag spline node"),
            lambda: setattr(parameter, "value", value),
            lambda: setattr(parameter, "value", old),
        )

    def apply_calculator(self, request: dict[str, Any]) -> None:
        targets = self._calculator_targets(request.get("scope", 0))
        if not targets:
            return
        if request.get("restore"):
            before = {curve.id: (copy.deepcopy(curve.transformations), copy.deepcopy(curve.redo_transformations)) for curve in targets}

            def restore(values: dict[str, Any]) -> None:
                for curve in targets:
                    curve.transformations, curve.redo_transformations = copy.deepcopy(values[curve.id])
                    curve._recompute()

            for curve in targets:
                curve.restore_original()
            after = {curve.id: (copy.deepcopy(curve.transformations), copy.deepcopy(curve.redo_transformations)) for curve in targets}
            restore(before)
            self._push_change(self.tr("Restore original data"), lambda: restore(after), lambda: restore(before))
            return
        operation = request["operation"]
        try:
            transformations = []
            operand = (
                self.project.dataset.curve(request["operand_curve_id"])
                if str(operation).startswith("curve_")
                else None
            )
            for curve in targets:
                if operand is not None:
                    transformations.append(
                        (
                            curve,
                            apply_curve_operation(
                                curve,
                                operand,
                                operation,
                                interpolation=request["interpolation"],
                                extrapolate=request["extrapolate"],
                            ),
                        )
                    )
                else:
                    transformations.append((curve, apply_scalar(curve, operation, request.get("value"))))
            for curve, _ in transformations:
                curve.undo_transformation()

            def redo() -> None:
                for curve, transformation in transformations:
                    if curve.redo_transformations and curve.redo_transformations[-1] is transformation:
                        curve.redo_transformation()
                    elif transformation not in curve.transformations:
                        curve.apply_transformation(transformation)

            def undo() -> None:
                for curve, transformation in reversed(transformations):
                    if curve.transformations and curve.transformations[-1] is transformation:
                        curve.undo_transformation()

            self._push_change(self.tr("Data calculation"), redo, undo)
        except Exception as exc:
            self._show_error(self.tr("Data Calculator"), exc)

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

    def reset_layout(self) -> None:
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.series_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.model_dock)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.series_dock.show()
        self.model_dock.show()
        for dock in (
            self.log_dock,
            self.worksheet_dock,
            self.diagnostics_dock,
            self.calculator_dock,
            self.function_dock,
            self.uncertainty_dock,
        ):
            if dock not in (self.series_dock, self.model_dock):
                dock.hide()
        self.resize(1440, 900)

    def _automatic_update_check(self) -> None:
        self.check_for_updates(force=False)

    def check_for_updates(self, *, force: bool = False) -> None:
        if self._update_reply is not None:
            if force:
                self._notify(self.tr("An update check is already in progress."))
            return
        now = time.time()
        try:
            last_check = float(self.settings.value("updates/last_check", 0.0) or 0.0)
        except (TypeError, ValueError):
            last_check = 0.0
        if not force and now - last_check < 24 * 60 * 60:
            return

        # Record the attempt so repeated launches while offline do not hammer GitHub.
        self.settings.setValue("updates/last_check", now)
        request = QNetworkRequest(
            QUrl("https://api.github.com/repos/SebRoLENS/curvemole/releases/latest")
        )
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", f"CurveMole/{__version__}".encode("ascii"))
        request.setTransferTimeout(10_000)
        reply = self._update_manager.get(request)
        self._update_reply = reply
        reply.finished.connect(
            lambda reply=reply, force=force: self._update_check_finished(reply, force)
        )

    def _update_check_finished(self, reply: Any, force: bool) -> None:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                message = self.tr("Could not check for CurveMole updates: ") + reply.errorString()
                self._log(message)
                if force:
                    QMessageBox.warning(self, self.tr("Check for updates"), message)
                return

            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            current = _semantic_version(__version__)
            latest = _semantic_version(str(payload.get("tag_name", "")))
            if current is None or latest is None:
                raise ValueError(self.tr("GitHub returned an unrecognised release version."))

            latest_text = ".".join(str(value) for value in latest)
            if latest <= current:
                self.settings.remove("updates/last_notified_version")
                self.settings.remove("updates/last_notified_at")
                if force:
                    QMessageBox.information(
                        self,
                        self.tr("Check for updates"),
                        self.tr("CurveMole is up to date. Installed version: ") + __version__,
                    )
                return

            now = time.time()
            previous_version = str(
                self.settings.value("updates/last_notified_version", "") or ""
            )
            try:
                previous_at = float(
                    self.settings.value("updates/last_notified_at", 0.0) or 0.0
                )
            except (TypeError, ValueError):
                previous_at = 0.0

            due = _update_notification_due(
                latest_text,
                previous_version,
                previous_at,
                now,
            )
            if not force and not due:
                return

            reminder = not force and previous_version == latest_text
            release_url = str(
                payload.get("html_url")
                or "https://github.com/SebRoLENS/curvemole/releases"
            )
            self._show_update_available(
                latest_text,
                _update_kind(current, latest),
                release_url,
                reminder=reminder,
            )
            self.settings.setValue("updates/last_notified_version", latest_text)
            self.settings.setValue("updates/last_notified_at", now)
        except Exception as exc:
            self._log(f"Update check failed: {exc}")
            if force:
                QMessageBox.warning(self, self.tr("Check for updates"), str(exc))
        finally:
            self._update_reply = None
            reply.deleteLater()

    def _show_update_available(
        self,
        latest: str,
        kind: str,
        release_url: str,
        *,
        reminder: bool,
    ) -> None:
        if kind == "patch":
            description = self.tr(
                "A maintenance update is available with patches that correct bugs."
            )
        elif kind == "minor":
            description = self.tr(
                "A feature update is available and contains new functionality."
            )
        else:
            description = self.tr("A new major version of CurveMole is available.")

        prefix = self.tr("Reminder: ") if reminder else ""
        message = (
            prefix
            + self.tr("CurveMole ")
            + latest
            + self.tr(" is available. ")
            + description
            + "\n\n"
            + self.tr(
                "Keeping CurveMole up to date is strongly recommended so that you receive "
                "the latest bug fixes, reliability improvements, and compatibility updates."
            )
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(self.tr("CurveMole update available"))
        box.setText(message)
        open_button = box.addButton(
            self.tr("Open release page"), QMessageBox.ButtonRole.AcceptRole
        )
        box.addButton(self.tr("Later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_button:
            self._open_external(release_url)

    def open_documentation(self, name: str) -> None:
        source_tree = Path(__file__).resolve().parents[3] / "docs" / name
        if source_tree.exists():
            self._open_external(source_tree)
            return
        packaged = _resource_path(f"docs/{name}")
        if packaged and packaged.exists():
            self._open_external(packaged)
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

    def show_about(self) -> None:
        AboutDialog(_resource_path("curvemole.png"), self).exec()

    def show_plugin_manager(self) -> None:
        trusted = set(self.project.ui_state.get("trusted_plugins", []))
        manager = PluginManager(self.registry, trusted_identifiers=trusted)
        directory = self.project.ui_state.get("plugin_directory", "")
        dialog = PluginManagerDialog(manager, directory, self)
        dialog.exec()
        if dialog.directory.text().strip() != directory or dialog.loaded_identifiers:
            self.project.ui_state["plugin_directory"] = dialog.directory.text().strip()
            self.project.ui_state["trusted_plugins"] = sorted(manager.trusted_identifiers)
            if not self.project.read_only:
                self.project.touch()
            self._notify(self.tr("Plugin registry updated."))

    def _set_active_curve(self, curve_id: str | None) -> None:
        if curve_id != self.active_curve_id:
            self.plot_workspace.cancel_placement()
        self.active_curve_id = curve_id
        self.selected_component_id = None
        self.refresh_all()

    def _selection_changed(self) -> None:
        selected = self.curve_tree.selected_curve_ids()
        self.model_panel.set_context(
            self.project,
            self.active_curve_id,
            len(selected),
            self.selected_component_id,
        )
        self.plot_workspace.set_context(
            self.project,
            self.active_curve_id,
            selected,
            self.selected_component_id,
        )

    def remove_selected_curves(self) -> None:
        if not self._ensure_editable():
            return
        selected = self.curve_tree.selected_curve_ids()
        if not selected and self.active_curve_id:
            selected = {self.active_curve_id}
        if not selected:
            self._notify(self.tr("Select at least one curve to remove."), warning=True)
            return
        count = len(selected)
        question = (
            self.tr("Remove the selected curve? This action can be undone.")
            if count == 1
            else self.tr("Remove the selected curves? This action can be undone.")
        )
        if QMessageBox.question(self, self.tr("Remove curve"), question) != QMessageBox.StandardButton.Yes:
            return

        records: list[tuple[str, Series, int, Curve, dict[str, Any] | None, bool, Any]] = []
        for curve_id in selected:
            series = self.project.dataset.series_for(curve_id)
            curve = self.project.dataset.curve(curve_id)
            index = series.curves.index(curve)
            model = self.project.models.get(curve_id)
            model_state = model.to_dict() if model is not None else None
            had_result = curve_id in self.project.results
            result_value = copy.deepcopy(self.project.results.get(curve_id))
            records.append((curve_id, series, index, curve, model_state, had_result, result_value))
        active_before = self.active_curve_id

        def redo() -> None:
            existing_ids = {curve.id for curve in self.project.curves}
            for curve_id, *_ in records:
                if curve_id in existing_ids:
                    self.project.remove_curve(curve_id)
            if self.active_curve_id in selected:
                self.active_curve_id = self.project.curves[0].id if self.project.curves else None
            self.selected_component_id = None

        def undo() -> None:
            for curve_id, series, index, curve, model_state, had_result, result_value in sorted(
                records, key=lambda item: item[2]
            ):
                if all(existing.id != curve_id for existing in series.curves):
                    series.add(curve, index)
                if model_state is not None:
                    self.project.models[curve_id] = Model.from_dict(copy.deepcopy(model_state))
                if had_result:
                    self.project.results[curve_id] = copy.deepcopy(result_value)
            self.active_curve_id = active_before if active_before else (self.project.curves[0].id if self.project.curves else None)
            self.selected_component_id = None

        self._push_change(
            self.tr("Remove curve") if count == 1 else self.tr("Remove curves"),
            redo,
            undo,
        )

    def _set_curve_colour(self, curve_id: str, colour: str) -> None:
        curve = self.project.dataset.curve(curve_id)
        curve.colour = colour.upper()
        self.project.touch()
        self.refresh_all()

    def choose_curve_colour(self, curve_id: str) -> None:
        if not self._ensure_editable():
            return
        curve = self.project.dataset.curve(curve_id)
        while True:
            selected = QColorDialog.getColor(
                QColor(curve.colour),
                self,
                self.tr("Choose spectrum colour"),
            )
            if not selected.isValid():
                return
            colour = selected.name(QColor.NameFormat.HexRgb).upper()
            if spectrum_colour_allowed(colour):
                break
            QMessageBox.warning(
                self,
                self.tr("Reserved colour"),
                self.tr(
                    "Red is reserved for the Model sum so spectra and fitted-model curves can never use the same colour. Choose another spectrum colour."
                ),
            )
        old = curve.colour.upper()
        if colour == old:
            return
        self.undo_stack.push(
            CallbackCommand(
                self.tr("Change spectrum colour"),
                lambda: self._set_curve_colour(curve_id, colour),
                lambda: self._set_curve_colour(curve_id, old),
            )
        )

    def apply_series_palette(self, series_id: str, palette_name: str) -> None:
        if not self._ensure_editable():
            return
        palette = SERIES_PALETTES.get(palette_name)
        if not palette:
            return
        series = next((item for item in self.project.dataset.series if item.id == series_id), None)
        if series is None:
            return
        before_colours = [curve.colour for curve in series.curves]
        before_palette = series.metadata.get("palette")
        after_colours = [palette[index % len(palette)] for index in range(len(series.curves))]

        def restore(colours: list[str], marker: Any) -> None:
            for curve, colour in zip(series.curves, colours, strict=True):
                curve.colour = colour.upper()
            if marker is None:
                series.metadata.pop("palette", None)
            else:
                series.metadata["palette"] = marker
            self.project.touch()
            self.refresh_all()

        self.undo_stack.push(
            CallbackCommand(
                self.tr("Change series palette"),
                lambda: restore(after_colours, palette_name),
                lambda: restore(before_colours, before_palette),
            )
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
        self, snapshot: list[tuple[Series, str, dict[str, Any], list[str]]]
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
        self.project.touch()
        self.refresh_all()

    def _push_series_layout_change(self, text: str, operation: Callable[[], None]) -> None:
        if not self._ensure_editable():
            return
        before = self._series_layout_snapshot()
        operation()
        after = self._series_layout_snapshot()
        self._restore_series_layout(before)
        self.undo_stack.push(
            CallbackCommand(
                text,
                lambda: self._restore_series_layout(after),
                lambda: self._restore_series_layout(before),
            )
        )

    def create_series(self) -> None:
        if not self._ensure_editable():
            return
        default_name = self.tr("Series ") + str(len(self.project.dataset.series) + 1)
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
                Series(name, metadata={"palette": DEFAULT_SERIES_PALETTE})
            )

        self._push_series_layout_change(self.tr("Create series"), operation)

    def move_curves_to_series(self, curve_ids: object, target_series_id: str) -> None:
        if not self._ensure_editable():
            return
        requested = [str(value) for value in list(curve_ids)]
        if not requested:
            return
        target = next(
            (series for series in self.project.dataset.series if series.id == target_series_id), None
        )
        if target is None:
            return
        order = {curve.id: index for index, curve in enumerate(self.project.curves)}
        requested = sorted(set(requested), key=lambda curve_id: order.get(curve_id, 10**9))

        def operation() -> None:
            moved: list[Curve] = []
            for curve_id in requested:
                try:
                    source = self.project.dataset.series_for(curve_id)
                except KeyError:
                    continue
                if source.id == target_series_id:
                    continue
                moved.append(source.remove(curve_id))
            for curve in moved:
                target.add(curve)

        before = self._series_layout_snapshot()
        operation()
        after = self._series_layout_snapshot()
        self._restore_series_layout(before)
        if after == before:
            return
        self.undo_stack.push(
            CallbackCommand(
                self.tr("Move spectra to series"),
                lambda: self._restore_series_layout(after),
                lambda: self._restore_series_layout(before),
            )
        )

    def merge_series(self, source_series_id: str, target_series_id: str) -> None:
        if not self._ensure_editable() or source_series_id == target_series_id:
            return
        source = next(
            (series for series in self.project.dataset.series if series.id == source_series_id), None
        )
        target = next(
            (series for series in self.project.dataset.series if series.id == target_series_id), None
        )
        if source is None or target is None:
            return

        def operation() -> None:
            while source.curves:
                target.add(source.remove(source.curves[0].id))
            self.project.dataset.series = [
                series for series in self.project.dataset.series if series.id != source_series_id
            ]

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

        before = self._series_layout_snapshot()
        operation()
        after = self._series_layout_snapshot()
        self._restore_series_layout(before)
        if after == before:
            return
        self.undo_stack.push(
            CallbackCommand(
                self.tr("Reorder spectra"),
                lambda: self._restore_series_layout(after),
                lambda: self._restore_series_layout(before),
            )
        )

    def _rename_series(self, series_id: str, name: str) -> None:
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

    def _set_component(self, component_id: str) -> None:
        self.selected_component_id = component_id
        self.model_panel.refresh(component_id)
        self.plot_workspace.set_context(
            self.project,
            self.active_curve_id,
            self.curve_tree.selected_curve_ids(),
            component_id,
        )

    def _model_mutation(self, text: str, operation: Callable[[Model], Any]) -> None:
        if not self.active_curve_id:
            return
        model = self.project.model_for(self.active_curve_id)
        before = model.to_dict()
        operation(model)
        after = model.to_dict()
        self.project.models[self.active_curve_id] = Model.from_dict(before)
        self._push_model_state(self.active_curve_id, before, after, text)

    def _push_model_state(
        self,
        curve_id: str,
        before: dict[str, Any],
        after: dict[str, Any],
        text: str,
    ) -> None:
        self._push_change(
            text,
            lambda: self.project.models.__setitem__(curve_id, Model.from_dict(copy.deepcopy(after))),
            lambda: self.project.models.__setitem__(curve_id, Model.from_dict(copy.deepcopy(before))),
        )

    def _push_change(self, text: str, redo: Callable[[], None], undo: Callable[[], None]) -> None:
        if not self._ensure_editable():
            return

        def wrapped(operation: Callable[[], None]) -> None:
            operation()
            self._after_edit()

        self.undo_stack.push(CallbackCommand(text, lambda: wrapped(redo), lambda: wrapped(undo)))

    def _after_edit(self) -> None:
        try:
            self.project.touch()
        except PermissionError as exc:
            self._show_error(self.tr("Read-only project"), exc)
        for curve_id in self.curve_tree.selected_curve_ids() or ({self.active_curve_id} if self.active_curve_id else set()):
            try:
                curve = self.project.dataset.curve(curve_id)
            except KeyError:
                continue
            if curve.state == CurveState.FITTED:
                curve.state = CurveState.MODIFIED
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
        operation: Callable[[Callable[[float | None, str], None]], Any],
        finished: Callable[[Any], None],
        status: str,
    ) -> None:
        if self._thread is not None:
            self._notify(self.tr("Another task is already running."), warning=True)
            return
        self._thread = QThread(self)
        self._worker = Worker(operation)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._task_progress)
        self._worker.finished.connect(finished)
        self._worker.finished.connect(self._task_done)
        self._worker.failed.connect(self._task_failed)
        self._worker.failed.connect(self._task_done)
        self._thread.finished.connect(self._thread.deleteLater)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_action.setEnabled(True)
        self.fit_action.setEnabled(False)
        self._notify(status)
        self._thread.start()

    def _task_progress(self, value: float | None, text: str) -> None:
        if value is None:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(round(value * 100))
        self.statusBar().showMessage(text)

    def _task_failed(self, message: str, details: str) -> None:
        self._log(details)
        if "cancelled" in message.lower():
            self._notify(self.tr("Task cancelled; the previous valid result was retained."), warning=True)
        else:
            self._show_error(self.tr("Task failed"), RuntimeError(message))
        self.refresh_all()

    def _task_done(self, *_: Any) -> None:
        if self._thread:
            self._thread.quit()
        self._thread = None
        self._worker = None
        self._cancellation = None
        self.progress.setVisible(False)
        self.cancel_action.setEnabled(False)
        self.fit_action.setEnabled(True)

    def _mask_targets(self) -> list[Curve]:
        if not self.active_curve_id:
            return []
        mode = self.plot_workspace.mask_target.currentIndex()
        if mode == 0:
            ids = {self.active_curve_id}
        elif mode == 1:
            ids = self.curve_tree.selected_curve_ids() or {self.active_curve_id}
        else:
            ids = {curve.id for curve in self.project.curves if curve.visible}
        return [curve for curve in self.project.curves if curve.id in ids]

    def _calculator_targets(self, scope: int) -> list[Curve]:
        if not self.active_curve_id:
            return []
        if scope == 0:
            return [self.project.dataset.curve(self.active_curve_id)]
        if scope == 1:
            ids = self.curve_tree.selected_curve_ids() or {self.active_curve_id}
            return [curve for curve in self.project.curves if curve.id in ids]
        series = self.project.dataset.series_for(self.active_curve_id)
        return list(series.curves)

    def _mask_tolerance(self) -> float:
        return float(self.project.ui_state.get("mask_transfer_tolerance", 0.0))

    def _last_fit_result(self) -> FitResult | None:
        value = self.project.results.get("last_fit")
        return value if isinstance(value, FitResult) else None

    def _refresh_diagnostics(self) -> None:
        result = self._last_fit_result()
        output = result.curve_outputs.get(self.active_curve_id) if result and self.active_curve_id else None
        self.diagnostics.set_residual(output.residual if output else None)

    def refresh_worksheet(self) -> None:
        if not self.worksheet_dock.isVisible():
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

    def _load_custom_functions(self) -> None:
        for value in self.project.custom_functions:
            try:
                definition = formula_definition(
                    value["identifier"],
                    value.get("display_name", value["identifier"]),
                    value["formula"],
                    kind=value.get("kind", "generic"),
                    defaults=value.get("defaults"),
                    bounds={key: tuple(bounds) for key, bounds in value.get("bounds", {}).items()},
                    derived_formulas=value.get("derived_formulas", {}),
                )
                self.registry.register(definition, replace=True)
            except Exception as exc:
                self._log(f"Custom function skipped: {exc}")

    def _autosave(self) -> None:
        try:
            path = self.recovery.autosave(self.project)
            if path:
                self._log(f"Recovery saved: {path.name}")
        except Exception as exc:
            self._log(f"Autosave failed: {exc}")

    def _confirm_discard_or_save(self) -> bool:
        if not self.project.dirty:
            return True
        answer = QMessageBox.question(
            self,
            self.tr("Unsaved changes"),
            self.tr("Save changes to the current project?"),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return True

    def _ensure_editable(self) -> bool:
        if not self.project.read_only:
            return True
        QMessageBox.information(
            self,
            self.tr("Read-only project"),
            self.tr("This project is locked by another instance. Use Save As to create an editable copy."),
        )
        return False

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
        return f"{self.project.name}{marker}{mode} — CurveMole {__version__}"

    def _restore_layout(self) -> None:
        geometry = self.settings.value("geometry")
        state = self.settings.value("window_state")
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)
        self.apply_theme(str(self.settings.value("theme", "system")))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None:
            QMessageBox.warning(self, self.tr("Task running"), self.tr("Cancel the running task before quitting."))
            event.ignore()
            return
        if not self._confirm_discard_or_save():
            event.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("window_state", self.saveState())
        self._release_lock()
        event.accept()

    def _release_lock(self) -> None:
        if self._project_lock:
            self._project_lock.__exit__(None, None, None)
            self._project_lock = None

    def dragEnterEvent(self, event: Any) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: Any) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        projects = [path for path in paths if Path(path).suffix.lower() == ".fitproj"]
        data = [path for path in paths if Path(path).suffix.lower() in {".txt", ".dat", ".csv", ".tsv"}]
        if projects:
            self.open_project(projects[0])
        elif data:
            self.import_data(data)


def _semantic_version(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", value.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def _update_kind(current: tuple[int, int, int], latest: tuple[int, int, int]) -> str:
    if latest[0] != current[0]:
        return "major"
    if latest[1] != current[1]:
        return "minor"
    return "patch"


def _update_notification_due(
    latest: str,
    last_notified_version: str,
    last_notified_at: float,
    now: float,
) -> bool:
    if latest != last_notified_version:
        return True
    return now - last_notified_at >= 10 * 24 * 60 * 60


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
