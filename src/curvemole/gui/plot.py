"""Fast interactive spectrum, residual, masking, and peak-handle canvas."""

from __future__ import annotations

import math
from contextlib import suppress
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.models import component_height
from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry


class MaskViewBox(pg.ViewBox):
    maskPointRequested = Signal(float)
    maskRangeRequested = Signal(float, float)
    peakPlacementPreview = Signal(float, float, float)
    peakPlacementRequested = Signal(float, float, float)
    splinePointRequested = Signal(float, float)
    splinePointRemoveRequested = Signal(float, float)
    placementFinishRequested = Signal()

    def __init__(self) -> None:
        super().__init__(enableMenu=True)
        self.mask_mode = False
        self.interaction_mode: str | None = None

    def mouseClickEvent(self, event: Any) -> None:
        if self.interaction_mode == "peak" and event.button() == Qt.MouseButton.LeftButton:
            point = self.mapSceneToView(event.scenePos())
            self.peakPlacementRequested.emit(float(point.x()), float(point.y()), 0.0)
            event.accept()
            return
        if self.interaction_mode == "spline":
            if event.button() == Qt.MouseButton.LeftButton:
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
        if self.mask_mode and event.button() == Qt.MouseButton.LeftButton:
            point = self.mapSceneToView(event.scenePos())
            self.maskPointRequested.emit(float(point.x()))
            event.accept()
            return
        super().mouseClickEvent(event)

    def mouseDragEvent(self, event: Any, axis: int | None = None) -> None:
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
            event.accept()
            return
        if self.interaction_mode is None and event.button() == Qt.MouseButton.RightButton:
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
                    self.maskRangeRequested.emit(float(start.x()), float(end.x()))
            event.accept()
            return
        super().mouseDragEvent(event, axis=axis)


