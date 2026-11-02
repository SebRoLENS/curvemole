"""Discover mouse gestures and the keyboard bindings assigned to this window."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


def _label(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").split("\t")[0]


class ShortcutsDialog(QDialog):
    def __init__(self, window, mouse_text: str) -> None:
        super().__init__(window)
        self.setWindowTitle(self.tr("Shortcuts"))
        self.resize(960, 700)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs)

        self.mouse = QTextBrowser(self)
        self.mouse.setAccessibleName(self.tr("Mouse shortcuts by mode"))
        self.mouse.document().setDocumentMargin(16)
        self.mouse.document().setDefaultStyleSheet("td, th { padding: 6px; }")
        self.mouse.setMarkdown(mouse_text)
        self.tabs.addTab(self.mouse, self.tr("Mouse"))

        keyboard = QWidget(self)
        keyboard_layout = QVBoxLayout(keyboard)
        note = QLabel(self.tr(
            "Current bindings for menu, toolbar and loaded plugin commands, including commands "
            "that are temporarily unavailable. Plain keys do not interrupt typing; text editors "
            "keep their native selection, copy/paste and Undo/Redo shortcuts."
        ))
        note.setWordWrap(True)
        keyboard_layout.addWidget(note)
        self.search = QLineEdit(keyboard)
        self.search.setPlaceholderText(self.tr("Search commands, shortcuts or contexts…"))
        self.search.setAccessibleName(self.tr("Search keyboard shortcuts"))
        keyboard_layout.addWidget(self.search)

        manager = window._action_shortcuts
        manager.refresh()
        rows = []
        for command in (*manager.commands(), *manager.buttons()):
            sequences = command.shortcuts() if isinstance(command, QAction) else [command.shortcut()]
            keys = ", ".join(sequence.toString(QKeySequence.SequenceFormat.NativeText)
                             for sequence in sequences if not sequence.isEmpty())
            if keys:
                context = manager.identities.get(command, self.tr("Toolbar"))
                context = _label(context).replace("_toolbar", " toolbar").replace("/", " → ")
                rows.append((_label(command.text()), keys, context))
        for key, action, context in (
            ("Up", self.tr("Activate previous checked spectrum"), self.tr("Plot focus")),
            ("Down", self.tr("Activate next checked spectrum"), self.tr("Plot focus")),
            ("Esc", self.tr("Cancel placement or end data-point editing"), self.tr("Plot editing")),
            ("Return", self.tr("Finish placement after the minimum number of points"), self.tr("Quick Add placement")),
            ("Enter", self.tr("Finish placement after the minimum number of points"), self.tr("Quick Add placement")),
            ("Delete", self.tr("Delete selected experimental point"), self.tr("Edit data points")),
            ("Backspace", self.tr("Delete selected experimental point"), self.tr("Edit data points")),
            ("F2", self.tr("Rename selected editable item"), self.tr("Series / spectra tree")),
            ("F4", self.tr("Open selected function's composition menu"), self.tr("Function list")),
            ("Ctrl+F", self.tr("Find in the open help document"), self.tr("Help viewer")),
        ):
            rows.append((action, QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText), context))

        self.keyboard = QTableWidget(len(rows), 3, keyboard)
        self.keyboard.setAccessibleName(self.tr("Keyboard shortcuts"))
        self.keyboard.setHorizontalHeaderLabels([self.tr("Action"), self.tr("Shortcut"), self.tr("Context")])
        self.keyboard.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.keyboard.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.keyboard.verticalHeader().hide()
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.keyboard.setItem(row, column, item)
        self.keyboard.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.keyboard.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.keyboard.setSortingEnabled(True)
        self.keyboard.sortItems(0, Qt.SortOrder.AscendingOrder)
        keyboard_layout.addWidget(self.keyboard)
        self.search.textChanged.connect(self._filter_keyboard)
        self.keyboard.model().layoutChanged.connect(lambda: self._filter_keyboard(self.search.text()))
        self.tabs.addTab(keyboard, self.tr("Keyboard"))

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def _filter_keyboard(self, text: str) -> None:
        query = text.strip().casefold()
        for row in range(self.keyboard.rowCount()):
            visible = any(query in self.keyboard.item(row, column).text().casefold()
                          for column in range(self.keyboard.columnCount()))
            self.keyboard.setRowHidden(row, not visible)
