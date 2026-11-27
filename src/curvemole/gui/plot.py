"""Fast interactive spectrum, residual, masking, and peak-handle canvas."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QRadioButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry
from curvemole.gui.plot_appearance import (
    colour_with_opacity,
    normalize_plot_appearance,
    plot_mode_flags,
    qt_pen_style,
)
from curvemole.gui.scientific_axis import ScientificAxisItem


class MaskViewBox(pg.ViewBox):
    def autoRange(self, padding=None, items=None, item=None):
        callback = getattr(self, "data_range_callback", None)
        if callback is not None:
            callback()
        else:
            super().autoRange(padding=padding, items=items, item=item)

    maskPointRequested = Signal(float)
    maskRangeRequested = Signal(float, float)
    unmaskPointRequested = Signal(float)
    unmaskRangeRequested = Signal(float, float)
    peakPlacementPreview = Signal(float, float, float)
    peakPlacementRequested = Signal(float, float, float)
    splinePointRequested = Signal(float, float)
    splinePointRemoveRequested = Signal(float, float)
    placementFinishRequested = Signal()

    def __init__(self) -> None:
        super().__init__(enableMenu=True)
        self.mask_mode = False
        self.interaction_mode: str | None = None
        self.plugin_marker_callback = lambda scene_position: False
        self.quick_add_placement = False
        self.placement_editor = None
        self._context_menu_event = None
        self._context_menu_timer = QTimer(self)
        self._context_menu_timer.setSingleShot(True)
        self._context_menu_timer.timeout.connect(self._show_pending_context_menu)

    def _show_pending_context_menu(self) -> None:
        event, self._context_menu_event = self._context_menu_event, None
        if event is not None and not self.mask_mode and self.interaction_mode is None:
            self.raiseContextMenu(event)

    def mouseClickEvent(self, event: Any) -> None:
        if self.interaction_mode == 'plugin_points' and event.button() == Qt.MouseButton.LeftButton:
            self.plugin_session.pick(event.scenePos())
            event.accept()
            return
        if (self.interaction_mode is None and not self.mask_mode
                and event.button() == Qt.MouseButton.LeftButton
                and self.plugin_marker_callback(event.scenePos())):
            event.accept()
            return
        if self.interaction_mode == "data_points" and event.button() == Qt.MouseButton.LeftButton:
            self.point_editor.select_at(event.scenePos())
            event.accept()
            return
        if (
            self.quick_add_placement
            and self.interaction_mode is not None
            and event.button() == Qt.MouseButton.RightButton
        ):
            self.placementFinishRequested.emit()
            event.accept()
            return
        if self.interaction_mode == "peak" and event.button() == Qt.MouseButton.LeftButton:
            point = self.mapSceneToView(event.scenePos())
            self.peakPlacementRequested.emit(float(point.x()), float(point.y()), 0.0)
            event.accept()
            return
        if self.interaction_mode == "spline":
            if event.button() == Qt.MouseButton.LeftButton:
                if self.placement_editor is not None and self.placement_editor.click_at(event.scenePos()):
                    event.accept()
                    return
                if event.double():
                    self.placementFinishRequested.emit()
                    event.accept()
                    return
                point = self.mapSceneToView(event.scenePos())
                self.splinePointRequested.emit(float(point.x()), float(point.y()))
                event.accept()
                return
            if event.button() == Qt.MouseButton.RightButton:
                point = self.mapSceneToView(event.scenePos())
                self.splinePointRemoveRequested.emit(float(point.x()), float(point.y()))
                event.accept()
                return
        if self.mask_mode and event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            point = self.mapSceneToView(event.scenePos())
            signal = self.unmaskPointRequested if event.button() == Qt.MouseButton.LeftButton else self.maskPointRequested
            signal.emit(float(point.x()))
            event.accept()
            return
        if self.interaction_mode is None and event.double():
            self._context_menu_timer.stop()
            self._context_menu_event = None
            callback = None
            if event.button() == Qt.MouseButton.LeftButton:
                callback = getattr(self, "unmasked_range_callback", None)
            elif event.button() == Qt.MouseButton.RightButton:
                callback = getattr(self, "data_range_callback", None)
            if callback is not None:
                callback()
                event.accept()
                return
        if (
            self.interaction_mode is None
            and event.button() == Qt.MouseButton.RightButton
            and self.menuEnabled()
        ):
            # Wait for a possible second click before opening a popup that would
            # otherwise steal the right double-click from the spectrum.
            event.accept()
            self._context_menu_event = event
            self._context_menu_timer.start(QApplication.doubleClickInterval())
            return
        super().mouseClickEvent(event)

    def mouseDragEvent(self, event: Any, axis: int | None = None) -> None:
        if self.interaction_mode == 'plugin_points' and event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        if self.interaction_mode == "data_points" and event.button() == Qt.MouseButton.LeftButton:
            if event.isStart():
                self.point_editor.begin_drag(event.buttonDownScenePos())
            if event.isFinish():
                self.point_editor.end_drag(event.scenePos())
            else:
                self.point_editor.update_drag(event.scenePos())
            event.accept()
            return
        if self.interaction_mode == "peak" and event.button() == Qt.MouseButton.LeftButton:
            start = self.mapSceneToView(event.buttonDownScenePos())
            end = self.mapSceneToView(event.scenePos())
            width = 2 * abs(float(end.x() - start.x()))
            self.peakPlacementPreview.emit(float(start.x()), float(start.y()), width)
            if event.isFinish():
                self.peakPlacementRequested.emit(float(start.x()), float(start.y()), width)
            event.accept()
            return
        if self.interaction_mode == "spline" and event.button() == Qt.MouseButton.LeftButton:
            if self.placement_editor is not None and self.placement_editor.drag(event):
                event.accept()
                return
            # Empty-space drags keep normal ViewBox panning in every point mode.
            super().mouseDragEvent(event, axis=axis)
            return
        if self.mask_mode and self.interaction_mode is None and event.button() == Qt.MouseButton.RightButton:
            if event.isFinish():
                start = self.mapSceneToView(event.buttonDownScenePos())
                end = self.mapSceneToView(event.scenePos())
                if not math.isclose(float(start.x()), float(end.x())):
                    self.maskRangeRequested.emit(float(start.x()), float(end.x()))
            event.accept()
            return
        if self.mask_mode and event.button() == Qt.MouseButton.LeftButton:
            if event.isFinish():
                start = self.mapSceneToView(event.buttonDownScenePos())
                end = self.mapSceneToView(event.scenePos())
                if abs(end.x() - start.x()) > 0:
                    self.unmaskRangeRequested.emit(float(start.x()), float(end.x()))
            event.accept()
            return
        if self.mask_mode and self.interaction_mode is None:
            event.ignore()
            return
        if self.interaction_mode in {None, "data_points", "plugin_points"} and event.button() == Qt.MouseButton.RightButton:
            self._context_menu_timer.stop()
            self._context_menu_event = None
            event.accept()
            # Use the same ViewBox-local coordinates as pyqtgraph's pan handler,
            # preserving inversion, logarithmic axes and per-axis view locking.
            delta = self.mapToView(event.lastPos()) - self.mapToView(event.pos())
            enabled = self.state["mouseEnabled"]
            x = float(delta.x()) if enabled[0] and axis != 1 else None
            y = float(delta.y()) if enabled[1] and axis != 0 else None
            self._resetTarget()
            if x is not None or y is not None:
                self.translateBy(x=x, y=y)
            self.sigRangeChangedManually.emit(enabled)
            return
        super().mouseDragEvent(event, axis=axis)


from curvemole.gui.plot_scene import _label_offset  # noqa: E402,F401 - historical import path


class PlotWorkspace(QWidget):
    maskPointRequested = Signal(float)
    maskRangeRequested = Signal(float, float)
    unmaskPointRequested = Signal(float)
    unmaskRangeRequested = Signal(float, float)
    peakDragged = Signal(str, float, float, bool)
    widthDragged = Signal(str, float, bool)
    splineNodeDragged = Signal(str, int, float, bool)
    componentSelected = Signal(str)
    componentOnCurveSelected = Signal(str, str)
    peakPlacementFinished = Signal(float, float, float)
    splinePlacementFinished = Signal(object)
    placementCancelled = Signal()

    def __init__(self, registry: FunctionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from curvemole.gui.plot_placement import PlacementController
        from curvemole.gui.plot_scene import SceneRenderer
        from curvemole.gui.plot_view_state import ViewState

        self.placement = PlacementController(self)
        self.scene = SceneRenderer(self)
        self.view_state = ViewState(self)
        self.registry = registry
        self._project: Project | None = None
        self._active_curve_id: str | None = None
        self._selected_curve_ids: set[str] = set()
        self._selected_component_id: str | None = None
        self._data_items: dict[str, pg.PlotDataItem] = {}
        self._render_items: dict[tuple, tuple[pg.PlotItem, pg.PlotDataItem]] = {}
        self._error_items: dict[str, pg.PlotDataItem] = {}
        self._component_items: dict[tuple[str, str], pg.PlotDataItem] = {}
        self._sum_items: dict[str, pg.PlotDataItem] = {}
        self._component_labels: list[pg.TextItem] = []
        self._component_labels_by_key: dict[tuple[str, str], pg.TextItem] = {}
        self._component_label_specs: list[tuple[pg.TextItem, float, float]] = []
        self._show_component_labels = True
        self._laying_out_labels = False
        self._handles: list[Any] = []
        self._updating_handles = False
        self._view_locked = False
        self._placement_mode: str | None = None
        self._quick_add_placement = False
        self._peak_preview: tuple[float, float, float] | None = None
        self._spline_points: list[tuple[float, float]] = []
        self._placement_items: list[Any] = []
        self._placement_mouse_targets: dict[Any, tuple[Qt.MouseButtons, bool]] = {}
        self._placement_name = ""
        self._plot_appearance = normalize_plot_appearance(None)

        self.view_controls = QFrame(self)
        self.view_controls.setObjectName("viewControls")
        self.view_controls.setFrameShape(QFrame.Shape.StyledPanel)
        self.view_controls.setStyleSheet(
            "QFrame#viewControls {"
            " background-color: palette(alternate-base);"
            " border: 1px solid palette(mid);"
            " border-radius: 7px;"
            "}"
        )
        view_layout = QVBoxLayout(self.view_controls)
        view_layout.setContentsMargins(8, 6, 8, 6)
        view_layout.setSpacing(4)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(QLabel(self.tr("Display:")))
        self.display_mode = QComboBox()
        self.display_mode.addItems([self.tr("Single"), self.tr("Overlay"), self.tr("Waterfall")])
        self.display_mode.currentIndexChanged.connect(self.refresh)
        controls.addWidget(self.display_mode)
        self._active_series_id: str | None = None
        self.scope_project = QRadioButton(self.tr("All series"))
        self.scope_series = QRadioButton(self.tr("Active series"))
        self.scope_selected = QRadioButton(self.tr("Selected"))
        self.scope_selected.setToolTip(self.tr("Overlay / Waterfall: selected visible spectra (Shift-click for a range, Ctrl-click individually)"))
        self.scope_project.setToolTip(self.tr("Overlay / Waterfall: all visible spectra in the project"))
        self.scope_series.setToolTip(self.tr("Overlay / Waterfall: visible spectra in the active series only"))
        self.scope_group = QButtonGroup(self)
        for button in (self.scope_project, self.scope_series, self.scope_selected):
            self.scope_group.addButton(button)
            controls.addWidget(button)
            button.setEnabled(False)
        self.scope_selected.setChecked(True)
        self.scope_group.buttonToggled.connect(lambda button, checked: self._scope_changed() if checked else None)
        self.display_mode.currentIndexChanged.connect(self._scope_enabled)
        controls.addStretch(1)
        view_layout.addLayout(controls)

        autoscale_controls = QHBoxLayout()
        autoscale_controls.setContentsMargins(0, 0, 0, 0)
        self.autoscale_toggle = QCheckBox(self.tr("Autoscale"))
        self.autoscale_toggle.setToolTip(
            self.tr("Automatically fit experimental data when you select a spectrum or click a series.")
        )
        autoscale_controls.addWidget(self.autoscale_toggle)
        self.autoscale_mode = QComboBox()
        self.autoscale_mode.addItems([self.tr("All points"), self.tr("Unmasked points")])
        self.autoscale_mode.setToolTip(
            self.tr("All points includes masked points; Unmasked points fits only non-masked points.")
        )
        self.autoscale_mode.setEnabled(False)
        autoscale_controls.addWidget(self.autoscale_mode)
        autoscale_controls.addStretch(1)
        self.autoscale_toggle.toggled.connect(self._autoscale_settings_changed)
        self.autoscale_mode.currentIndexChanged.connect(self._autoscale_settings_changed)
        view_layout.addLayout(autoscale_controls)

        function_controls = QHBoxLayout()
        function_controls.setContentsMargins(0, 0, 0, 0)
        function_controls.addWidget(QLabel(self.tr("Functions:")))
        self.function_style_mode = QComboBox()
        self.function_style_mode.addItem(self.tr("Lines"), "lines")
        self.function_style_mode.addItem(self.tr("Points"), "points")
        self.function_style_mode.addItem(
            self.tr("Lines + points"), "lines_points"
        )
        self.function_style_mode.setToolTip(
            self.tr("Choose how fitted/model functions are drawn in the plot.")
        )
        self.function_style_mode.currentIndexChanged.connect(
            self._function_style_changed
        )
        function_controls.addWidget(self.function_style_mode)
        function_controls.addStretch(1)
        view_layout.addLayout(function_controls)

        offset_controls = QHBoxLayout()
        offset_controls.setContentsMargins(0, 0, 0, 0)
        offset_controls.addWidget(QLabel(self.tr("X offset:")))
        self.x_offset = _offset_spin()
        offset_controls.addWidget(self.x_offset)
        offset_controls.addWidget(QLabel(self.tr("Y offset:")))
        self.y_offset = _offset_spin()
        offset_controls.addWidget(self.y_offset)
        self.x_offset.valueChanged.connect(self.refresh)
        self.y_offset.valueChanged.connect(self.refresh)
        self.mask_toggle = QToolButton(self)
        self.mask_toggle.hide()
        self.mask_toggle.setText(self.tr("Mask"))
        self.mask_toggle.setCheckable(True)
        self.mask_toggle.setToolTip(
            self.tr("Mask mode: right-drag to mask, left-drag to unmask. Use the mouse wheel to zoom. Click again to leave mask mode.")
        )
        self.mask_toggle.toggled.connect(self._set_mask_mode)
        self.mask_action = QAction(self.tr("Mask"), self, checkable=True)
        self.mask_action.setToolTip(self.mask_toggle.toolTip())
        self.mask_action.toggled.connect(self.mask_toggle.setChecked)
        self.mask_toggle.toggled.connect(lambda *_: self.mask_action.setChecked(self.mask_toggle.isChecked()))
        self._mask_scope = "active"
        self.display_mode.currentIndexChanged.connect(lambda *_: self.mask_toggle.setChecked(False))
        self.residual_toggle = QCheckBox(self.tr("Residuals"))
        self.residual_toggle.setChecked(True)
        offset_controls.addWidget(self.residual_toggle)
        self.error_bars_toggle = QCheckBox(self.tr("Error bars"))
        self.error_bars_toggle.setChecked(True)
        self.error_bars_toggle.setToolTip(self.tr(
            "Show imported Y confidence intervals or 1-sigma uncertainties. "
            "Changing visibility does not change fit weighting."))
        self.error_bars_toggle.toggled.connect(self._error_bars_changed)
        offset_controls.addWidget(self.error_bars_toggle)
        offset_controls.addStretch(1)
        self.coordinate_label = QLabel("x: —   y: —")
        self.coordinate_label.setMinimumWidth(210)
        offset_controls.addWidget(self.coordinate_label)
        view_layout.addLayout(offset_controls)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view_controls)
        self.placement_bar = QWidget()
        placement_bar_layout = QVBoxLayout(self.placement_bar)
        placement_bar_layout.setContentsMargins(8, 4, 8, 4)
        placement_bar_layout.setSpacing(3)
        self.placement_label = QLabel()
        self.placement_label.setWordWrap(True)
        placement_bar_layout.addWidget(self.placement_label)
        # Instructions need the full plot width. Beside all the buttons, a
        # wrapped label can consume the entire canvas height on Windows/high DPI.
        placement_layout = QHBoxLayout()
        placement_bar_layout.addLayout(placement_layout)
        placement_layout.addStretch(1)
        self.undo_point_button = QToolButton()
        self.undo_point_button.setText(self.tr("Undo point"))
        self.undo_point_button.setToolTip(self.tr("Undo the last point addition, deletion or move."))
        self.undo_point_button.clicked.connect(lambda: self.undo_spline_point())
        placement_layout.addWidget(self.undo_point_button)
        self.finish_placement_button = QToolButton()
        self.finish_placement_button.setText(self.tr("Finish"))
        self.finish_placement_button.clicked.connect(lambda: self.finish_placement())
        placement_layout.addWidget(self.finish_placement_button)
        self.cancel_placement_button = QToolButton()
        self.cancel_placement_button.setText(self.tr("Cancel"))
        self.cancel_placement_button.clicked.connect(lambda: self.cancel_placement())
        placement_layout.addWidget(self.cancel_placement_button)
        self.placement_bar.setStyleSheet(
            "QWidget { background:#e8f5f2; color:#123; border-bottom:1px solid #79b8ad; }"
        )
        self.placement_bar.hide()
        layout.addWidget(self.placement_bar)
        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.view_box = MaskViewBox()
        self.view_box.data_range_callback = self.auto_range
        self.view_box.unmasked_range_callback = self.view_active
        self.plot = self.graphics.addPlot(
            row=0, col=0, viewBox=self.view_box,
            axisItems={side: ScientificAxisItem(side) for side in ("bottom", "left")},
        )
        self.plot.autoBtn.clicked.disconnect()
        self.plot.autoBtn.clicked.connect(lambda: self.auto_range())
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        view_menu = self.view_box.getMenu(None)
        self.view_active_action = QAction(self.tr("View unmasked"), self)
        self.view_active_action.setToolTip(self.tr("View unmasked\nFrame only unmasked experimental data."))
        self.view_active_action.triggered.connect(self.view_active)
        view_menu.insertAction(view_menu.actions()[1], self.view_active_action)
        view_menu.addSeparator()
        self.component_labels_action = QAction(self.tr("Show component labels"), self)
        self.component_labels_action.setCheckable(True)
        self.component_labels_action.setChecked(True)
        self.component_labels_action.toggled.connect(self.set_component_labels_visible)
        view_menu.addAction(self.component_labels_action)
        self.residual_plot = self.graphics.addPlot(
            row=1, col=0,
            axisItems={side: ScientificAxisItem(side) for side in ("bottom", "left")},
        )
        self.residual_plot.setXLink(self.plot)
        # Residual Y follows the residuals of the visible X range until the user
        # zooms or pans the residual axis by hand (View all resets that choice).
        self._residual_view_manual = False
        residual_box = self.residual_plot.getViewBox()
        residual_box.setAutoVisible(y=True)
        residual_box.sigRangeChangedManually.connect(self._residual_range_changed_manually)
        self.residual_plot.setMaximumHeight(190)
        self.residual_plot.showGrid(x=True, y=True, alpha=0.15)
        self.residual_plot.setLabel("left", self.tr("Residual"))
        layout.addWidget(self.graphics)
        self.view_box.maskPointRequested.connect(self.maskPointRequested)
        self.view_box.maskRangeRequested.connect(self.maskRangeRequested)
        self.view_box.unmaskPointRequested.connect(self.unmaskPointRequested)
        self.view_box.unmaskRangeRequested.connect(self.unmaskRangeRequested)
        self.view_box.peakPlacementPreview.connect(self._preview_peak_placement)
        self.view_box.peakPlacementRequested.connect(self._finish_peak_placement)
        self.view_box.splinePointRequested.connect(self._add_spline_point)
        self.view_box.splinePointRemoveRequested.connect(self._remove_spline_point)
        self.view_box.placementFinishRequested.connect(self.finish_placement)
        self.view_box.sigRangeChanged.connect(self._layout_component_labels)
        self.residual_toggle.toggled.connect(self.residual_plot.setVisible)
        self._mouse_proxy = pg.SignalProxy(
            self.graphics.scene().sigMouseMoved,
            rateLimit=40,
            slot=self._mouse_moved,
        )
        self._cancel_shortcut = QShortcut(QKeySequence("Esc"), self)
        self._cancel_shortcut.activated.connect(self.cancel_placement)
        self._quick_add_return = QShortcut(QKeySequence("Return"), self)
        self._quick_add_enter = QShortcut(QKeySequence("Enter"), self)
        for shortcut in (self._quick_add_return, self._quick_add_enter):
            shortcut.setEnabled(False)
            shortcut.activated.connect(lambda: self.finish_placement())
        from curvemole.gui.data_point_editor import DataPointEditor
        self.point_editor = DataPointEditor(self)
        from curvemole.gui.point_placement_editor import PointPlacementEditor
        self.placement_editor = PointPlacementEditor(self, placement_layout)
        self.view_box.placement_editor = self.placement_editor
        layout.insertWidget(layout.indexOf(self.graphics), self.point_editor)
        self._plugin_plot_sessions = {}
        self.view_box.plugin_marker_callback = self._plugin_marker_clicked

    def _plugin_marker_clicked(self, scene_position):
        for session in reversed(list(self._plugin_plot_sessions.values())):
            marker = session.marker_at(scene_position)
            if marker is not None:
                session.markerClicked.emit(marker)
                return True
        return False

    def plot_appearance(self) -> dict[str, Any]:
        return dict(self._plot_appearance)

    def set_plot_appearance(self, settings: dict[str, Any]) -> None:
        self._plot_appearance = normalize_plot_appearance(settings)
        if self._project is not None:
            self._project.ui_state["plot_appearance"] = dict(self._plot_appearance)
        self._sync_function_style_control()
        self._apply_grid_appearance()
        self.refresh()

    def _apply_grid_appearance(self) -> None:
        visible = bool(self._plot_appearance.get("grid_visible", True))
        alpha = float(self._plot_appearance.get("grid_opacity", 15)) / 100.0
        self.plot.showGrid(x=visible, y=visible, alpha=alpha)
        self.residual_plot.showGrid(x=visible, y=visible, alpha=alpha)

    @staticmethod
    def _plot_options(
        mode: str,
        colour: str | QColor,
        width: float,
        line_style: str,
        opacity: int,
        point_size: float,
        symbol: str,
    ) -> dict[str, Any]:
        draw_lines, draw_points = plot_mode_flags(mode)
        rendered_colour = colour_with_opacity(colour, opacity)
        options: dict[str, Any] = {
            "symbol": None,
            "pen": (
                pg.mkPen(
                    rendered_colour,
                    width=width,
                    style=qt_pen_style(line_style),
                )
                if draw_lines
                else None
            )
        }
        if draw_points:
            options.update(
                symbol=symbol,
                symbolSize=point_size,
                symbolBrush=pg.mkBrush(rendered_colour),
                symbolPen=None,
            )
        return options

    def set_context(
        self,
        project: Project,
        active_curve_id: str | None,
        selected_curve_ids: set[str] | None = None,
        selected_component_id: str | None = None,
    ) -> None:
        project_changed = project is not self._project
        active_curve_changed = active_curve_id != self._active_curve_id
        if project_changed or active_curve_changed:
            for session in list(self._plugin_plot_sessions.values()):
                session._invalidate()
            self.point_editor.finish()
        self._project = project
        self._active_curve_id = active_curve_id
        if project is not None:
            project.ui_state.setdefault("display_scope", "selected")
            if project_changed:
                self.error_bars_toggle.blockSignals(True)
                self.error_bars_toggle.setChecked(bool(project.ui_state.get("show_error_bars", True)))
                self.error_bars_toggle.blockSignals(False)
                self.autoscale_toggle.blockSignals(True)
                self.autoscale_mode.blockSignals(True)
                self.autoscale_toggle.setChecked(bool(project.ui_state.get("autoscale_enabled", False)))
                self.autoscale_mode.setCurrentIndex(
                    1 if project.ui_state.get("autoscale_mode") == "active" else 0
                )
                self.autoscale_mode.setEnabled(self.autoscale_toggle.isChecked())
                self.autoscale_mode.blockSignals(False)
                self.autoscale_toggle.blockSignals(False)
                self._plot_appearance = normalize_plot_appearance(
                    project.ui_state.get("plot_appearance")
                )
                self._sync_function_style_control()
                self._apply_grid_appearance()
            if active_curve_id:
                self._active_series_id = project.dataset.series_for(active_curve_id).id
            elif self._active_series_id not in {series.id for series in project.dataset.series}:
                self._active_series_id = project.dataset.series[0].id if project.dataset.series else None
            self.scope_group.blockSignals(True)
            target = {"project": self.scope_project, "series": self.scope_series, "selected": self.scope_selected}.get(project.ui_state.get("display_scope"), self.scope_selected)
            target.setChecked(True)
            self.scope_group.blockSignals(False)
        self._selected_curve_ids = (
            set(selected_curve_ids) if selected_curve_ids is not None
            else ({active_curve_id} if active_curve_id else set())
        )
        self._selected_component_id = selected_component_id
        self.refresh()
        if active_curve_changed and self.autoscale_toggle.isChecked():
            self._apply_autoscale()

    def _autoscale_settings_changed(self, *_: Any) -> None:
        return self.view_state._autoscale_settings_changed(*_)

    def _apply_autoscale(self, *, series_id: str | None = None) -> None:
        return self.view_state._apply_autoscale(series_id=series_id)

    def _scope_enabled(self, index: int) -> None:
        self.scope_project.setEnabled(index != 0)
        self.scope_series.setEnabled(index != 0)
        self.scope_selected.setEnabled(index != 0)

    def _scope_changed(self) -> None:
        if self._project is not None:
            self._project.ui_state["display_scope"] = "selected" if self.scope_selected.isChecked() else ("series" if self.scope_series.isChecked() else "project")
        self.mask_toggle.setChecked(False)
        self.refresh()
        self.auto_range()

    def displayed_curves(self) -> list:
        project = self._project
        if project is None:
            return []
        if self.display_mode.currentIndex() == 0:
            return [curve for curve in project.curves if curve.id == self._active_curve_id]
        curves = project.curves
        if self.scope_series.isChecked():
            series = next((item for item in project.dataset.series if item.id == self._active_series_id), None)
            curves = series.curves if series is not None else []
        return [curve for curve in curves if curve.visible and (not self.scope_selected.isChecked() or curve.id in self._selected_curve_ids)]

    def curve_for_display(self, curve):
        controller = getattr(self, "view_options_controller", None)
        return controller.curve(curve) if controller is not None else curve

    def display_replays(self, curve) -> bool:
        controller = getattr(self, "view_options_controller", None)
        return controller is not None and controller.replays(curve)

    def restore_data_view_for_editing(self):
        editor = getattr(self.window(), "_function_point_editor", None)
        if editor is not None and editor.active:
            return
        controller = getattr(self, "view_options_controller", None)
        if controller is not None:
            controller.restore_for_editing()

    def refresh(self, *args: Any) -> None:
        if not hasattr(self, "render_controller"):
            from curvemole.gui.render_controller import RenderController
            self.render_controller = RenderController(self)
        self.render_controller.refresh(*args)

    def _refresh_scene(self, *_: Any) -> None:
        return self.scene._refresh_scene(*_)

    def set_component_labels_visible(self, visible: bool) -> None:
        self._show_component_labels = bool(visible)
        if self.component_labels_action.isChecked() != self._show_component_labels:
            self.component_labels_action.blockSignals(True)
            self.component_labels_action.setChecked(self._show_component_labels)
            self.component_labels_action.blockSignals(False)
        self.refresh()

    def _add_component_label(self, name: str, x: np.ndarray, y: np.ndarray) -> pg.TextItem | None:
        return self.scene._add_component_label(name, x, y)

    def _layout_component_labels(self, *_: Any) -> None:
        return self.scene._layout_component_labels(*_)

    def _add_component_handles(
        self, curve: Any, model: Any, x_offset: float, y_offset: float
    ) -> None:
        return self.scene._add_component_handles(curve, model, x_offset, y_offset)

    def _emit_peak(self, component_id: str, position: QPointF, x_offset: float, y_offset: float) -> None:
        modifiers = bool(Qt.KeyboardModifier.ControlModifier & QApplication.keyboardModifiers())
        self.peakDragged.emit(
            component_id,
            float(position.x() - x_offset),
            float(position.y() - y_offset),
            modifiers,
        )

    def _emit_width(self, component_id: str, width: float) -> None:
        modifiers = bool(Qt.KeyboardModifier.ControlModifier & QApplication.keyboardModifiers())
        self.widthDragged.emit(component_id, width, modifiers)

    def _emit_spline_node(
        self,
        item: pg.TargetItem,
        component_id: str,
        node: int,
        fixed_x: float,
        y_offset: float,
    ) -> None:
        modifiers = bool(Qt.KeyboardModifier.ControlModifier & QApplication.keyboardModifiers())
        position = item.pos()
        if not math.isclose(float(position.x()), fixed_x):
            item.setPos(fixed_x, position.y())
        self.splineNodeDragged.emit(
            component_id,
            node,
            float(position.y() - y_offset),
            modifiers,
        )

    def begin_peak_placement(self, name: str) -> None:
        return self.placement.begin_peak_placement(name)

    def begin_spline_placement(self, name: str) -> None:
        return self.placement.begin_spline_placement(name)

    def mark_quick_add_placement(self) -> None:
        return self.placement.mark_quick_add_placement()

    def cancel_placement(self) -> None:
        return self.placement.cancel_placement()

    def finish_placement(self) -> None:
        return self.placement.finish_placement()

    def undo_spline_point(self) -> None:
        return self.placement.undo_spline_point()

    def _preview_peak_placement(self, x: float, y: float, fwhm: float) -> None:
        return self.placement._preview_peak_placement(x, y, fwhm)

    def _finish_peak_placement(self, x: float, y: float, fwhm: float) -> None:
        return self.placement._finish_peak_placement(x, y, fwhm)

    def _add_spline_point(self, x: float, y: float) -> None:
        return self.placement._add_spline_point(x, y)

    def _remove_spline_point(self, x: float, y: float) -> None:
        return self.placement._remove_spline_point(x, y)

    def _render_placement_preview(self) -> None:
        return self.placement._render_placement_preview()

    def _clear_placement_items(self) -> None:
        return self.placement._clear_placement_items()

    def _end_placement(self) -> None:
        return self.placement._end_placement()

    def _restore_placement_mouse_targets(self) -> None:
        return self.placement._restore_placement_mouse_targets()

    def _sync_placement_mouse_targets(self) -> None:
        return self.placement._sync_placement_mouse_targets()

    def _update_spline_instruction(self) -> None:
        return self.placement._update_spline_instruction()

    def _active_display_offsets(self) -> tuple[float, float]:
        return self.view_state._active_display_offsets()

    def _from_display_coordinates(self, x: float, y: float) -> tuple[float, float]:
        return self.view_state._from_display_coordinates(x, y)

    def _active_x_span(self) -> float:
        return self.view_state._active_x_span()

    def _active_y_span(self) -> float:
        return self.view_state._active_y_span()

    def _default_peak_width(self) -> float:
        return self.placement._default_peak_width()

    def _update_interaction_state(self) -> None:
        spline_navigation = self._placement_mode == "spline"
        interactive = self._placement_mode is not None
        # MaskViewBox handles mask clicks and drags. Keep its mouse axes
        # enabled so pyqtgraph can still zoom with the wheel.
        enabled = (spline_navigation or not interactive) and not self._view_locked
        self.plot.setMouseEnabled(x=enabled, y=enabled)

    def _set_mask_mode(self, enabled: bool) -> None:
        if enabled:
            self.restore_data_view_for_editing()
            if self._project is None or not self._active_curve_id:
                self.mask_toggle.setChecked(False)
                self.mask_action.setChecked(False)
                return
            self.cancel_placement()
            self._mask_scope = "active"
            if self.display_mode.currentIndex() != 0:
                visible_count = len(self.displayed_curves())
                if not visible_count:
                    self.mask_toggle.setChecked(False)
                    self.mask_action.setChecked(False)
                    return
                if visible_count == 1:
                    # Target the displayed curve, which need not be the active one.
                    self._mask_scope = "visible"
                else:
                    choices = [self.tr("Active spectrum only"), self.tr("All visible spectra")]
                    choice, accepted = QInputDialog.getItem(
                        self, self.tr("Mask scope"), self.tr("Apply mask edits to:"), choices, 1, False,
                    )
                    if not accepted:
                        self.mask_toggle.setChecked(False)
                        self.mask_action.setChecked(False)
                        return
                    self._mask_scope = "visible" if choice == choices[1] else "active"
        self.view_box.mask_mode = enabled
        self._update_interaction_state()
        self.graphics.setToolTip(self.mask_toggle.toolTip() if enabled else "")

    def set_log_x(self, enabled: bool) -> None:
        return self.view_state.set_log_x(enabled)

    def set_log_y(self, enabled: bool) -> None:
        return self.view_state.set_log_y(enabled)

    def set_reverse_x(self, enabled: bool) -> None:
        return self.view_state.set_reverse_x(enabled)

    def set_reverse_y(self, enabled: bool) -> None:
        return self.view_state.set_reverse_y(enabled)

    def set_view_locked(self, enabled: bool) -> None:
        return self.view_state.set_view_locked(enabled)

    def auto_range(self) -> None:
        return self.view_state.auto_range()

    def _error_bars_changed(self, *_: Any) -> None:
        if self._project is not None:
            self._project.ui_state["show_error_bars"] = self.error_bars_toggle.isChecked()
        self.refresh()
        if self.autoscale_toggle.isChecked():
            self._apply_autoscale()

    def view_active(self) -> None:
        return self.view_state.view_active()

    def _fit_experimental_data(self, *, active_only: bool, series_id: str | None = None) -> None:
        # Never use scene/item bounds: adaptive rendering clips those to the
        # current viewport, while model extrapolation can dwarf the actual data.
        return self.view_state._fit_experimental_data(active_only=active_only, series_id=series_id)

    def _residual_range_changed_manually(self, *_: Any) -> None:
        return self.view_state._residual_range_changed_manually(*_)

    def _mouse_moved(self, event: tuple[QPointF]) -> None:
        point = event[0]
        if not self.plot.sceneBoundingRect().contains(point):
            return
        mapped = self.view_box.mapSceneToView(point)
        text = f"x: {mapped.x():.8g}   y: {mapped.y():.8g}"
        if self._project is not None and self._active_curve_id:
            curve = self._project.dataset.curve(self._active_curve_id)
            finite = np.isfinite(curve.x) & np.isfinite(curve.y)
            if np.any(finite):
                indices = np.flatnonzero(finite)
                index = int(indices[np.argmin(np.abs(curve.x[finite] - mapped.x()))])
                text += f"   |   {curve.name}: ({curve.x[index]:.8g}, {curve.y[index]:.8g})"
        self.coordinate_label.setText(text)


def _offset_spin() -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setDecimals(6)
    spin.setRange(-1e12, 1e12)
    spin.setSingleStep(1.0)
    spin.setKeyboardTracking(False)
    spin.setMaximumWidth(110)
    return spin
