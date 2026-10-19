"""Select, preview and commit individual experimental points on the plot."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from curvemole.gui.plot import PlotWorkspace


class DataPointEditor(QWidget):
    activeChanged = Signal(bool)
    moveRequested = Signal(str, int, float, float)
    deleteRequested = Signal(str, int)

    def __init__(self, workspace: PlotWorkspace):
        super().__init__(workspace)
        self.workspace = workspace
        self.active = False
        self.selected_row: int | None = None
        self._marker = None
        self._points = None
        self._drag = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr("Edit data points")))
        row.addWidget(QLabel(self.tr("Move:")))
        self.axes = QComboBox()
        for label, value in (("X", "x"), ("Y", "y"), ("XY", "xy")):
            self.axes.addItem(label, value)
        self.axes.setCurrentIndex(2)
        self.axes.setToolTip(self.tr("Constrain changes to X, Y or both data coordinates."))
        self.axes.currentIndexChanged.connect(self.cancel_drag)
        row.addWidget(self.axes)
        self.coordinates = QLabel()
        self.coordinates.setWordWrap(True)
        row.addStretch(1)
        self.delete_button = QPushButton(self.tr("Delete selected point"))
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self.delete_selected)
        row.addWidget(self.delete_button)
        self.done_button = QPushButton(self.tr("Done"))
        self.done_button.clicked.connect(self.finish)
        row.addWidget(self.done_button)
        layout.addLayout(row)
        layout.addWidget(self.coordinates)
        self.instructions = QLabel(self.tr(
            "Click a data point to select it; drag to move it. Delete removes the selected point. "
            "Right-drag pans, the wheel zooms, and Esc ends editing. Changes support Undo/Redo."))
        self.instructions.setWordWrap(True)
        layout.addWidget(self.instructions)
        self._delete_shortcuts = []
        for key in ("Delete", "Backspace"):
            shortcut = QShortcut(QKeySequence(key), workspace)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.setEnabled(False)
            shortcut.activated.connect(self.delete_selected)
            self._delete_shortcuts.append(shortcut)
        workspace.view_box.point_editor = self
        self.hide()

    def _curve(self):
        workspace = self.workspace
        if workspace._project is None or workspace._active_curve_id is None:
            return None
        try:
            return workspace._project.dataset.curve(workspace._active_curve_id)
        except KeyError:
            return None

    def begin(self) -> bool:
        workspace = self.workspace
        curve = self._curve()
        if (curve is None or workspace._project.read_only
                or not any(item.id == curve.id for item in workspace.displayed_curves())):
            return False
        workspace.cancel_placement()
        workspace.mask_toggle.setChecked(False)
        workspace.view_box._context_menu_timer.stop()
        workspace.view_box._context_menu_event = None
        self.active = True
        self.selected_row = None
        workspace.view_box.interaction_mode = "data_points"
        workspace.mask_toggle.setEnabled(False)
        workspace.mask_action.setEnabled(False)
        workspace.graphics.setFocus(Qt.FocusReason.OtherFocusReason)
        workspace.graphics.setCursor(Qt.CursorShape.CrossCursor)
        for shortcut in self._delete_shortcuts:
            shortcut.setEnabled(True)
        self.show()
        workspace._update_interaction_state()
        workspace.refresh()
        self.activeChanged.emit(True)
        return True

    def finish(self):
        if not self.active:
            return
        self.active = False
        self._drag = None
        self.selected_row = None
        self.workspace.view_box.interaction_mode = None
        self.workspace.mask_toggle.setEnabled(True)
        self.workspace.mask_action.setEnabled(True)
        self.workspace.graphics.unsetCursor()
        for shortcut in self._delete_shortcuts:
            shortcut.setEnabled(False)
        self.hide()
        self.workspace._update_interaction_state()
        self.workspace.refresh()
        self.activeChanged.emit(False)

    def _selected_index(self):
        curve = self._curve()
        if curve is None or self.selected_row is None:
            return None
        indices = np.flatnonzero(curve.row_indices == self.selected_row)
        return int(indices[0]) if len(indices) else None

    def refresh(self):
        # A plot refresh replaces its items and cancels uncommitted previews.
        self._marker = None
        self._points = None
        self._drag = None
        if not self.active:
            return
        curve = self._curve()
        if (curve is None or self.workspace._project.read_only
                or not any(item.id == curve.id for item in self.workspace.displayed_curves())):
            self.finish()
            return
        keep = ~curve.effective_mask
        item = self.workspace._data_items.get(curve.id)
        if item is not None:
            # The editor owns the sample markers during previews, including
            # when the normal renderer splits dense lines and symbols.
            item.setSymbol(None)
        x_offset, y_offset = self.workspace._active_display_offsets()
        self._points = pg.PlotDataItem(
            curve.x[keep] + x_offset,
            (curve.y - self._background(curve.x))[keep] + y_offset,
            pen=None, symbol="o", symbolSize=5, symbolPen=None, symbolBrush=pg.mkBrush(curve.colour))
        self._points.setZValue(5)
        self._points.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.workspace.plot.addItem(self._points)
        self._update_selection()

    def _background(self, x):
        workspace = self.workspace
        if not getattr(workspace, "_background_subtracted_view", False):
            return np.zeros_like(x, dtype=float)
        curve = self._curve()
        model = workspace._project.models.get(curve.id)
        if model is None or not any(component.enabled and component.is_background for component in model.components):
            return np.zeros_like(x, dtype=float)
        try:
            result = np.asarray(model.background(
                np.asarray(x), curve_id=curve.id,
                values=workspace._project.resolved_parameter_values(), registry=workspace.registry), dtype=float)
        except Exception:
            # Match the normal plot: an unavailable model must not hide data.
            return np.zeros_like(x, dtype=float)
        if result.shape != np.shape(x):
            return np.zeros_like(x, dtype=float)
        return np.where(np.isfinite(result), result, 0.0)

    def display_coordinates(self, x, y):
        x_offset, y_offset = self.workspace._active_display_offsets()
        xx = np.asarray(x, dtype=float) + x_offset
        yy = np.asarray(y, dtype=float) - self._background(np.asarray(x)) + y_offset
        with np.errstate(divide="ignore", invalid="ignore"):
            if self.workspace.plot.ctrl.logXCheck.isChecked():
                xx = np.log10(xx)
            if self.workspace.plot.ctrl.logYCheck.isChecked():
                yy = np.log10(yy)
        return xx, yy

    def nearest_index(self, scene_position):
        curve = self._curve()
        if curve is None:
            return None
        x, y = self.display_coordinates(curve.x, curve.y)
        position = self.workspace.view_box.mapSceneToView(scene_position)
        pixel_x, pixel_y = self.workspace.view_box.viewPixelSize()
        if not pixel_x or not pixel_y:
            return None
        distances = ((x - position.x()) / pixel_x) ** 2 + ((y - position.y()) / pixel_y) ** 2
        distances[~np.isfinite(distances)] = np.inf
        if not len(distances):
            return None
        index = int(np.argmin(distances))
        return index if distances[index] <= 12**2 else None

    def select_at(self, scene_position):
        index = self.nearest_index(scene_position)
        curve = self._curve()
        self.selected_row = int(curve.row_indices[index]) if index is not None else None
        self._update_selection()
        self.workspace.graphics.setFocus(Qt.FocusReason.MouseFocusReason)
        return index

    def _update_selection(self, coordinates=None):
        index = self._selected_index()
        self.delete_button.setEnabled(index is not None)
        if index is None:
            self.coordinates.setText(self.tr("Select a data point"))
            if self._marker is not None:
                self._marker.setData([], [])
            return
        curve = self._curve()
        x, y = coordinates if coordinates is not None else (curve.x[index], curve.y[index])
        self.coordinates.setText(f"{curve.name} · {self.tr('Point')} {index + 1}: X = {x:.9g}, Y = {y:.9g}")
        if self._marker is None:
            self._marker = pg.PlotDataItem(
                pen=None, symbolSize=16, symbol="o", symbolPen=pg.mkPen("#E69F00", width=2),
                symbolBrush=pg.mkBrush(0, 0, 0, 0))
            self._marker.setZValue(1000)
            self._marker.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.workspace.plot.addItem(self._marker)
        x_offset, y_offset = self.workspace._active_display_offsets()
        xx = np.array([x + x_offset])
        yy = np.array([y - float(self._background(np.array([x]))[0]) + y_offset])
        self._marker.setData(xx, yy)

    def begin_drag(self, scene_position):
        index = self.select_at(scene_position)
        if index is None:
            self._drag = None
            return False
        curve = self._curve()
        start = self.workspace.view_box.mapSceneToView(scene_position)
        xx, yy = self.display_coordinates(curve.x[index:index+1], curve.y[index:index+1])
        self._drag = {
            "curve_id": curve.id, "row": self.selected_row, "index": index,
            "start": (float(start.x()), float(start.y())),
            "anchor": (float(xx[0]), float(yy[0])),
            "old": (float(curve.x[index]), float(curve.y[index])),
            "new": (float(curve.x[index]), float(curve.y[index])),
        }
        return True

    def update_drag(self, scene_position):
        drag = self._drag
        if drag is None:
            return
        curve = self._curve()
        if curve is None or curve.id != drag["curve_id"] or self.workspace._project.read_only:
            self.cancel_drag()
            return
        end = self.workspace.view_box.mapSceneToView(scene_position)
        xx = drag["anchor"][0] + float(end.x()) - drag["start"][0]
        yy = drag["anchor"][1] + float(end.y()) - drag["start"][1]
        x_offset, y_offset = self.workspace._active_display_offsets()
        axes = self.axes.currentData()
        try:
            x = (10.0**xx if self.workspace.plot.ctrl.logXCheck.isChecked() else xx) - x_offset
            if "x" not in axes:
                x = drag["old"][0]
            y = (10.0**yy if self.workspace.plot.ctrl.logYCheck.isChecked() else yy) - y_offset
            y += float(self._background(np.array([x]))[0])
            if "y" not in axes:
                y = drag["old"][1]
        except (OverflowError, ValueError):
            return
        if not np.isfinite(x) or not np.isfinite(y):
            return
        drag["new"] = (x, y)
        self._preview_point(drag["index"], x, y)
        self._update_selection((x, y))

    def _preview_point(self, index, x, y):
        from curvemole.gui.rendering import _optimise_plot_data_item

        curve = self._curve()
        xx, yy = curve.x.copy(), curve.y.copy()
        xx[index], yy[index] = x, y
        x_offset, y_offset = self.workspace._active_display_offsets()
        display_y = yy - self._background(xx) + y_offset
        keep = ~curve.effective_mask
        item = self.workspace._data_items.get(curve.id)
        if item is not None:
            item.setData(xx[keep] + x_offset, display_y[keep])
            _optimise_plot_data_item(item, adaptive=self.workspace.display_mode.currentIndex() != 0)
        if self._points is not None:
            self._points.setData(xx[keep] + x_offset, display_y[keep])
            _optimise_plot_data_item(self._points, adaptive=self.workspace.display_mode.currentIndex() != 0)
        error_item = self.workspace._error_items.get(curve.id)
        if error_item is not None:
            from curvemole.gui.data_errors import error_bar_item
            preview = error_bar_item(curve, xx + x_offset, display_y, keep, curve.colour)
            if preview is not None:
                ex, ey = preview.getOriginalDataset()
                error_item.setData(ex, ey)

    def end_drag(self, scene_position):
        if self._drag is None:
            return
        self.update_drag(scene_position)
        drag, self._drag = self._drag, None
        if drag is None:
            return
        if not all(math.isclose(old, new, rel_tol=1e-14, abs_tol=0.0)
                   for old, new in zip(drag["old"], drag["new"], strict=True)):
            self.moveRequested.emit(drag["curve_id"], drag["row"], *drag["new"])
        # Also restore a rejected/read-only/no-op preview from the actual data.
        self.workspace.refresh()

    def cancel_drag(self, *_):
        if self._drag is not None:
            self._drag = None
            self.workspace.refresh()

    def delete_selected(self):
        index = self._selected_index()
        if not self.active or index is None or self.workspace._project.read_only:
            return
        self.cancel_drag()
        curve = self._curve()
        self.deleteRequested.emit(curve.id, self.selected_row)
        self.workspace.refresh()
