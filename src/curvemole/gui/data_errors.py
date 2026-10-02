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
