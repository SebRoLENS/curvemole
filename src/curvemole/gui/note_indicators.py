"""Clickable note and spectrum colour decorations for item views."""

from math import floor

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
)
from shiboken6 import isValid

from curvemole.core.notebook import description_key
from curvemole.gui.icons import vector_icon

NOTE_ROLE = int(Qt.ItemDataRole.UserRole) + 20
CHECKBOX_TOOLTIP_ROLE = int(Qt.ItemDataRole.UserRole) + 21


def checkbox_indicator_size(view) -> QSize:
    """Get the real Qt item-checkbox size, which differs from PM_IndicatorSize on macOS."""
    option = QStyleOptionViewItem()
    option.initFrom(view)
    option.rect = QRect(0, 0, 100, max(32, view.fontMetrics().height() + 12))
    option.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
    option.checkState = Qt.CheckState.Checked
    style = view.style()
    indicator = style.subElementRect(
        QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, view
    )
    if not indicator.isEmpty():
        return indicator.size()
    return QSize(
        max(1, style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, view)),
        max(1, style.pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight, None, view)),
    )


def spectrum_colour_icon(view, colour: str) -> QIcon:
    """Draw a swatch using Qt's native icon/decoration layout."""
    size = view.iconSize()
    width, height = max(1, size.width()), max(1, size.height())
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(view.palette().color(view.foregroundRole()))
    painter.setBrush(QColor(colour))
    painter.drawRect(0, 0, width - 1, height - 1)
    painter.end()
    icon = QIcon()
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Selected, QIcon.Mode.Active, QIcon.Mode.Disabled):
        icon.addPixmap(pixmap, mode)
    return icon


def attach_note(item, project, kind, object_id, curve_id="", *, column=None):
    entry = project.notebook.descriptions.get(description_key(kind, object_id, curve_id))
    if not entry or not entry.text.strip():
        return
    ref = (kind, object_id, curve_id)
    icon = vector_icon("laboratory-notebook.svg")
    if column is None:
        item.setIcon(icon)
        item.setData(NOTE_ROLE, ref)
    else:
        item.setIcon(column, icon)
        item.setData(column, NOTE_ROLE, ref)


class NoteIndicatorDelegate(QStyledItemDelegate):
    def __init__(self, view, callback):
        super().__init__(view)
        self.view, self.callback = view, callback
        self._pressed_swatch = None
        view.viewport().installEventFilter(self)

    def note_rect(self, index):
        option = QStyleOptionViewItem()
        self.view.initViewItemOption(option)
        self.initStyleOption(option, index)
        option.rect = self.view.visualRect(index)
        option.widget = self.view
        return self.view.style().subElementRect(QStyle.SubElement.SE_ItemViewItemDecoration, option, self.view)

    @staticmethod
    def _swatch_curve_id(index):
        if not index.isValid() or index.column() != 0:
            return None
        metadata = index.siblingAtColumn(1).data(Qt.ItemDataRole.UserRole)
        if metadata and metadata[0] == "curve":
            return str(metadata[1])
        return None

    def helpEvent(self, event, view, option, index):
        text = index.data(CHECKBOX_TOOLTIP_ROLE)
        if text and event.type() == QEvent.Type.ToolTip:
            self.initStyleOption(option, index)
            checkbox = view.style().subElementRect(
                QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, view
            )
            if checkbox.contains(event.pos()):
                QToolTip.showText(event.globalPos(), text, view.viewport(), checkbox)
                return True
        return super().helpEvent(event, view, option, index)

    def eventFilter(self, watched, event):
        view = getattr(self, "view", None)
        if view is None or not isValid(view) or watched is not view.viewport():
            return super().eventFilter(watched, event)

        kind = event.type()
        if kind in (QEvent.Type.UngrabMouse, QEvent.Type.Hide):
            self._pressed_swatch = None
        if kind == QEvent.Type.MouseMove and self._pressed_swatch is not None:
            # This press belongs to the swatch, including movement over adjacent cells.
            return True
        if (kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease)
                and event.button() == Qt.MouseButton.LeftButton):
            point = event.position()
            position = QPoint(floor(point.x()), floor(point.y()))
            if kind != QEvent.Type.MouseButtonRelease:
                self._pressed_swatch = None
                index = self.view.indexAt(position)
                if self._swatch_curve_id(index) is not None and self.note_rect(index).contains(position):
                    self._pressed_swatch = QPersistentModelIndex(index), position
                    return True
                ref = index.data(NOTE_ROLE)
                if kind == QEvent.Type.MouseButtonPress and ref and self.note_rect(index).contains(position):
                    self.callback(ref)
                    return True
            elif self._pressed_swatch is not None:
                self._release_swatch(position)
                return True
        return super().eventFilter(watched, event)

    def _release_swatch(self, position):
        pressed, origin = self._pressed_swatch
        self._pressed_swatch = None
        index = QModelIndex(pressed)
        curve_id = self._swatch_curve_id(index)
        if curve_id is None or not self.view.viewport().rect().contains(position):
            return
        rect = self.note_rect(index)
        # A small slip just outside the square still belongs to the captured click.
        if rect.contains(position) or (
            rect.contains(origin) and (position - origin).manhattanLength() < QApplication.startDragDistance()
        ):
            self.view.curveColourRequested.emit(curve_id)
