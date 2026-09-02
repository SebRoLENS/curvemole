from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

import pyqtgraph as pg
from PySide6.QtGui import QPen
from PySide6.QtWidgets import QApplication

from curvemole.gui.app import _optimise_plot_data_item


def test_dense_line_uses_peak_downsampling_and_clip_to_view() -> None:
    app = QApplication.instance() or QApplication([])
    widget = pg.PlotWidget()
    x = np.linspace(400.0, 4000.0, 12000)
    y = np.sin(x / 25.0)
    item = widget.plot(x, y, pen=pg.mkPen("#336699", width=2.0))

    _optimise_plot_data_item(item, adaptive=True)

    assert item.opts["autoDownsample"] is True
    assert item.opts["downsampleMethod"] == "peak"
    assert item.opts["clipToView"] is True
    pen = item.opts["pen"]
    assert isinstance(pen, QPen)
    assert pen.widthF() == pytest.approx(1.0)
    np.testing.assert_array_equal(x, np.linspace(400.0, 4000.0, 12000))
    widget.close()
    app.processEvents()


def test_single_view_keeps_full_resolution_but_clips_visible_range() -> None:
    app = QApplication.instance() or QApplication([])
    widget = pg.PlotWidget()
    x = np.linspace(0.0, 100.0, 5000)
    y = np.cos(x)
    item = widget.plot(x, y, pen=pg.mkPen("#224466", width=1.35))

    _optimise_plot_data_item(item, adaptive=False)

    assert item.opts["autoDownsample"] is False
    assert item.opts["downsample"] == 1
    assert item.opts["clipToView"] is True
    assert item.opts["pen"].widthF() == pytest.approx(1.35)
    widget.close()
    app.processEvents()


def test_descending_spectrum_is_reversed_only_for_display() -> None:
    app = QApplication.instance() or QApplication([])
    widget = pg.PlotWidget()
    source_x = np.linspace(4000.0, 400.0, 6000)
    source_y = np.arange(source_x.size, dtype=float)
    x_copy = source_x.copy()
    y_copy = source_y.copy()
    item = widget.plot(source_x, source_y, pen=pg.mkPen("#112233", width=1.0))

    _optimise_plot_data_item(item, adaptive=True)

    displayed_x, displayed_y = item.getOriginalDataset()
    assert displayed_x is not None and displayed_y is not None
    assert np.all(np.diff(displayed_x) >= 0)
    np.testing.assert_array_equal(displayed_y, source_y[::-1])
    np.testing.assert_array_equal(source_x, x_copy)
    np.testing.assert_array_equal(source_y, y_copy)
    assert item.opts["clipToView"] is True
    widget.close()
    app.processEvents()


def test_non_monotonic_line_falls_back_safely() -> None:
    app = QApplication.instance() or QApplication([])
    widget = pg.PlotWidget()
    x = np.array([0.0, 2.0, 1.0, 3.0])
    y = np.array([0.0, 1.0, 0.5, 1.5])
    item = widget.plot(x, y, pen=pg.mkPen("#445566", width=2.0))

    _optimise_plot_data_item(item, adaptive=True)

    assert item.opts["clipToView"] is False
    assert item.opts["autoDownsample"] is False
    np.testing.assert_array_equal(item.xData, x)
    widget.close()
    app.processEvents()
