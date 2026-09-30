"""Reusable clickable note decorations for item views."""

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QToolTip
from shiboken6 import isValid

from curvemole.core.notebook import description_key
from curvemole.gui.icons import vector_icon

NOTE_ROLE = int(Qt.ItemDataRole.UserRole) + 20
CHECKBOX_TOOLTIP_ROLE = int(Qt.ItemDataRole.UserRole) + 21


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
        view.viewport().installEventFilter(self)

    def note_rect(self, index):
        option = QStyleOptionViewItem()
        size = self.view.iconSize()
        option.decorationSize = size if size.isValid() else QSize(16, 16)
        self.initStyleOption(option, index)
        option.rect = self.view.visualRect(index)
        option.widget = self.view
        return self.view.style().subElementRect(QStyle.SubElement.SE_ItemViewItemDecoration, option, self.view)

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
        if (event.type() == QEvent.Type.MouseButtonPress
                and isValid(self.view)
                and watched is self.view.viewport()
                and event.button() == Qt.MouseButton.LeftButton):
            index = self.view.indexAt(event.position().toPoint())
            ref = index.data(NOTE_ROLE)
            if ref and self.note_rect(index).contains(event.position().toPoint()):
                self.callback(ref)
                return True
        return super().eventFilter(watched, event)
