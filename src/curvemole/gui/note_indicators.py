"""Reusable clickable note decorations for item views."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from curvemole.core.notebook import description_key
from curvemole.gui.icons import vector_icon

NOTE_ROLE = int(Qt.ItemDataRole.UserRole) + 20


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
        self.initStyleOption(option, index)
        option.rect = self.view.visualRect(index)
        option.widget = self.view
        return self.view.style().subElementRect(QStyle.SubElement.SE_ItemViewItemDecoration, option, self.view)

    def eventFilter(self, watched, event):
        if (watched is self.view.viewport()
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton):
            index = self.view.indexAt(event.position().toPoint())
            ref = index.data(NOTE_ROLE)
            if ref and self.note_rect(index).contains(event.position().toPoint()):
                self.callback(ref)
                return True
        return super().eventFilter(watched, event)
