"""Edit temporary function-initialization points without touching spectrum data."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QComboBox


class PointPlacementEditor:
    def __init__(self, workspace, layout) -> None:
        self.workspace = workspace
        self.mode = QComboBox()
        self.mode.addItem(workspace.tr("Add points"), "add")
        self.mode.addItem(workspace.tr("Delete points"), "delete")
        self.mode.addItem(workspace.tr("Move points"), "move")
        self.mode.setToolTip(workspace.tr(
            "Edit the function's initialization points. Experimental data are unchanged. "
            "Drag empty space to pan; use the mouse wheel to zoom."
        ))
        self.mode.setAccessibleName(workspace.tr("Point editing mode"))
        layout.insertWidget(1, self.mode)
        self.mode.hide()
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._history: list[list[tuple[float, float]]] = []
        self._drag_index: int | None = None
        self._drag_before: list[tuple[float, float]] | None = None

    def start(self) -> None:
        self._history.clear()
        self._drag_index = None
        self._drag_before = None
        self.mode.setCurrentIndex(0)
        self.mode.show()

    def stop(self) -> None:
        self._history.clear()
        self._drag_index = None
        self._drag_before = None
        self.mode.hide()

    @property
    def can_undo(self) -> bool:
        return bool(self._history)

    def record(self) -> None:
        self._history.append(list(self.workspace._spline_points))

    def undo(self) -> None:
        self._finish_drag()
        if self._history:
            self.workspace._spline_points = self._history.pop()
            self._changed()

    def instruction(self) -> str:
        w = self.workspace
        if self.mode.currentData() == "delete":
            return w.tr("Left-click a point to delete it; left-drag empty space to pan. ")
        if self.mode.currentData() == "move":
            return w.tr("Left-click and drag a point to move it; left-drag empty space to pan. ")
        return w.tr("Left-click adds a point; left-drag pans. ")

    def _mode_changed(self, *_args) -> None:
        self._finish_drag()
        if self.workspace._placement_mode == "spline":
            self.workspace.graphics.setCursor(
                Qt.CursorShape.OpenHandCursor
                if self.mode.currentData() == "move" else Qt.CursorShape.CrossCursor
            )
            self.workspace._update_spline_instruction()

    def data_position(self, position: QPointF, *, scene: bool = True) -> tuple[float, float]:
        w = self.workspace
        point = w.view_box.mapSceneToView(position) if scene else position
        x, y = float(point.x()), float(point.y())
        try:
            if w.plot.ctrl.logXCheck.isChecked():
                x = 10.0 ** x
            if w.plot.ctrl.logYCheck.isChecked():
                y = 10.0 ** y
        except OverflowError:
            return math.nan, math.nan
        return w._from_display_coordinates(x, y)

    def _point_at(self, position: QPointF) -> int | None:
        """Use a fixed screen radius, independent of data range, zoom or offsets."""
        w = self.workspace
        x_offset, y_offset = w._active_display_offsets()
        nearest, distance = None, 12.0 ** 2
        for index, (x, y) in enumerate(w._spline_points):
            x, y = x + x_offset, y + y_offset
            if w.plot.ctrl.logXCheck.isChecked():
                if x <= 0:
                    continue
                x = math.log10(x)
            if w.plot.ctrl.logYCheck.isChecked():
                if y <= 0:
                    continue
                y = math.log10(y)
            point = w.view_box.mapViewToScene(QPointF(x, y))
            delta = point - position
            candidate = delta.x() ** 2 + delta.y() ** 2
            if candidate <= distance:
                nearest, distance = index, candidate
        return nearest

    def click_at(self, position: QPointF) -> bool:
        if self.mode.currentData() == "add":
            return False
        if self.mode.currentData() == "delete":
            index = self._point_at(position)
            if index is not None:
                self.record()
                self.workspace._spline_points.pop(index)
                self._changed()
        # A click/double-click in Move mode neither adds a point nor finishes.
        return True

    def drag(self, event) -> bool:
        if self.mode.currentData() != "move":
            return False
        if event.isStart():
            self._drag_index = self._point_at(event.buttonDownScenePos())
            self._drag_before = (
                list(self.workspace._spline_points) if self._drag_index is not None else None
            )
        if self._drag_index is None:
            return False
        w = self.workspace
        x, y = self.data_position(event.scenePos())
        tolerance = max(w._active_x_span(), 1.0) * 1e-12
        # Coincident x coordinates cannot define a spline. Keep the original point
        # rather than silently deleting or merging another control point.
        duplicate = any(
            index != self._drag_index and math.isclose(x, px, rel_tol=0, abs_tol=tolerance)
            for index, (px, _py) in enumerate(w._spline_points)
        )
        if math.isfinite(x) and math.isfinite(y) and not duplicate:
            w._spline_points[self._drag_index] = (x, y)
            self._changed()
        if event.isFinish():
            self._finish_drag()
            w._update_spline_instruction()
        return True

    def _finish_drag(self) -> None:
        if self._drag_before is not None and self._drag_before != self.workspace._spline_points:
            self._history.append(self._drag_before)
        self._drag_index = None
        self._drag_before = None

    def _changed(self) -> None:
        self.workspace._render_placement_preview()
        self.workspace._update_spline_instruction()
