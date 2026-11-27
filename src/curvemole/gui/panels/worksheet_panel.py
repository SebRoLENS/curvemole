"""WorksheetPanel."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from curvemole.gui.worksheet import WorksheetModel


class WorksheetPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.label = QLabel(self.tr("No active curve"))
        self.table = QTableView()
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._model = WorksheetModel(self.table)
        self.table.setModel(self._model)
        layout.addWidget(self.label)
        layout.addWidget(self.table)

    def set_curve(self, curve: Any | None, *, maximum_rows: int = 100_000) -> None:
        self._model.set_curve(curve, maximum_rows=maximum_rows)
        if curve is None:
            self.label.setText(self.tr("No active curve"))
            return
        rows = self._model.rowCount()
        self.label.setText(
            f"{curve.name} — {rows}/{len(curve)} " + self.tr("rows shown")
        )

