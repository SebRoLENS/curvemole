"""Read-only worksheet cells formatted on demand from existing numeric arrays."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, Qt

from curvemole.core.data import Curve


class WorksheetModel(QAbstractTableModel):
    """Keep column references instead of one Qt item/string per data cell."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = 0
        self._headings = []
        self._columns = []

    def set_curve(self, curve: Curve | None, *, maximum_rows: int = 100_000) -> None:
        self.beginResetModel()
        try:
            self._rows = min(len(curve), max(0, maximum_rows)) if curve is not None else 0
            self._columns = []
            if curve is None:
                return
            asymmetric = curve.current_error_y_minus is not None
            self._headings = (
                ["x", "y", "error −", "error +", "data confidence (%)", "weight", self.tr("masked")]
                if asymmetric else ["x", "y", "sigma_y", "weight", self.tr("masked")]
            )
            self._columns = [curve.x, curve.y]
            if asymmetric:
                self._columns.extend([curve.current_error_y_minus, curve.current_error_y_plus,
                                      curve.error_confidence_level * 100])
            else:
                self._columns.append(curve.current_sigma_y)
            self._columns.extend([curve.current_weights, curve.effective_mask])
        finally:
            self.endResetModel()

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else self._rows

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self._headings)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if (role != Qt.ItemDataRole.DisplayRole or not index.isValid()
                or not 0 <= index.row() < self._rows
                or not 0 <= index.column() < len(self._columns)):
            return None
        column = self._columns[index.column()]
        if column is None:
            return ""
        value = column if isinstance(column, (int, float)) else column[index.row()]
        return str(value)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._headings[section] if 0 <= section < len(self._headings) else None
        return str(section + 1) if 0 <= section < self._rows else None
