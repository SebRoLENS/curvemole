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
    """Configure one line item for pixel-aware rendering without changing source data."""
    if item.opts.get("pen") is None:
        return
    x_data, _ = item.getOriginalDataset()
    if x_data is None:
        return
    monotonic = _normalise_display_x(item)
    item.setClipToView(monotonic)
    use_downsampling = adaptive and monotonic and len(x_data) >= _ADAPTIVE_RENDER_MIN_POINTS
    item.setDownsampling(
        ds=None if use_downsampling else 1,
        auto=use_downsampling,
        method="peak",
    )
    if adaptive:
        pen = item.opts.get("pen")
        if isinstance(pen, QPen) and not np.isclose(pen.widthF(), 1.0):
            fast_pen = QPen(pen)
            fast_pen.setWidthF(1.0)
            item.setPen(fast_pen)


