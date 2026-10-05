"""A control row that wraps when docks leave less room for the plot."""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QLabel, QLayout, QLayoutItem


class FlowLayout(QLayout):
    def __init__(self, spacing: int = 6) -> None:
        super().__init__()
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            item = self._items.pop(index)
            self.invalidate()
            return item
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect: QRect, *, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, row_height = area.x(), area.y(), 0
        for index, item in enumerate(self._items):
            if item.isEmpty():
                continue
            size = item.sizeHint()
            # A dynamic coordinate/metric label may have a very long size hint.
            # Constrain it to the available row and let its word wrap handle height.
            width = min(size.width(), max(area.width(), item.minimumSize().width()))
            height = item.heightForWidth(width) if item.hasHeightForWidth() else size.height()
            needed = width
            widget = item.widget()
            if isinstance(widget, QLabel) and widget.buddy() is not None:
                following = self.itemAt(index + 1)
                if following is not None and following.widget() is widget.buddy():
                    needed += self.spacing() + following.sizeHint().width()
            if row_height and x + needed > area.right() + 1:
                x = area.x()
                y += row_height + self.spacing()
                row_height = 0
            if apply:
                item.setGeometry(QRect(x, y, width, height))
            x += width + self.spacing()
            row_height = max(row_height, height)
        return y + row_height - rect.y() + margins.bottom()
