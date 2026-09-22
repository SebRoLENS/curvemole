"""Keep the compact plot controls aligned with experimental-data semantics."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QLabel

from curvemole.gui.plot import PlotWorkspace
from curvemole.gui.plot_appearance import normalize_plot_appearance

_ORIGINAL_INIT = PlotWorkspace.__init__


def _widgets(layout) -> list[Any]:
    result: list[Any] = []
    for index in range(layout.count()):
        widget = layout.itemAt(index).widget()
        if widget is not None:
            result.append(widget)
    return result


def _insert_before_stretch(layout, widget) -> None:
    layout.insertWidget(max(0, layout.count() - 1), widget)


def _sync_plot_style_control(self: PlotWorkspace) -> None:
    """Synchronise the quick style selector with imported-data rendering."""
    value = str(self._plot_appearance.get("data_style", "lines"))
    index = self.function_style_mode.findData(value)
    self.function_style_mode.blockSignals(True)
    self.function_style_mode.setCurrentIndex(index if index >= 0 else 0)
    self.function_style_mode.blockSignals(False)


def _plot_style_changed(self: PlotWorkspace, *_: Any) -> None:
    """Apply the quick style selector to experimental data, not fit functions."""
    value = self.function_style_mode.currentData()
    if value is None:
        return
    self._plot_appearance["data_style"] = str(value)
    self._plot_appearance = normalize_plot_appearance(self._plot_appearance)
    if self._project is not None:
        self._project.ui_state["plot_appearance"] = dict(self._plot_appearance)
    self.refresh()


def _plot_workspace_init(self: PlotWorkspace, *args: Any, **kwargs: Any) -> None:
    _ORIGINAL_INIT(self, *args, **kwargs)

    view_layout = self.view_controls.layout()
    display_row = view_layout.itemAt(0).layout()
    autoscale_row = view_layout.itemAt(1).layout()
    style_row = view_layout.itemAt(2).layout()
    offset_row = view_layout.itemAt(3).layout()

    # The quick selector is about the loaded experimental data. Keep the legacy
    # attribute as an internal compatibility alias while exposing the correct name.
    self.plot_style_mode = self.function_style_mode
    self.plot_style_mode.setToolTip(
        self.tr("Choose how imported data are drawn in the plot.")
    )
    for widget in _widgets(style_row):
        if isinstance(widget, QLabel) and widget.text() == self.tr("Functions:"):
            widget.setText(self.tr("Plot style:"))
            self.plot_style_label = widget
            break

    # Keep offsets on the same row as Display. The old labels are replaced so the
    # ordering stays explicit and independent from the previous offset-row layout.
    for widget in _widgets(offset_row):
        if isinstance(widget, QLabel) and widget is not self.coordinate_label:
            widget.hide()
    offset_row.removeWidget(self.x_offset)
    offset_row.removeWidget(self.y_offset)
    offset_row.removeWidget(self.coordinate_label)
    x_label = QLabel(self.tr("X offset:"), self.view_controls)
    y_label = QLabel(self.tr("Y offset:"), self.view_controls)
    _insert_before_stretch(display_row, x_label)
    _insert_before_stretch(display_row, self.x_offset)
    _insert_before_stretch(display_row, y_label)
    _insert_before_stretch(display_row, self.y_offset)
    display_row.addWidget(self.coordinate_label)
    self.x_offset_label = x_label
    self.y_offset_label = y_label

    # Residual visibility belongs with the other view-scaling controls.
    offset_row.removeWidget(self.residual_toggle)
    _insert_before_stretch(autoscale_row, self.residual_toggle)

    self.autoscale_toggle.setToolTip(
        self.tr("Automatically fit the experimental data whenever the active data item changes.")
    )


# Install semantic methods before __init__ is called so the signal connection made
# by PlotWorkspace.__init__ already targets the corrected data-style handler.
PlotWorkspace._sync_function_style_control = _sync_plot_style_control
PlotWorkspace._function_style_changed = _plot_style_changed
PlotWorkspace.__init__ = _plot_workspace_init
