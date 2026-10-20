"""Owner-scoped, non-mutating previews and sample picking for plugin panels."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from curvemole.core.extensions import extensions


class PluginPlotSession(QObject):
    sampleClicked = Signal(int)
    markerClicked = Signal(int)
    pickingChanged = Signal(bool)
    invalidated = Signal()

    def __init__(self, window, owner, curve_id):
        workspace = window.plot_workspace
        super().__init__(workspace)
        self._window, self._workspace, self._owner = window, workspace, owner
        self._project = window.project
        self._curve_id = curve_id
        self._hash = self._project.dataset.curve(curve_id).content_hash
        self._segments, self._markers, self._items = [], [], []
        self._interval = None
        self.closed = False
        self.picking = False
        self._bar = QWidget(workspace)
        layout = QHBoxLayout(self._bar)
        self._instruction = QLabel()
        self._instruction.setWordWrap(True)
        layout.addWidget(self._instruction, 1)
        done = QPushButton(self.tr("Done"))
        done.clicked.connect(lambda: self.set_picking(False))
        layout.addWidget(done)
        workspace.layout().insertWidget(workspace.layout().indexOf(workspace.graphics), self._bar)
        self._bar.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def _curve(self, *, check_data=True):
        w = self._window
        if (self.closed or self._project is not w.project or w.active_curve_id != self._curve_id
                or self._owner in w.plugin_manager.errors
                or not any(e.owner == self._owner for e in extensions.entries.values())
                or not any(c.id == self._curve_id for c in self._workspace.displayed_curves())):
            return None
        curve = w.project.dataset.curve(self._curve_id)
        return curve if not check_data or curve.content_hash == self._hash else None

    def _poll(self):
        if self._curve(check_data=False) is None:
            self._invalidate()
        elif self.picking and self._window._thread is not None:
            self.set_picking(False)

    def _require_curve(self):
        curve = self._curve()
        if curve is None:
            self._invalidate()
            raise ValueError("The plugin plot session is no longer current.")
        return curve

    @staticmethod
    def _index(value, length):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or not 0 <= value < length:
            raise ValueError("Preview indices must refer to current spectrum rows.")
        return int(value)

    def set_preview(self, *, segments=(), markers=(), selected_interval=None):
        """Display indexed Y segments/markers without changing source data or zoom."""
        curve = self._require_curve()
        new_segments, new_markers = [], []
        for item in segments:
            indices = np.asarray([self._index(i, len(curve)) for i in item['indices']], dtype=int)
            y = np.asarray(item['y'], dtype=float).copy()
            if y.shape != indices.shape or not len(indices) or not np.all(np.isfinite(y)):
                raise ValueError("Preview Y values must be finite and match their indices.")
            new_segments.append((indices, y, pg.mkColor(item.get('colour', '#0ea5a4'))))
        for item in markers:
            index = self._index(item['index'], len(curve))
            symbol = item.get('symbol', 'o')
            if symbol not in ('o', 'x', '+', 's', 'd', 't'):
                raise ValueError("Unsupported preview marker symbol.")
            new_markers.append((index, pg.mkColor(item.get('colour', '#E69F00')), symbol,
                                bool(item.get('selected', False))))
        interval = None
        if selected_interval is not None:
            if len(selected_interval) != 2:
                raise ValueError("A selected interval needs two sample indices.")
            interval = tuple(sorted(self._index(i, len(curve)) for i in selected_interval))
        self._segments, self._markers, self._interval = new_segments, new_markers, interval
        self.refresh()

    def _remove_items(self):
        for item in self._items:
            self._workspace.plot.removeItem(item)
        self._items.clear()

    def refresh(self):
        if self.closed:
            return
        curve = self._curve()
        if curve is None:
            self._invalidate()
            return
        self._remove_items()
        ws = self._workspace
        if ws.display_replays(curve):
            return
        dx, dy = ws._active_display_offsets()

        def add(item, z):
            item.setZValue(z)
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            ws.plot.addItem(item, ignoreBounds=True)
            self._items.append(item)

        for indices, y, colour in self._segments:
            xx = curve.x[indices] + dx
            yy = y - ws.point_editor._background(curve.x[indices]) + dy
            hidden = curve.effective_mask[indices]
            xx, yy = xx.copy(), yy.copy()
            xx[hidden], yy[hidden] = np.nan, np.nan
            add(pg.PlotDataItem(xx, yy, pen=pg.mkPen(colour, width=2), connect='finite'), 40)
        for position, (index, colour, symbol, selected) in enumerate(self._markers):
            if curve.effective_mask[index]:
                continue
            xx = curve.x[index:index+1] + dx
            yy = curve.y[index:index+1] - ws.point_editor._background(curve.x[index:index+1]) + dy
            item = pg.PlotDataItem(xx, yy, pen=None, symbol=symbol, symbolSize=16 if selected else 10,
                                   symbolPen=pg.mkPen(colour, width=2), symbolBrush=pg.mkBrush(colour))
            add(item, 50)
            item.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
            item.sigPointsClicked.connect(
                lambda _item, _points, event, row=position: self._marker_clicked(row, event))
        if self._interval is not None:
            lo, hi = self._interval
            xx = curve.x[lo:hi+1] + dx
            with np.errstate(divide='ignore', invalid='ignore'):
                if ws.plot.ctrl.logXCheck.isChecked():
                    xx = np.log10(xx)
            xx = xx[np.isfinite(xx)]
            if len(xx) and xx.min() < xx.max():
                add(pg.LinearRegionItem((float(xx.min()), float(xx.max())), movable=False,
                                        brush=pg.mkBrush(230, 159, 0, 35), pen=pg.mkPen(None)), -5)

    def _marker_clicked(self, index, event):
        ws = self._workspace
        if self._curve() is not None and ws.view_box.interaction_mode is None and not ws.view_box.mask_mode:
            event.accept()
            # A panel may redraw all markers while selecting its row. Keep the
            # clicked graphics item alive until Qt finishes dispatching the event.
            QTimer.singleShot(0, self, lambda: self._emit_marker(index))
        else:
            event.ignore()

    def _emit_marker(self, index):
        if self._curve() is not None:
            self.markerClicked.emit(index)

    def marker_at(self, scene_position):
        curve = self._curve()
        if curve is None or self._workspace.display_replays(curve) or not self._markers:
            return None
        indices = np.array([m[0] for m in self._markers])
        distances = self._distances(curve, scene_position, indices)
        marker = int(np.argmin(distances))
        return marker if distances[marker] <= 12**2 else None

    def _distances(self, curve, scene_position, indices):
        ws = self._workspace
        xx, yy = ws.point_editor.display_coordinates(curve.x[indices], curve.y[indices])
        position = ws.view_box.mapSceneToView(scene_position)
        px, py = ws.view_box.viewPixelSize()
        with np.errstate(divide='ignore', invalid='ignore'):
            distances = ((xx-position.x())/px)**2 + ((yy-position.y())/py)**2
        distances[~np.isfinite(distances) | curve.effective_mask[indices]] = np.inf
        return distances

    def pick(self, scene_position):
        curve = self._require_curve()
        distances = self._distances(curve, scene_position, np.arange(len(curve)))
        if len(distances):
            index = int(np.argmin(distances))
            if distances[index] <= 12**2:
                self.sampleClicked.emit(index)

    def set_picking(self, enabled, *, instruction="Select a data point in the main graph. Esc ends selection."):
        ws = self._workspace
        if enabled:
            ws.restore_data_view_for_editing()
            self._require_curve()
            if self._window._thread is not None:
                raise ValueError("Wait for the current calculation before selecting data points.")
            ws.cancel_placement()
            ws.mask_toggle.setChecked(False)
            ws.view_box._context_menu_timer.stop()
            ws.view_box._context_menu_event = None
            ws.view_box.plugin_session = self
            ws.view_box.interaction_mode = 'plugin_points'
            ws.graphics.setCursor(Qt.CursorShape.CrossCursor)
            ws.graphics.setFocus()
            self._instruction.setText(str(instruction))
            self._bar.show()
        elif self.picking:
            if ws.view_box.interaction_mode == 'plugin_points' and ws.view_box.plugin_session is self:
                ws.view_box.interaction_mode = None
                ws.graphics.unsetCursor()
            self._bar.hide()
        changed = self.picking != bool(enabled)
        self.picking = bool(enabled)
        ws._sync_placement_mouse_targets()
        if changed:
            self.pickingChanged.emit(self.picking)

    def _invalidate(self):
        if not self.closed:
            self.close()
            self.invalidated.emit()

    @Slot()
    def close(self):
        if self.closed:
            return
        self.set_picking(False)
        self._remove_items()
        self._timer.stop()
        self.closed = True
        self._bar.hide()
        self._bar.deleteLater()
        if self._workspace._plugin_plot_sessions.get(self._owner) is self:
            self._workspace._plugin_plot_sessions.pop(self._owner)
        self.deleteLater()
