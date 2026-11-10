"""Keep Autoscale consistent when the active data item is changed with the mouse."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QTreeWidgetItem

from curvemole.gui.main_window import MainWindow


def _apply_clicked_data_autoscale(window: MainWindow, kind: str, item_id: str) -> None:
    workspace = window.plot_workspace
    if window._session_finished or not workspace.autoscale_toggle.isChecked():
        return
    if kind == "series":
        if workspace._active_series_id == item_id:
            workspace._apply_autoscale(series_id=item_id)
    elif window.active_curve_id == item_id:
        workspace._apply_autoscale()


def _data_item_clicked(
    window: MainWindow,
    item: QTreeWidgetItem,
    _column: int,
) -> None:
    metadata = item.data(1, Qt.ItemDataRole.UserRole)
    if not metadata or metadata[0] not in {"series", "curve"}:
        return
    kind, item_id = metadata[0], str(metadata[1])

    # QTreeWidget can emit current/selection signals in a different order for
    # mouse interaction than for keyboard navigation. Run after the click event
    # has finished so active-curve changes and plot refreshes cannot overwrite
    # the requested autoscale.
    QTimer.singleShot(
        0,
        lambda: _apply_clicked_data_autoscale(window, kind, item_id),
    )


def _install() -> None:
    original = MainWindow._connect_signals
    if getattr(original, "_curvemole_mouse_autoscale", False):
        return

    def connect_signals(window: MainWindow) -> None:
        original(window)
        window.curve_tree.itemClicked.connect(
            lambda item, column, window=window: _data_item_clicked(window, item, column)
        )

    connect_signals._curvemole_mouse_autoscale = True  # type: ignore[attr-defined]
    MainWindow._connect_signals = connect_signals


_install()
