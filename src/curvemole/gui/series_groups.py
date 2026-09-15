"""Shared, theme-aware hierarchy and scope controls for spectrum selectors."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QRadioButton


def style_heading(item, widget, *, series=True):
    font = item.font()
    font.setBold(True)
    item.setFont(font)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
    if series:
        dark = widget.palette().color(QPalette.ColorRole.Base).lightness() < 128
        item.setForeground(QColor("#66B5FF" if dark else "#075B9A"))
    item.setSizeHint(QSize(0, widget.fontMetrics().height() + (14 if series else 8)))
    item.setBackground(widget.palette().color(QPalette.ColorRole.AlternateBase))


def add_scope(dialog, layout, project, source_id, callback):
    source_id = source_id or (project.curves[0].id if project.curves else None)
    dialog.scope_series_id = project.dataset.series_for(source_id).id if source_id else None
    row = QHBoxLayout()
    row.addWidget(QLabel(dialog.tr("Show:")))
    dialog.active_series = QRadioButton(dialog.tr("Active series"))
    dialog.all_series = QRadioButton(dialog.tr("All series"))
    dialog.scope_group = QButtonGroup(dialog)
    for button in (dialog.active_series, dialog.all_series):
        dialog.scope_group.addButton(button)
        row.addWidget(button)
    dialog.active_series.setChecked(True)
    row.addStretch(1)
    layout.addLayout(row)
    dialog.scope_group.buttonToggled.connect(lambda button, checked: callback() if checked else None)


# Shared picker also used by every Calculator operation, including restore.
from PySide6.QtWidgets import (  # noqa: E402
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


class SpectrumSelectionDialog(QDialog):
    def __init__(self, project, source_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Choose spectra — Data Calculator"))
        self.resize(560, 540)
        layout = QVBoxLayout(self)
        add_scope(self, layout, project, source_id, self._filter_series)
        self.targets = QListWidget()
        self.targets.setAlternatingRowColors(True)
        self.targets.setSpacing(3)
        self._series = {}
        for series in project.dataset.series:
            heading = QListWidgetItem(series.name, self.targets)
            style_heading(heading, self.targets)
            self._series[self.targets.count() - 1] = series.id
            for curve in series.curves:
                item = QListWidgetItem("    " + curve.name, self.targets)
                item.setData(Qt.ItemDataRole.UserRole, curve.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if curve.id == source_id else Qt.CheckState.Unchecked)
                self._series[self.targets.count() - 1] = series.id
        layout.addWidget(self.targets)
        row = QHBoxLayout()
        for label, checked in ((self.tr("Select all shown"), True), (self.tr("Deselect all shown"), False)):
            button = QPushButton(label)
            button.clicked.connect(lambda _, value=checked: self._check_shown(value))
            row.addWidget(button)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._filter_series()

    def _filter_series(self):
        for row, series_id in self._series.items():
            self.targets.item(row).setHidden(not self.all_series.isChecked() and series_id != self.scope_series_id)

    def _check_shown(self, checked):
        for row in range(self.targets.count()):
            item = self.targets.item(row)
            if not item.isHidden() and item.data(Qt.ItemDataRole.UserRole):
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def selected_ids(self):
        return [self.targets.item(row).data(Qt.ItemDataRole.UserRole)
                for row in range(self.targets.count())
                if not self.targets.item(row).isHidden()
                and self.targets.item(row).checkState() == Qt.CheckState.Checked
                and self.targets.item(row).data(Qt.ItemDataRole.UserRole)]