class PlotWorkspace(QWidget):
    maskPointRequested = Signal(float)
    maskRangeRequested = Signal(float, float)
    peakDragged = Signal(str, float, float, bool)
    widthDragged = Signal(str, float, bool)
    splineNodeDragged = Signal(str, int, float, bool)
    componentSelected = Signal(str)
    peakPlacementFinished = Signal(float, float, float)
    splinePlacementFinished = Signal(object)
    placementCancelled = Signal()

    def __init__(self, registry: FunctionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.registry = registry
        self._project: Project | None = None
        self._active_curve_id: str | None = None
        self._selected_curve_ids: set[str] = set()
        self._selected_component_id: str | None = None
        self._data_items: dict[str, pg.PlotDataItem] = {}
        self._component_items: dict[str, pg.PlotDataItem] = {}
        self._handles: list[Any] = []
        self._updating_handles = False
        self._view_locked = False
        self._placement_mode: str | None = None
        self._peak_preview: tuple[float, float, float] | None = None
        self._spline_points: list[tuple[float, float]] = []
        self._placement_items: list[Any] = []
        self._placement_name = ""

        controls = QHBoxLayout()
        controls.setContentsMargins(4, 2, 4, 2)
        controls.addWidget(QLabel(self.tr("Display:")))
        self.display_mode = QComboBox()
        self.display_mode.addItems([self.tr("Single"), self.tr("Overlay"), self.tr("Waterfall")])
        self.display_mode.currentIndexChanged.connect(self.refresh)
        controls.addWidget(self.display_mode)
        controls.addWidget(QLabel(self.tr("X offset:")))
        self.x_offset = _offset_spin()
        controls.addWidget(self.x_offset)
        controls.addWidget(QLabel(self.tr("Y offset:")))
        self.y_offset = _offset_spin()
        controls.addWidget(self.y_offset)
        self.x_offset.valueChanged.connect(self.refresh)
        self.y_offset.valueChanged.connect(self.refresh)
        self.mask_toggle = QToolButton()
        self.mask_toggle.setText(self.tr("Mask"))
        self.mask_toggle.setCheckable(True)
        self.mask_toggle.setToolTip(
            self.tr("Click for point/range masking, or right-drag the graph to mask an interval directly.")
        )
        self.mask_toggle.toggled.connect(self._set_mask_mode)
        controls.addWidget(self.mask_toggle)
        self.mask_operation = QComboBox()
        self.mask_operation.addItem(self.tr("Mask"), "mask")
        self.mask_operation.addItem(self.tr("Unmask"), "unmask")
        controls.addWidget(self.mask_operation)
        controls.addWidget(QLabel(self.tr("Target:")))
        self.mask_target = QComboBox()
        self.mask_target.addItems([self.tr("Active"), self.tr("Selected"), self.tr("All visible")])
        controls.addWidget(self.mask_target)
        self.residual_toggle = QCheckBox(self.tr("Residuals"))
        self.residual_toggle.setChecked(True)
        controls.addWidget(self.residual_toggle)
        controls.addStretch(1)
        self.coordinate_label = QLabel("x: —   y: —")
        self.coordinate_label.setMinimumWidth(210)
        controls.addWidget(self.coordinate_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(controls)
        self.placement_bar = QWidget()
        placement_layout = QHBoxLayout(self.placement_bar)
        placement_layout.setContentsMargins(8, 4, 8, 4)
        self.placement_label = QLabel()
        self.placement_label.setWordWrap(True)
        placement_layout.addWidget(self.placement_label, 1)
        self.undo_point_button = QToolButton()
        self.undo_point_button.setText(self.tr("Undo point"))
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
        self.plot = self.graphics.addPlot(row=0, col=0, viewBox=self.view_box)
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.residual_plot = self.graphics.addPlot(row=1, col=0)
        self.residual_plot.setXLink(self.plot)
        self.residual_plot.setMaximumHeight(190)
        self.residual_plot.showGrid(x=True, y=True, alpha=0.15)
        self.residual_plot.setLabel("left", self.tr("Residual"))
        layout.addWidget(self.graphics)
        self.view_box.maskPointRequested.connect(self.maskPointRequested)
        self.view_box.maskRangeRequested.connect(self.maskRangeRequested)
        self.view_box.peakPlacementPreview.connect(self._preview_peak_placement)
        self.view_box.peakPlacementRequested.connect(self._finish_peak_placement)
        self.view_box.splinePointRequested.connect(self._add_spline_point)
        self.view_box.splinePointRemoveRequested.connect(self._remove_spline_point)
        self.view_box.placementFinishRequested.connect(self.finish_placement)
        self.residual_toggle.toggled.connect(self.residual_plot.setVisible)
        self._mouse_proxy = pg.SignalProxy(
            self.graphics.scene().sigMouseMoved,
            rateLimit=40,
            slot=self._mouse_moved,
        )
        self._cancel_shortcut = QShortcut(QKeySequence("Esc"), self)
        self._cancel_shortcut.activated.connect(self.cancel_placement)

    def set_context(
        self,
        project: Project,
        active_curve_id: str | None,
        selected_curve_ids: set[str] | None = None,
        selected_component_id: str | None = None,
    ) -> None:
        self._project = project
        self._active_curve_id = active_curve_id
        self._selected_curve_ids = set(selected_curve_ids or ())
        self._selected_component_id = selected_component_id
        self.refresh()

    def refresh(self, *_: Any) -> None:
        self.plot.clear()
        self.residual_plot.clear()
        self._data_items.clear()
        self._component_items.clear()
        self._handles.clear()
        self._placement_items.clear()
        project = self._project
        if project is None or not project.curves:
            self.plot.setTitle(self.tr("Import data to begin"))
            return
        mode = self.display_mode.currentText()
        if mode == self.tr("Single"):
            curves = [project.dataset.curve(self._active_curve_id)] if self._active_curve_id else []
        else:
            curves = [curve for curve in project.curves if curve.visible]
        x_step = self.x_offset.value() if mode == self.tr("Waterfall") else 0.0
        y_step = self.y_offset.value() if mode == self.tr("Waterfall") else 0.0
        global_values = project.resolved_parameter_values()
        for index, curve in enumerate(curves):
            x = curve.x + index * x_step
            y = curve.y + index * y_step
            unmasked = ~curve.effective_mask
            pen = pg.mkPen(curve.colour, width=1.35 if curve.id == self._active_curve_id else 1.0)
            item = self.plot.plot(x[unmasked], y[unmasked], pen=pen, name=curve.name)
            item.curve_id = curve.id
            self._data_items[curve.id] = item
            masked = curve.effective_mask & np.isfinite(x) & np.isfinite(y)
            if np.any(masked):
                faded = QColor(curve.colour)
                faded.setAlpha(75)
                self.plot.plot(
                    x[masked],
                    y[masked],
                    pen=None,
                    symbol="o",
                    symbolSize=5,
                    symbolBrush=pg.mkBrush(faded),
                    symbolPen=None,
                )
            for mask in curve.masks.values():
                for lower, upper in mask.ranges:
                    if math.isclose(lower, upper):
                        continue
                    region = pg.LinearRegionItem(
                        values=(lower + index * x_step, upper + index * x_step),
                        movable=False,
                        brush=pg.mkBrush(120, 120, 120, 38),
                        pen=pg.mkPen(120, 120, 120, 70),
                    )
                    region.setZValue(-20)
                    self.plot.addItem(region)
            model = project.models.get(curve.id)
            if model and model.components:
                total, component_arrays = model.evaluate(
                    curve.x,
                    curve_id=curve.id,
                    values=global_values,
                    registry=self.registry,
                    components=True,
                )
                total = total + index * y_step
                self.plot.plot(x, total, pen=pg.mkPen("#D55E00", width=2.1), name=f"{curve.name} fit")
                residual = curve.y - (total - index * y_step)
                self.residual_plot.plot(x[unmasked], residual[unmasked], pen=pg.mkPen(curve.colour, width=1))
                for component in model.components:
                    if not component.enabled or component.id not in component_arrays:
                        continue
                    component_y = component_arrays[component.id] + index * y_step
                    selected = component.id == self._selected_component_id and curve.id == self._active_curve_id
                    component_item = self.plot.plot(
                        x,
                        component_y,
                        pen=pg.mkPen("#CC79A7" if selected else "#777777", width=1.7 if selected else 0.8, style=Qt.PenStyle.DashLine),
                    )
                    component_item.component_id = component.id
                    component_item.curve_id = curve.id
                    component_item.curve.setClickable(True, width=8)
                    component_item.sigClicked.connect(
                        lambda item, event, component_id=component.id: self.componentSelected.emit(
                            component_id
                        )
                    )
                    self._component_items[component.id] = component_item
                if curve.id == self._active_curve_id and self._selected_component_id:
                    self._add_component_handles(curve, model, index * x_step, index * y_step)
        if curves:
            first = curves[0]
            self.plot.setLabel("bottom", first.x_label, units=first.x_unit or None)
            self.plot.setLabel("left", first.y_label, units=first.y_unit or None)
            self.residual_plot.setLabel("bottom", first.x_label, units=first.x_unit or None)
        self._render_placement_preview()
        self.plot.setTitle("")

    def _add_component_handles(
        self, curve: Any, model: Any, x_offset: float, y_offset: float
    ) -> None:
        try:
            component = model.component(self._selected_component_id)
        except KeyError:
            return
        definition = self.registry.get(component.function_id)
        if component.function_id == "cubic_spline":
            for index, x_node in enumerate(component.metadata.get("x_nodes", [])):
                parameter = component.parameters.get(f"y{index}")
                if parameter is None:
                    continue
                target = pg.TargetItem(
                    pos=(float(x_node) + x_offset, parameter.value + y_offset),
                    size=10,
                    movable=True,
                    pen=pg.mkPen("#009E73", width=2),
                    brush=pg.mkBrush(255, 255, 255, 180),
                )
                target.setToolTip(
                    self.tr("Drag spline y node. Its x position remains fixed by default.")
                )
                self.plot.addItem(target)
                target.sigPositionChangeFinished.connect(
                    lambda item, component_id=component.id, node=index, xo=float(x_node)
                    + x_offset, yo=y_offset: self._emit_spline_node(
                        item, component_id, node, xo, yo
                    )
                )
                self._handles.append(target)
            return
        if definition.kind != "peak" or "center" not in component.parameters:
            return
        height = component_height(component, registry=self.registry)
        if height is None:
            return
        centre = component.parameters["center"].value
        target = pg.TargetItem(
            pos=(centre + x_offset, height + y_offset),
            size=12,
            movable=True,
            pen=pg.mkPen("#009E73", width=2),
            brush=pg.mkBrush(255, 255, 255, 180),
        )
        target.setToolTip(self.tr("Drag peak centre/height. Hold Ctrl to change a fixed value."))
        self.plot.addItem(target)
        target.sigPositionChangeFinished.connect(
            lambda item: self._emit_peak(component.id, item.pos(), x_offset, y_offset)
        )
        self._handles.append(target)
        derived = definition.derived_values(
            {name: parameter.value for name, parameter in component.parameters.items()}, component.metadata
        )
        fwhm = derived.get("FWHM")
        if fwhm and fwhm > 0:
            for side in (-1, 1):
                line = pg.InfiniteLine(
                    pos=centre + x_offset + side * fwhm / 2,
                    angle=90,
                    movable=True,
                    pen=pg.mkPen("#009E73", width=1.2),
                    hoverPen=pg.mkPen("#E69F00", width=2),
                )
                line.setToolTip(self.tr("Drag to change FWHM. Hold Ctrl for a fixed width."))
                self.plot.addItem(line)
                line.sigPositionChangeFinished.connect(
                    lambda item, component_id=component.id, c=centre + x_offset: self._emit_width(
                        component_id, 2 * abs(float(item.value()) - c)
                    )
                )
                self._handles.append(line)

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
        self.cancel_placement()
        self._placement_mode = "peak"
        self._placement_name = name
        self._peak_preview = None
        self.view_box.interaction_mode = "peak"
        self.mask_toggle.setChecked(False)
        self.mask_toggle.setEnabled(False)
        self.undo_point_button.hide()
        self.finish_placement_button.hide()
        self.placement_label.setText(
            self.tr("Place ")
            + name
            + self.tr(": click the peak centre, drag horizontally to either half-height edge, and release. Esc cancels.")
        )
        self.placement_bar.show()
        self.graphics.setCursor(Qt.CursorShape.CrossCursor)
        self._update_interaction_state()

    def begin_spline_placement(self, name: str) -> None:
        self.cancel_placement()
        self._placement_mode = "spline"
        self._placement_name = name
        self._spline_points = []
        self.view_box.interaction_mode = "spline"
        self.mask_toggle.setChecked(False)
        self.mask_toggle.setEnabled(False)
        self.undo_point_button.show()
        self.finish_placement_button.show()
        self.undo_point_button.setEnabled(False)
        self.finish_placement_button.setEnabled(False)
        self._update_spline_instruction()
        self.placement_bar.show()
        self.graphics.setCursor(Qt.CursorShape.CrossCursor)
        self._update_interaction_state()

    def cancel_placement(self) -> None:
        if self._placement_mode is None:
            return
        self._end_placement()
        self.placementCancelled.emit()

    def finish_placement(self) -> None:
        if self._placement_mode != "spline":
            return
        if len(self._spline_points) < 2:
            self._update_spline_instruction()
            return
        points = sorted(self._spline_points)
        self._end_placement()
        self.splinePlacementFinished.emit(points)

    def undo_spline_point(self) -> None:
        if self._placement_mode != "spline" or not self._spline_points:
            return
        self._spline_points.pop()
        self._render_placement_preview()
        self._update_spline_instruction()

    def _preview_peak_placement(self, x: float, y: float, fwhm: float) -> None:
        if self._placement_mode != "peak":
            return
        x, y = self._from_display_coordinates(x, y)
        self._peak_preview = (x, y, fwhm)
        self._render_placement_preview()

    def _finish_peak_placement(self, x: float, y: float, fwhm: float) -> None:
        if self._placement_mode != "peak":
            return
        x, y = self._from_display_coordinates(x, y)
        selected_width = fwhm if fwhm > 0 else self._default_peak_width()
        self._end_placement()
        self.peakPlacementFinished.emit(x, y, selected_width)

    def _add_spline_point(self, x: float, y: float) -> None:
        if self._placement_mode != "spline":
            return
        x, y = self._from_display_coordinates(x, y)
        if not math.isfinite(x) or not math.isfinite(y):
            return
        tolerance = max(self._active_x_span(), 1.0) * 1e-12
        for index, (existing_x, _) in enumerate(self._spline_points):
            if math.isclose(x, existing_x, rel_tol=0.0, abs_tol=tolerance):
                self._spline_points[index] = (x, y)
                break
        else:
            self._spline_points.append((x, y))
        self._render_placement_preview()
        self._update_spline_instruction()

    def _remove_spline_point(self, x: float, y: float) -> None:
        if self._placement_mode != "spline" or not self._spline_points:
            return
        x, y = self._from_display_coordinates(x, y)
        x_scale = max(self._active_x_span(), np.finfo(float).eps)
        y_scale = max(self._active_y_span(), np.finfo(float).eps)
        index = min(
            range(len(self._spline_points)),
            key=lambda item: (
                ((self._spline_points[item][0] - x) / x_scale) ** 2
                + ((self._spline_points[item][1] - y) / y_scale) ** 2
            ),
        )
        self._spline_points.pop(index)
        self._render_placement_preview()
        self._update_spline_instruction()

    def _render_placement_preview(self) -> None:
        self._clear_placement_items()
        if self._placement_mode is None or self._project is None or not self._active_curve_id:
            return
        x_offset, y_offset = self._active_display_offsets()
        if self._placement_mode == "peak" and self._peak_preview is not None:
            centre, height, fwhm = self._peak_preview
            width = fwhm if fwhm > 0 else self._default_peak_width()
            region = pg.LinearRegionItem(
                values=(centre + x_offset - width / 2, centre + x_offset + width / 2),
                movable=False,
                brush=pg.mkBrush(0, 158, 115, 38),
                pen=pg.mkPen(0, 158, 115, 130),
            )
            centre_line = pg.InfiniteLine(
                pos=centre + x_offset,
                angle=90,
                movable=False,
                pen=pg.mkPen("#009E73", width=2),
            )
            marker = self.plot.plot(
                [centre + x_offset],
                [height + y_offset],
                pen=None,
                symbol="+",
                symbolSize=14,
                symbolPen=pg.mkPen("#009E73", width=2),
            )
            for item in (region, centre_line):
                self.plot.addItem(item)
            self._placement_items.extend([region, centre_line, marker])
            return
        if self._placement_mode != "spline" or not self._spline_points:
            return
        ordered = sorted(self._spline_points)
        node_x = np.asarray([point[0] for point in ordered], dtype=float)
        node_y = np.asarray([point[1] for point in ordered], dtype=float)
        markers = self.plot.plot(
            node_x + x_offset,
            node_y + y_offset,
            pen=None,
            symbol="o",
            symbolSize=9,
            symbolBrush=pg.mkBrush("#009E73"),
            symbolPen=pg.mkPen("#ffffff", width=1),
        )
        self._placement_items.append(markers)
        if len(ordered) < 2:
            return
        curve = self._project.dataset.curve(self._active_curve_id)
        finite = np.isfinite(curve.x)
        if not np.any(finite):
            return
        metadata = {"x_nodes": node_x.tolist()}
        values = {f"y{index}": value for index, value in enumerate(node_y)}
        preview = self.registry.get("cubic_spline").evaluate(curve.x[finite], values, metadata)
        line = self.plot.plot(
            curve.x[finite] + x_offset,
            preview + y_offset,
            pen=pg.mkPen("#009E73", width=2, style=Qt.PenStyle.DashLine),
        )
        self._placement_items.append(line)

    def _clear_placement_items(self) -> None:
        for item in self._placement_items:
            with suppress(RuntimeError):
                self.plot.removeItem(item)
        self._placement_items.clear()

    def _end_placement(self) -> None:
        self._clear_placement_items()
        self._placement_mode = None
        self._placement_name = ""
        self._peak_preview = None
        self._spline_points = []
        self.view_box.interaction_mode = None
        self.placement_bar.hide()
        self.mask_toggle.setEnabled(True)
        self.graphics.unsetCursor()
        self._update_interaction_state()

    def _update_spline_instruction(self) -> None:
        count = len(self._spline_points)
        self.placement_label.setText(
            self.tr(
                "Place spline background nodes: left-click adds a point, right-click removes the nearest point, "
                "and a left double-click accepts the spline. The curve updates live. "
            )
            + f"{count} "
            + self.tr("point(s). Add at least two, then double-click or press Finish. Esc cancels.")
        )
        self.undo_point_button.setEnabled(count > 0)
        self.finish_placement_button.setEnabled(count >= 2)

    def _active_display_offsets(self) -> tuple[float, float]:
        if self.display_mode.currentText() != self.tr("Waterfall") or self._project is None:
            return 0.0, 0.0
        curves = [curve for curve in self._project.curves if curve.visible]
        index = next(
            (position for position, curve in enumerate(curves) if curve.id == self._active_curve_id),
            0,
        )
        return index * self.x_offset.value(), index * self.y_offset.value()

    def _from_display_coordinates(self, x: float, y: float) -> tuple[float, float]:
        x_offset, y_offset = self._active_display_offsets()
        return x - x_offset, y - y_offset

    def _active_x_span(self) -> float:
        if self._project is None or not self._active_curve_id:
            return 0.0
        curve = self._project.dataset.curve(self._active_curve_id)
        finite = curve.x[np.isfinite(curve.x)]
        return float(np.ptp(finite)) if len(finite) else 0.0

    def _active_y_span(self) -> float:
        if self._project is None or not self._active_curve_id:
            return 0.0
        curve = self._project.dataset.curve(self._active_curve_id)
        finite = curve.y[np.isfinite(curve.y)]
        return float(np.ptp(finite)) if len(finite) else 0.0

    def _default_peak_width(self) -> float:
        if self._project is None or not self._active_curve_id:
            return 1.0
        curve = self._project.dataset.curve(self._active_curve_id)
        finite = np.sort(curve.x[np.isfinite(curve.x)])
        spacing = float(np.nanmedian(np.abs(np.diff(finite)))) if len(finite) > 1 else 0.0
        return max(self._active_x_span() * 0.05, spacing * 4, np.finfo(float).eps)

    def _update_interaction_state(self) -> None:
        interactive = self._placement_mode is not None
        enabled = not interactive and not self._view_locked and not self.view_box.mask_mode
        self.plot.setMouseEnabled(x=enabled, y=enabled)

    def _set_mask_mode(self, enabled: bool) -> None:
        self.view_box.mask_mode = enabled
        self._update_interaction_state()
        self.mask_toggle.setText(self.tr("Masking…") if enabled else self.tr("Mask"))

    def set_log_x(self, enabled: bool) -> None:
        self.plot.setLogMode(x=enabled, y=None)
        self.residual_plot.setLogMode(x=enabled, y=False)

    def set_log_y(self, enabled: bool) -> None:
        self.plot.setLogMode(x=None, y=enabled)

    def set_reverse_x(self, enabled: bool) -> None:
        self.view_box.invertX(enabled)

    def set_reverse_y(self, enabled: bool) -> None:
        self.view_box.invertY(enabled)

    def set_view_locked(self, enabled: bool) -> None:
        self._view_locked = enabled
        self._update_interaction_state()

    def auto_range(self) -> None:
        self.plot.enableAutoRange()
        self.residual_plot.enableAutoRange()

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
