"""Graphical placement of peaks, splines and point-defined functions on the plot.

PlacementController handles click/drag placement, previews, point removal,
the placement instruction bar and which plot items receive mouse clicks while
placing. PlotWorkspace keeps delegating methods with the historical names.
"""

from __future__ import annotations

import math
from contextlib import suppress
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QPointF, Qt
from shiboken6 import isValid


class PlacementController(QObject):
    def __init__(self, workspace: Any) -> None:
        super().__init__(workspace)
        self.workspace = workspace

    def begin_peak_placement(self, name: str) -> None:
        workspace = self.workspace
        workspace.restore_data_view_for_editing()
        workspace.cancel_placement()
        workspace._placement_mode = "peak"
        workspace._placement_name = name
        workspace._peak_preview = None
        workspace.view_box.interaction_mode = "peak"
        workspace.mask_toggle.setChecked(False)
        workspace.mask_toggle.setEnabled(False)
        workspace.undo_point_button.hide()
        workspace.finish_placement_button.hide()
        workspace.placement_label.setText(
            workspace.tr("Place ")
            + name
            + workspace.tr(": click the peak centre, drag horizontally to either half-height edge, and release. Esc cancels.")
        )
        workspace.placement_bar.show()
        workspace.graphics.setCursor(Qt.CursorShape.CrossCursor)
        workspace._update_interaction_state()
        workspace._sync_placement_mouse_targets()

    def begin_spline_placement(self, name: str) -> None:
        workspace = self.workspace
        workspace.restore_data_view_for_editing()
        workspace.cancel_placement()
        workspace._placement_mode = "spline"
        workspace._placement_name = name
        workspace._spline_points = []
        workspace.placement_editor.start()
        workspace.view_box.interaction_mode = "spline"
        # Placement graphics must never force a new view range. Manual pan/zoom stays active.
        workspace.view_box.disableAutoRange()
        workspace.mask_toggle.setChecked(False)
        workspace.mask_toggle.setEnabled(False)
        workspace.undo_point_button.show()
        workspace.finish_placement_button.show()
        workspace.undo_point_button.setEnabled(False)
        workspace.finish_placement_button.setEnabled(False)
        workspace._update_spline_instruction()
        workspace.placement_bar.show()
        workspace.graphics.setCursor(Qt.CursorShape.CrossCursor)
        workspace._update_interaction_state()
        workspace._sync_placement_mouse_targets()

    def mark_quick_add_placement(self) -> None:
        workspace = self.workspace
        """Enable Quick Add finish gestures for the placement just started."""
        if workspace._placement_mode is None:
            return
        workspace._quick_add_placement = True
        workspace.view_box.quick_add_placement = True
        workspace.view_box._context_menu_timer.stop()
        workspace.view_box._context_menu_event = None
        workspace._quick_add_return.setEnabled(True)
        workspace._quick_add_enter.setEnabled(True)
        if workspace._placement_mode == "spline":
            workspace._update_spline_instruction()

    def cancel_placement(self) -> None:
        workspace = self.workspace
        for session in list(workspace._plugin_plot_sessions.values()):
            if session.picking:
                session.set_picking(False)
        if workspace.point_editor.active:
            workspace.point_editor.finish()
        if workspace._placement_mode is None:
            return
        workspace._end_placement()
        workspace.placementCancelled.emit()

    def finish_placement(self) -> None:
        workspace = self.workspace
        if workspace._placement_mode != "spline":
            return
        if len(workspace._spline_points) < 2:
            workspace._update_spline_instruction()
            return
        points = sorted(workspace._spline_points)
        workspace._end_placement()
        workspace.splinePlacementFinished.emit(points)

    def undo_spline_point(self) -> None:
        workspace = self.workspace
        if workspace._placement_mode == "spline":
            workspace.placement_editor.undo()

    def _preview_peak_placement(self, x: float, y: float, fwhm: float) -> None:
        workspace = self.workspace
        if workspace._placement_mode != "peak":
            return
        x, y = workspace._from_display_coordinates(x, y)
        workspace._peak_preview = (x, y, fwhm)
        workspace._render_placement_preview()

    def _finish_peak_placement(self, x: float, y: float, fwhm: float) -> None:
        workspace = self.workspace
        if workspace._placement_mode != "peak":
            return
        x, y = workspace._from_display_coordinates(x, y)
        selected_width = fwhm if fwhm > 0 else workspace._default_peak_width()
        workspace._end_placement()
        workspace.peakPlacementFinished.emit(x, y, selected_width)

    def _add_spline_point(self, x: float, y: float) -> None:
        workspace = self.workspace
        if workspace._placement_mode != "spline":
            return
        x, y = workspace.placement_editor.data_position(QPointF(x, y), scene=False)
        if not math.isfinite(x) or not math.isfinite(y):
            return
        tolerance = max(workspace._active_x_span(), 1.0) * 1e-12
        for index, (existing_x, _) in enumerate(workspace._spline_points):
            if math.isclose(x, existing_x, rel_tol=0.0, abs_tol=tolerance):
                if workspace._spline_points[index] == (x, y):
                    return
                workspace.placement_editor.record()
                workspace._spline_points[index] = (x, y)
                break
        else:
            workspace.placement_editor.record()
            workspace._spline_points.append((x, y))
        workspace._render_placement_preview()
        workspace._update_spline_instruction()

    def _remove_spline_point(self, x: float, y: float) -> None:
        workspace = self.workspace
        if workspace._placement_mode != "spline" or not workspace._spline_points:
            return
        x, y = workspace.placement_editor.data_position(QPointF(x, y), scene=False)
        x_scale = max(workspace._active_x_span(), np.finfo(float).eps)
        y_scale = max(workspace._active_y_span(), np.finfo(float).eps)
        index = min(
            range(len(workspace._spline_points)),
            key=lambda item: (
                ((workspace._spline_points[item][0] - x) / x_scale) ** 2
                + ((workspace._spline_points[item][1] - y) / y_scale) ** 2
            ),
        )
        workspace.placement_editor.record()
        workspace._spline_points.pop(index)
        workspace._render_placement_preview()
        workspace._update_spline_instruction()

    def _render_placement_preview(self) -> None:
        workspace = self.workspace
        workspace._clear_placement_items()
        if workspace._placement_mode is None or workspace._project is None or not workspace._active_curve_id:
            return
        x_offset, y_offset = workspace._active_display_offsets()
        if workspace._placement_mode == "peak" and workspace._peak_preview is not None:
            centre, height, fwhm = workspace._peak_preview
            width = fwhm if fwhm > 0 else workspace._default_peak_width()
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
            marker = workspace.plot.plot(
                [centre + x_offset],
                [height + y_offset],
                pen=None,
                symbol="+",
                symbolSize=14,
                symbolPen=pg.mkPen("#009E73", width=2),
            )
            for item in (region, centre_line):
                workspace.plot.addItem(item)
            workspace._placement_items.extend([region, centre_line, marker])
            return
        if workspace._placement_mode != "spline" or not workspace._spline_points:
            return
        ordered = sorted(workspace._spline_points)
        node_x = np.asarray([point[0] for point in ordered], dtype=float)
        node_y = np.asarray([point[1] for point in ordered], dtype=float)
        markers = workspace.plot.plot(
            node_x + x_offset,
            node_y + y_offset,
            pen=None,
            symbol="o",
            symbolSize=9,
            symbolBrush=pg.mkBrush("#009E73"),
            symbolPen=pg.mkPen("#ffffff", width=1),
        )
        workspace._placement_items.append(markers)
        if len(ordered) < 2:
            return
        curve = workspace._project.dataset.curve(workspace._active_curve_id)
        finite = np.isfinite(curve.x)
        if not np.any(finite):
            return
        data_x = np.asarray(curve.x[finite], dtype=float)
        lower = float(min(np.min(data_x), np.min(node_x)))
        upper = float(max(np.max(data_x), np.max(node_x)))
        preview_count = max(400, min(4000, len(data_x) * 2))
        preview_x = np.linspace(lower, upper, preview_count)
        metadata = {"x_nodes": node_x.tolist()}
        values = {f"y{index}": value for index, value in enumerate(node_y)}
        preview = workspace.registry.get("cubic_spline").evaluate(preview_x, values, metadata)
        line = workspace.plot.plot(
            preview_x + x_offset,
            preview + y_offset,
            pen=pg.mkPen("#009E73", width=2, style=Qt.PenStyle.DashLine),
        )
        workspace._placement_items.append(line)

    def _clear_placement_items(self) -> None:
        workspace = self.workspace
        for item in workspace._placement_items:
            # Live dragging replaces preview graphics repeatedly. Retaining their
            # mouse-state snapshots would also retain every discarded preview.
            pending = [item]
            while pending:
                target = pending.pop()
                if isValid(target):
                    pending.extend(target.childItems())
                workspace._placement_mouse_targets.pop(target, None)
            with suppress(RuntimeError):
                workspace.plot.removeItem(item)
        workspace._placement_items.clear()

    def _end_placement(self) -> None:
        workspace = self.workspace
        workspace.placement_editor.stop()
        workspace._clear_placement_items()
        workspace._placement_mode = None
        workspace._quick_add_placement = False
        workspace.view_box.quick_add_placement = False
        workspace._quick_add_return.setEnabled(False)
        workspace._quick_add_enter.setEnabled(False)
        workspace._placement_name = ""
        workspace._peak_preview = None
        workspace._spline_points = []
        workspace.view_box.interaction_mode = None
        workspace.placement_bar.hide()
        workspace.mask_toggle.setEnabled(True)
        workspace.graphics.unsetCursor()
        workspace._update_interaction_state()
        workspace._sync_placement_mouse_targets()

    def _restore_placement_mouse_targets(self) -> None:
        workspace = self.workspace
        for item, (buttons, enabled) in workspace._placement_mouse_targets.items():
            if isValid(item):
                item.setAcceptedMouseButtons(buttons)
                item.setEnabled(enabled)
        workspace._placement_mouse_targets.clear()

    def _sync_placement_mouse_targets(self) -> None:
        workspace = self.workspace
        """Let placement clicks pass through plot symbols, curves and handles."""
        if (workspace._placement_mode is None and not workspace.point_editor.active
                and workspace.view_box.interaction_mode != 'plugin_points'):
            workspace._restore_placement_mouse_targets()
            return

        no_button = Qt.MouseButton.NoButton
        roots = (
            *workspace.plot.items,
            *workspace._data_items.values(),
            *workspace._component_items.values(),
            *workspace._placement_items,
            *workspace._handles,
        )
        items: list[Any] = []
        seen: set[Any] = set()
        for root in roots:
            pending = [root]
            while pending:
                item = pending.pop()
                if not isValid(item) or item in seen:
                    continue
                seen.add(item)
                items.append(item)
                pending.extend(item.childItems())
        # Snapshot all children before disabling their parents: Qt propagates
        # the disabled state, so reading a child afterwards loses its old value.
        for item in items:
            if item not in workspace._placement_mouse_targets:
                workspace._placement_mouse_targets[item] = (
                    item.acceptedMouseButtons(), item.isEnabled()
                )
        for item in items:
            item.setAcceptedMouseButtons(no_button)
            item.setEnabled(False)

    def _update_spline_instruction(self) -> None:
        workspace = self.workspace
        count = len(workspace._spline_points)
        finish = (
            workspace.tr("Right-click, press Enter or Finish when done; Esc cancels.")
            if workspace._quick_add_placement else
            workspace.tr("Press Finish when done; Esc cancels. Right-click removes the nearest point.")
        )
        workspace.placement_label.setText(
            workspace.tr("Place spline nodes: ")
            + workspace.placement_editor.instruction()
            + workspace.tr("The mouse wheel zooms. The curve updates live. ")
            + f"{count}/2 " + workspace.tr("minimum points. ") + finish
        )
        workspace.undo_point_button.setEnabled(workspace.placement_editor.can_undo)
        workspace.finish_placement_button.setEnabled(count >= 2)

    def _default_peak_width(self) -> float:
        workspace = self.workspace
        if workspace._project is None or not workspace._active_curve_id:
            return 1.0
        curve = workspace._project.dataset.curve(workspace._active_curve_id)
        finite = np.sort(curve.x[np.isfinite(curve.x)])
        spacing = float(np.nanmedian(np.abs(np.diff(finite)))) if len(finite) > 1 else 0.0
        return max(workspace._active_x_span() * 0.05, spacing * 4, np.finfo(float).eps)
