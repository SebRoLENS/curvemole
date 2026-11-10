"""Internal row drags that leave model changes to the owning panel."""

from typing import NamedTuple

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QDrag, QPainter, QPalette, QPen


class RowDrop(NamedTuple):
    target: QModelIndex
    after: bool
    x: int
    y: int


class RowDragMixin:
    def setup_row_drag(self):
        self._pressed_row = QPersistentModelIndex()
        self._dragged_row = QPersistentModelIndex()
        self._row_drop = None
        self._drag_position = None
        self.setDragDropMode(self.DragDropMode.InternalMove)
        self.setDropIndicatorShown(False)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed_row = QPersistentModelIndex(self.indexAt(event.position().toPoint()))
        super().mousePressEvent(event)

    def startDrag(self, supported_actions):
        source = QModelIndex(self._pressed_row)
        if not source.isValid() or not source.flags() & Qt.ItemFlag.ItemIsDragEnabled:
            return
        drag = QDrag(self)
        drag.setMimeData(self.model().mimeData([source]))
        self._dragged_row = self._pressed_row
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._dragged_row = QPersistentModelIndex()
            self._drag_position = None
            self._show_row_drop(None)

    def dragEnterEvent(self, event):
        if event.source() is self and self._dragged_row.isValid():
            super().dragEnterEvent(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.source() is not self or not self._dragged_row.isValid():
            self._show_row_drop(None)
            event.ignore()
            return
        super().dragMoveEvent(event)  # Keep Qt's edge autoscroll.
        self._drag_position = event.position().toPoint()
        drop = self._row_drop_at(QModelIndex(self._dragged_row), self._drag_position)
        self._show_row_drop(drop)
        if drop is None:
            event.ignore()
        else:
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        if self._drag_position is not None and self._dragged_row.isValid():
            self._show_row_drop(self._row_drop_at(QModelIndex(self._dragged_row), self._drag_position))

    def dragLeaveEvent(self, event):
        self._drag_position = None
        self._show_row_drop(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._drag_position = None
        self._show_row_drop(None)
        if event.source() is not self or not self._dragged_row.isValid():
            event.ignore()
            return
        source = QModelIndex(self._dragged_row)
        drop = self._row_drop_at(source, event.position().toPoint())
        if drop is None:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self._request_row_move(source, drop)

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
