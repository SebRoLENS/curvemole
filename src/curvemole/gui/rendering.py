"""Shared pixel-aware rendering for loaded spectra and import previews."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QPen

_ADAPTIVE_RENDER_MIN_POINTS = 1500


def _normalise_display_x(item: pg.PlotDataItem) -> bool:
    """Ensure monotonic display X data is ascending so clip-to-view is safe."""
    x_data, y_data = item.getOriginalDataset()
    if x_data is None or y_data is None or len(x_data) < 2:
        return False
    x = np.asarray(x_data)
    if not np.all(np.isfinite(x)):
        return False
    delta = np.diff(x)
    if np.all(delta >= 0) and np.any(delta > 0):
        return True
    if np.all(delta <= 0) and np.any(delta < 0):
        item.setData(x=x[::-1], y=np.asarray(y_data)[::-1])
        return True
    return False


def _optimise_plot_data_item(item: pg.PlotDataItem, *, adaptive: bool) -> None:
    """Clip visible data and thin dense lines or symbols without changing source data."""
    has_line = item.opts.get("pen") is not None
    has_symbols = item.opts.get("symbol") is not None
    if not has_line and not has_symbols:
        return
    x_data, _ = item.getOriginalDataset()
    if x_data is None:
        return
    monotonic = _normalise_display_x(item)
    item.setClipToView(monotonic)
    use_downsampling = (adaptive or has_symbols) and monotonic and len(x_data) >= _ADAPTIVE_RENDER_MIN_POINTS
    item.setDownsampling(
        ds=None if use_downsampling else 1,
        auto=use_downsampling,
        method="subsample" if has_symbols else "peak",
    )
    if adaptive and has_line:
        pen = item.opts.get("pen")
        if isinstance(pen, QPen) and not np.isclose(pen.widthF(), 1.0):
            fast_pen = QPen(pen)
            fast_pen.setWidthF(1.0)
            item.setPen(fast_pen)


def _split_dense_symbols(plot: pg.PlotItem, item: pg.PlotDataItem) -> pg.PlotDataItem | None:
    """Keep peak-preserving line reduction separate from real sampled markers."""
    if item.opts.get("pen") is None or item.opts.get("symbol") is None:
        return None
    x, y = item.getOriginalDataset()
    if x is None or len(x) < _ADAPTIVE_RENDER_MIN_POINTS:
        return None
    symbols = pg.PlotDataItem(
        x, y, pen=None, symbol=item.opts["symbol"],
        symbolSize=item.opts["symbolSize"],
        symbolPen=item.opts["symbolPen"],
        symbolBrush=item.opts["symbolBrush"],
    )
    item.setSymbol(None)
    plot.addItem(symbols, ignoreBounds=True)
    _optimise_plot_data_item(symbols, adaptive=True)
    return symbols

