"""Internal row drags that leave model changes to the owning panel."""

from typing import NamedTuple

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, Qt, QTimer
from PySide6.QtGui import QPainter, QPalette, QPen


class RowDrop(NamedTuple):
    target: QModelIndex
    after: bool
    x: int
    y: int


class RowDragMixin:
    def setup_row_drag(self):
        self._pressed_row = QPersistentModelIndex()
        self._dragged_row = None
        self._row_drop = None
        self._drag_position = None
        self._edge_scroll_steps = 0
        self._edge_scroll_timer = QTimer(self)
        self._edge_scroll_timer.setInterval(50)
        self._edge_scroll_timer.timeout.connect(self._scroll_at_drag_edge)
        self.setDragDropMode(self.DragDropMode.DragOnly)
        self.setDropIndicatorShown(False)
        self.model().modelReset.connect(self._end_row_drag)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed_row = QPersistentModelIndex(self.indexAt(event.position().toPoint()))
        super().mousePressEvent(event)

    def startDrag(self, supported_actions):
        source = QModelIndex(self._pressed_row)
        if not source.isValid() or not source.flags() & Qt.ItemFlag.ItemIsDragEnabled:
            return
        # The native drag loop can consume wheel input. Keep reordering inside
        # the view so its ordinary wheel handling works while a row is held.
        self._dragged_row = self._pressed_row
        self._pressed_row = QPersistentModelIndex()
        self.viewport().setCursor(Qt.CursorShape.DragMoveCursor)

    def mouseMoveEvent(self, event):
        if self._dragged_row is None:
            super().mouseMoveEvent(event)
        if self._dragged_row is None:
            return

        position = event.position().toPoint()
        rect = self.viewport().rect()
        self._drag_position = position if rect.contains(position) else None
        margin = self.autoScrollMargin()
        near_edge = not rect.adjusted(margin, margin, -margin, -margin).contains(position)
        if self._drag_position is not None and near_edge and self.hasAutoScroll():
            if not self._edge_scroll_timer.isActive():
                self._edge_scroll_timer.start()
        else:
            self._stop_edge_scroll()
        self._refresh_row_drop()

    def _scroll_at_drag_edge(self):
        position = self._drag_position
        if position is None:
            return
        self._edge_scroll_steps += 1
        margin = self.autoScrollMargin()
        viewport = self.viewport()
        for offset, size, scrollbar in (
            (position.x(), viewport.width(), self.horizontalScrollBar()),
            (position.y(), viewport.height(), self.verticalScrollBar()),
        ):
            step = min(self._edge_scroll_steps, max(1, scrollbar.pageStep()))
            if offset < margin:
                scrollbar.setValue(scrollbar.value() - step)
            elif offset >= size - margin:
                scrollbar.setValue(scrollbar.value() + step)

    def _stop_edge_scroll(self):
        self._edge_scroll_timer.stop()
        self._edge_scroll_steps = 0

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._dragged_row is None:
            super().mouseReleaseEvent(event)
            return
        source = QModelIndex(self._dragged_row)
        position = event.position().toPoint()
        drop = None
        if source.isValid() and self.viewport().rect().contains(position):
            drop = self._row_drop_at(source, position)
        self._end_row_drag()
        if drop is not None:
            self._request_row_move(source, drop)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._dragged_row is not None:
            self._end_row_drag()
            event.accept()
            return
        super().keyPressEvent(event)

    def viewportEvent(self, event):
        if event.type() in (QEvent.Type.UngrabMouse, QEvent.Type.Hide):
            self._end_row_drag()
        return super().viewportEvent(event)

    def _end_row_drag(self):
        if self._dragged_row is None:
            return
        self._dragged_row = None
        self._drag_position = None
        self._stop_edge_scroll()
        self.viewport().unsetCursor()
        self._show_row_drop(None)

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self._refresh_row_drop()

    def _refresh_row_drop(self):
        if self._drag_position is not None and self._dragged_row.isValid():
            self._show_row_drop(self._row_drop_at(QModelIndex(self._dragged_row), self._drag_position))
        else:
            self._show_row_drop(None)

    def _show_row_drop(self, drop):
        if self._row_drop != drop:
            self._row_drop = drop
            self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._row_drop is None:
            return
        _, _, x, y = self._row_drop
        y = max(2, min(y, self.viewport().height() - 3))
        painter = QPainter(self.viewport())
        for role, width in ((QPalette.ColorRole.Base, 5), (QPalette.ColorRole.Highlight, 3)):
            painter.setPen(QPen(self.palette().color(role), width))
            painter.drawLine(x, y, self.viewport().width() - 3, y)
        painter.end()
