"""Interpretable residual diagnostics; no opaque aggregate score."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from curvemole.core.data import DetectorPixelRows


@dataclass(slots=True)
class ResidualDiagnostics:
    standardised: np.ndarray
    histogram_counts: np.ndarray
    histogram_edges: np.ndarray
    qq_theoretical: np.ndarray
    qq_observed: np.ndarray
    autocorrelation: np.ndarray
    durbin_watson: float | None
    outlier_indices: np.ndarray
    warnings: list[str]

    def summary(self) -> dict[str, Any]:
        return {
            "durbin_watson": self.durbin_watson,
            "outlier_count": int(len(self.outlier_indices)),
            "lag1_autocorrelation": (
                float(self.autocorrelation[1]) if len(self.autocorrelation) > 1 else None
            ),
            "warnings": self.warnings,
        }


def _scale_residuals(values):
    # An exact power-of-two rescaling keeps sums of squares in float64 range.
    exponent = math.frexp(float(np.max(np.abs(values))))[1]
    return np.ldexp(values, -exponent), exponent


def _centred(scaled):
    # Subtract a nearby origin first, including for exactly constant series.
    centred = scaled - (scaled.min() + scaled.max()) / 2
    centred -= centred.mean()
    return centred


def _lag_limit(size, max_lag=None):
    if max_lag is None:
        return max(1, min(100, size // 4))
    if not isinstance(max_lag, (int, np.integer)) or max_lag < 0:
        raise ValueError("max_lag must be a nonnegative integer")
    return min(max_lag, size - 1)


_SPACING_WINDOW = 9
_SPACING_RATIO = 2.5


def _local_step_scale(steps, eligible):
    """Median absolute X step in a small centred window, ignoring ineligible steps."""
    half = _SPACING_WINDOW // 2
    magnitudes = np.where(eligible, np.abs(steps), np.nan)
    padded = np.pad(magnitudes, half, constant_values=np.nan)
    windows = np.lib.stride_tricks.sliding_window_view(padded, _SPACING_WINDOW)
    with np.errstate(all="ignore"):
        valid = np.isfinite(windows)
        counts = valid.sum(axis=1)
        ordered = np.sort(np.where(valid, windows, np.inf), axis=1)
        lower = ordered[np.arange(len(steps)), np.maximum(counts - 1, 0) // 2]
        upper = ordered[np.arange(len(steps)), counts // 2]
        scale = (lower + upper) / 2
    return np.where(counts > 0, scale, np.nan)


def contiguous_residual_segments(indices, x):
    """Split residuals at original-row gaps and, for other data, at X discontinuities.

    Calibrated detector axes (Raman shift, wavelength, wavenumber) are smooth but
    never exactly uniform, and X values read from text files are rounded. Rows
    therefore stay together while the X step keeps the dominant direction and is
    within a factor of the *local* step; only real jumps, reversals and
    duplicate/invalid X values break a segment.
    """
    rows = np.asarray(indices)
    neighbours = np.diff(rows) == 1
    if not isinstance(indices, DetectorPixelRows) and len(neighbours):
        steps = np.diff(np.asarray(x, dtype=float))
        eligible = neighbours & np.isfinite(steps) & (steps != 0)
        if np.any(eligible):
            direction = np.sign(np.median(steps[eligible]))
            eligible &= np.sign(steps) == direction
        if np.any(eligible):
            scale = _local_step_scale(steps, eligible)
            with np.errstate(all="ignore"):
                ratio = np.abs(steps) / scale
            regular = (ratio <= _SPACING_RATIO) & (ratio >= 1 / _SPACING_RATIO)
            neighbours &= eligible & regular
        else:
            neighbours[:] = False
    starts = np.r_[0, np.flatnonzero(~neighbours) + 1, len(rows)]
    return tuple(slice(int(start), int(stop)) for start, stop in zip(starts[:-1], starts[1:], strict=True))


def _lag_correlations(demeaned, limit, segments=None):
    denominator = np.dot(demeaned, demeaned)
    parts = (demeaned,) if segments is None else tuple(demeaned[segment] for segment in segments)
    for lag in range(1, limit + 1):
        numerator = sum(np.dot(part[:-lag], part[lag:]) for part in parts if len(part) > lag)
        yield numerator / denominator if denominator else np.nan


def residual_diagnostics(
    residual: np.ndarray,
    *,
    max_lag: int | None = None,
    histogram_bins: int | str = "auto",
    indices: np.ndarray | None = None,
    x: np.ndarray | None = None,
) -> ResidualDiagnostics:
    values = np.asarray(residual, dtype=float).reshape(-1)
    input_count = len(values)
    finite_indices = np.flatnonzero(np.isfinite(values))
    values = values[finite_indices]
    warnings: list[str] = []
    if len(values) < 3:
        empty = np.array([], dtype=float)
        return ResidualDiagnostics(
            empty, empty.astype(int), empty, empty, empty, empty, None, np.array([], dtype=int),
            ["At least three finite residuals are required for diagnostics."],
        )
    scaled, exponent = _scale_residuals(values)
    demeaned = _centred(scaled)
    scale = np.sqrt(np.dot(demeaned, demeaned) / (len(values) - 1))
    standardised = demeaned / scale if scale else np.zeros_like(values)
    if isinstance(histogram_bins, (str, int, np.integer)) and (
        scale or values[0] - .5 == values[0] + .5
    ):
        # At large constant values NumPy's default interval of ±0.5 collapses.
        bounds = None if scale else sorted((scaled[0] / 2, scaled[0]))
        counts, edges = np.histogram(scaled, bins=histogram_bins, range=bounds)
        edges = np.ldexp(edges, exponent)
    else:
        counts, edges = np.histogram(values, bins=histogram_bins)
    ordered = np.sort(standardised)
    probabilities = (np.arange(len(ordered)) + 0.5) / len(ordered)
    from scipy.special import ndtri
    theoretical = ndtri(probabilities)
    segments = None
    if x is not None or indices is not None or len(finite_indices) != input_count:
        rows = finite_indices if indices is None else np.asanyarray(indices)[finite_indices]
        coordinates = rows if x is None else np.asarray(x)[finite_indices]
        segments = contiguous_residual_segments(rows, coordinates)
    lengths = [len(values)] if segments is None else [segment.stop - segment.start for segment in segments]
    lag_limit = min(_lag_limit(len(values), max_lag), max(lengths) - 1)
    autocorrelation = np.ones(lag_limit + 1)
    autocorrelation[1:] = list(_lag_correlations(demeaned, lag_limit, segments))
    parts = (scaled,) if segments is None else tuple(scaled[segment] for segment in segments)
    differences = [np.diff(part) for part in parts if len(part) > 1]
    total = float(np.dot(scaled, scaled))
    durbin_watson = sum(float(np.dot(part, part)) for part in differences) / total if total and differences else None
    if len(parts) > 1:
        if isinstance(indices, DetectorPixelRows):
            warnings.append("Lag statistics skip gaps in the detector grid.")
        else:
            warnings.append("Lag statistics skip gaps and changes in X spacing.")
    outlier_local = np.flatnonzero(np.abs(standardised) >= 3)
    outlier_indices = finite_indices[outlier_local]
    if len(outlier_indices):
        warnings.append(f"{len(outlier_indices)} potential |standardised residual| >= 3 outlier(s).")
    if lag_limit:
        pairs = np.array([sum(max(0, length - lag) for length in lengths)
                          for lag in range(1, lag_limit + 1)])
        # Under white noise Var(r_k) is approximately pairs / N² for this
        # pooled estimator. Adjust the point thresholds for testing many lags.
        significance = ndtri(1 - .025 / lag_limit) * np.sqrt(pairs) / len(values)
        if np.any((pairs >= 20) & (np.abs(autocorrelation[1:]) > significance)):
            warnings.append("Residual autocorrelation exceeds the multiple-lag 95% white-noise threshold.")
    return ResidualDiagnostics(
        standardised,
        counts,
        edges,
        theoretical,
        ordered,
        autocorrelation,
        durbin_watson,
        outlier_indices,
        warnings,
    )


def estimate_block_length(residual: np.ndarray, segments=None) -> int:
    values = np.asarray(residual, dtype=float).reshape(-1)
    finite = values[np.isfinite(values)]
    if len(finite) < 3:
        return 1
    scaled, _ = _scale_residuals(finite)
    limit = min(_lag_limit(len(finite)), max(
        (segment.stop - segment.start - 1 for segment in segments), default=len(finite) - 1,
    )) if segments is not None else _lag_limit(len(finite))
    threshold = math.exp(-1)
    for lag, correlation in enumerate(_lag_correlations(_centred(scaled), limit, segments), 1):
        if abs(correlation) < threshold:
            return lag
    return max(1, min(len(values) // 10, limit))
