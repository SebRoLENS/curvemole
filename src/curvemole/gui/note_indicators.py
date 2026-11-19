"""Reusable clickable note decorations for item views."""

from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QToolTip
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
    """Draw a passive swatch using Qt's native icon/decoration layout."""
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
        self._pressed_swatch_curve_id = None
        view.viewport().installEventFilter(self)

    def note_rect(self, index):
        option = QStyleOptionViewItem()
        size = self.view.iconSize()
        option.decorationSize = size if size.isValid() else QSize(16, 16)
        self.initStyleOption(option, index)
        option.rect = self.view.visualRect(index)
        option.widget = self.view
        return self.view.style().subElementRect(QStyle.SubElement.SE_ItemViewItemDecoration, option, self.view)

    def spectrum_swatch_curve_id(self, index, position):
        """Return the spectrum ID only for clicks on the colour icon."""
        if not index.isValid() or index.column() != 0:
            return None
        metadata = index.siblingAtColumn(1).data(Qt.ItemDataRole.UserRole)
        if metadata and metadata[0] == "curve" and self.note_rect(index).contains(position):
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
        if (event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease)
                and isValid(self.view)
                and watched is self.view.viewport()
                and event.button() == Qt.MouseButton.LeftButton):
            position = event.position().toPoint()
            index = self.view.indexAt(position)
            if event.type() == QEvent.Type.MouseButtonPress:
                self._pressed_swatch_curve_id = self.spectrum_swatch_curve_id(index, position)
                if self._pressed_swatch_curve_id is not None:
                    # Do not select the row or toggle its visibility checkbox.
                    return True
                ref = index.data(NOTE_ROLE)
                if ref and self.note_rect(index).contains(position):
                    self.callback(ref)
                    return True
            elif self._pressed_swatch_curve_id is not None:
                curve_id = self._pressed_swatch_curve_id
                self._pressed_swatch_curve_id = None
                if self.spectrum_swatch_curve_id(index, position) == curve_id:
                    self.view.curveColourRequested.emit(curve_id)
                return True
        return super().eventFilter(watched, event)
