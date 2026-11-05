"""Compact column selectors with a searchable popup for large tables."""

from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QListView,
    QStyledItemDelegate,
    QVBoxLayout,
)

from curvemole.gui.windowing import transient_widget

COLUMN_SEARCH_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class _ColumnDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        option.text = index.data(COLUMN_SEARCH_ROLE) or option.text


def choose_column(parent, model, current=-1) -> int | None:
    """Select a real column once, filtering by code, axis or original name."""
    if not model.rowCount():
        return None
    with transient_widget(QDialog(parent, Qt.WindowType.Popup)) as popup:
        popup.setWindowTitle(parent.tr("Choose a column"))
        layout = QVBoxLayout(popup)
        search = QLineEdit(popup)
        search.setPlaceholderText(parent.tr("Search by column code or name…"))
        layout.addWidget(search)
        proxy = QSortFilterProxyModel(popup)
        proxy.setSourceModel(model)
        proxy.setFilterRole(COLUMN_SEARCH_ROLE)
        proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        view = QListView(popup)
        view.setModel(proxy)
        view.setItemDelegate(_ColumnDelegate(view))
        view.setUniformItemSizes(True)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(view)
        empty = QLabel(parent.tr("No matching columns."), popup)
        empty.hide()
        layout.addWidget(empty)
        selected = None

        def select(index):
            nonlocal selected
            if index.isValid():
                selected = proxy.mapToSource(index).row()
                popup.accept()

        def filter_columns(text):
            proxy.setFilterFixedString(text)
            view.setCurrentIndex(proxy.index(0, 0))
            empty.setVisible(proxy.rowCount() == 0)

        def accept_current():
            select(view.currentIndex())

        def focus_results():
            view.setFocus()

        # Down from the search box enters the filtered list; typing keeps the
        # search field focused, Enter accepts, and Escape dismisses the popup.
        from PySide6.QtGui import QKeySequence, QShortcut
        down = QShortcut(QKeySequence(Qt.Key.Key_Down), search)
        down.setContext(Qt.ShortcutContext.WidgetShortcut)
        down.activated.connect(focus_results)
        search.textChanged.connect(filter_columns)
        search.returnPressed.connect(accept_current)
        view.clicked.connect(select)
        view.activated.connect(select)
        initial = proxy.mapFromSource(model.index(max(0, current), 0))
        view.setCurrentIndex(initial)
        view.scrollTo(initial)

        screen = parent.screen().availableGeometry()
        popup.resize(min(max(parent.width(), 380), screen.width()),
                     min(360, screen.height()))
        anchor = parent.mapToGlobal(parent.rect().bottomLeft())
        left = max(screen.left(), min(anchor.x(), screen.right() - popup.width() + 1))
        top = anchor.y()
        if top + popup.height() > screen.bottom():
            top = parent.mapToGlobal(parent.rect().topLeft()).y() - popup.height()
        popup.move(left, max(screen.top(), top))
        search.setFocus()
        if popup.exec() == QDialog.DialogCode.Accepted:
            return selected
    return None


class ColumnSelector(QComboBox):
    """Display only cN (axis); show original names in the searchable popup."""

    def showPopup(self) -> None:
        selected = choose_column(self, self.model(), self.currentIndex())
        if selected is not None:
            self.setCurrentIndex(selected)

    def add_column(self, text: str, key: str, original_name: str) -> None:
        self.addItem(text, key)
        details = f"{text} — {original_name}" if original_name else text
        index = self.count() - 1
        self.setItemData(index, details, COLUMN_SEARCH_ROLE)
        self.setItemData(index, details, Qt.ItemDataRole.ToolTipRole)
