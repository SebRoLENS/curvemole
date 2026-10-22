"""Experimental error bars as finite line segments, including logarithmic views."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg


def y_error_widths(curve):
    if curve.current_error_y_minus is not None:
        return curve.current_error_y_minus, curve.current_error_y_plus
    if curve.current_sigma_y is not None:
        return curve.current_sigma_y, curve.current_sigma_y
    return None


def error_bar_item(curve, x, y, valid, colour):
    """Plot original CI half-widths (or legacy 1-sigma), never fit-scale widths."""
    widths = y_error_widths(curve)
    if widths is None and curve.current_sigma_x is None:
        return None
    x, y, valid = np.asarray(x), np.asarray(y), np.asarray(valid).copy()
    if len(x) > 4000:
        return DenseErrorBars(curve, x, y, valid, colour)
    segments_x, segments_y = [], []
    finite_x = np.sort(np.unique(x[np.isfinite(x)]))
    spacing = np.diff(finite_x)
    cap = float(np.median(spacing)) * .2 if len(spacing) else .01
    if widths is not None:
        minus, plus = widths
        keep = valid & np.isfinite(minus) & np.isfinite(plus) & (minus > 0) & (plus > 0)
        xx, yy, low, high = x[keep], y[keep], y[keep] - minus[keep], y[keep] + plus[keep]
        gap = np.full(len(xx), np.nan)
        segments_x.append(np.column_stack((xx, xx, gap, xx-cap, xx+cap, gap, xx-cap, xx+cap, gap)).ravel())
        segments_y.append(np.column_stack((low, high, gap, low, low, gap, high, high, gap)).ravel())
    if curve.current_sigma_x is not None:
        sx = curve.current_sigma_x
        keep = valid & np.isfinite(sx) & (sx > 0)
        xx, yy = x[keep], y[keep]
        gap = np.full(len(xx), np.nan)
        segments_x.append(np.column_stack((xx-sx[keep], xx+sx[keep], gap)).ravel())
        segments_y.append(np.column_stack((yy, yy, gap)).ravel())
    if not segments_x or not any(len(values) for values in segments_x):
        return None
    item = pg.PlotDataItem(np.concatenate(segments_x), np.concatenate(segments_y),
                          pen=pg.mkPen(colour, width=1), connect="finite")
    item.setZValue(1)
    return item


class DenseErrorBars(pg.PlotDataItem):
    """Pixel-bin envelopes preserve uncertainty extrema while bounding geometry."""

    def __init__(self, curve, x, y, valid, colour):
        self._ready = False
        self._updating = False
        self._source_x, self._source_y = x, y
        widths = y_error_widths(curve)
        self._low = y if widths is None else y - widths[0]
        self._high = y if widths is None else y + widths[1]
        sx = curve.current_sigma_x
        self._left = x if sx is None else x - sx
        self._right = x if sx is None else x + sx
        self._valid = valid & np.isfinite(x) & np.isfinite(y)
        for array in (self._low, self._high, self._left, self._right):
            self._valid &= np.isfinite(array)
        self._has_y, self._has_x = widths is not None, sx is not None
        self._bounds = ((float(np.min(self._left[self._valid])), float(np.max(self._right[self._valid]))),
                        (float(np.min(self._low[self._valid])), float(np.max(self._high[self._valid])))) if np.any(self._valid) else ((0., 1.), (0., 1.))
        super().__init__(pen=pg.mkPen(colour, width=1), connect="finite")
        self.setZValue(1)
        self._ready = True
        self._rebuild()

    def dataBounds(self, ax, frac=1.0, orthoRange=None):
        if getattr(self, "_ready", False):
            bounds = np.asarray(self._bounds[ax])
            if self.opts["logMode"][ax]:
                positive = bounds[bounds > 0]
                if not len(positive):
                    return (None, None)
                bounds = np.log10(positive)
            return float(bounds.min()), float(bounds.max())
        return super().dataBounds(ax, frac, orthoRange)

    def viewRangeChanged(self, vb=None, ranges=None, changed=None):
        super().viewRangeChanged(vb, ranges, changed)
        if getattr(self, "_ready", False):
            self._rebuild()

    def _rebuild(self):
        if self._updating:
            return
        self._updating = True
        try:
            view = self.getViewBox()
            pixels = max(1, int(view.width())) if view is not None else 1000
            lower, upper = view.viewRange()[0] if view is not None else self._bounds[0]
            display_x = self._source_x
            if self.opts["logMode"][0]:
                with np.errstate(divide="ignore", invalid="ignore"):
                    display_x = np.log10(display_x)
            visible = self._valid & (display_x >= lower) & (display_x <= upper)
            indices = np.flatnonzero(visible)
            if not len(indices):
                self.setData([], [])
                return
            # Keep individual samples at low density. At high density display
            # the union of every interval in each pixel, never a smaller error.
            bins = np.clip(((display_x[indices] - lower) / max(upper - lower, 1e-300) * pixels).astype(int), 0, pixels - 1)
            order = np.argsort(bins, kind="stable")
            indices, bins = indices[order], bins[order]
            starts = np.r_[0, np.flatnonzero(np.diff(bins)) + 1]
            if len(indices) <= pixels:
                starts = np.arange(len(indices))
            low = np.minimum.reduceat(self._low[indices], starts)
            high = np.maximum.reduceat(self._high[indices], starts)
            left = np.minimum.reduceat(self._left[indices], starts)
            right = np.maximum.reduceat(self._right[indices], starts)
            xx = (left + right) / 2
            yy = (low + high) / 2
            gap = np.full(len(xx), np.nan)
            xs, ys = [], []
            if self._has_y:
                xs.append(np.column_stack((xx, xx, gap)).ravel())
                ys.append(np.column_stack((low, high, gap)).ravel())
            if self._has_x:
                xs.append(np.column_stack((left, right, gap)).ravel())
                ys.append(np.column_stack((yy, yy, gap)).ravel())
            self.setData(np.concatenate(xs), np.concatenate(ys))
        finally:
            self._updating = False
