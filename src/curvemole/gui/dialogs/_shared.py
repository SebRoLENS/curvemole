"""Helpers shared by the dialogs."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QListWidget,
    QTableWidget,
)

from curvemole.gui.parameter_link import ParameterLinkDialog  # noqa: E402, F401


def _set_list_checked(widget: QListWidget, checked: bool) -> None:
    state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
    for index in range(widget.count()):
        item = widget.item(index)
        if not item.isHidden() and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            item.setCheckState(state)


def _set_table_checked(table: QTableWidget, column: int, checked: bool) -> None:
    state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
    for row in range(table.rowCount()):
        item = table.item(row, column)
        if not table.isRowHidden(row) and item is not None and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            item.setCheckState(state)


def _name_accept(buttons: QDialogButtonBox, text: str) -> None:
    """Name the accept button after its action instead of a generic "OK"."""
    button = buttons.button(QDialogButtonBox.StandardButton.Ok)
    if button is not None:
        button.setText(text)


def np_median(values: Any) -> float:
    import numpy as np

    return float(np.median(values))

