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
