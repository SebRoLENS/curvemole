"""Interpretable residual diagnostics; no opaque aggregate score."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


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


def _lag_correlations(demeaned, limit):
    denominator = np.dot(demeaned, demeaned)
    for lag in range(1, limit + 1):
        yield np.dot(demeaned[:-lag], demeaned[lag:]) / denominator if denominator else np.nan


def residual_diagnostics(
    residual: np.ndarray,
    *,
    max_lag: int | None = None,
    histogram_bins: int | str = "auto",
) -> ResidualDiagnostics:
    values = np.asarray(residual, dtype=float).reshape(-1)
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
    lag_limit = _lag_limit(len(values), max_lag)
    autocorrelation = np.ones(lag_limit + 1)
    autocorrelation[1:] = list(_lag_correlations(demeaned, lag_limit))
    differences = np.diff(scaled)
    total = float(np.dot(scaled, scaled))
    durbin_watson = float(np.dot(differences, differences)) / total if total else None
    outlier_local = np.flatnonzero(np.abs(standardised) >= 3)
    outlier_indices = finite_indices[outlier_local]
    if len(outlier_indices):
        warnings.append(f"{len(outlier_indices)} potential |standardised residual| >= 3 outlier(s).")
    significance = 1.96 / math.sqrt(len(values))
    if len(autocorrelation) > 1 and np.any(np.abs(autocorrelation[1:]) > significance):
        warnings.append("Residual autocorrelation exceeds the approximate 95% white-noise band.")
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


def estimate_block_length(residual: np.ndarray) -> int:
    values = np.asarray(residual, dtype=float).reshape(-1)
    finite = values[np.isfinite(values)]
    if len(finite) < 3:
        return 1
    scaled, _ = _scale_residuals(finite)
    limit = _lag_limit(len(finite))
    threshold = math.exp(-1)
    for lag, correlation in enumerate(_lag_correlations(_centred(scaled), limit), 1):
        if abs(correlation) < threshold:
            return lag
    return max(1, min(len(values) // 10, limit))
