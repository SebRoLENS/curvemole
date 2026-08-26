"""Interpretable residual diagnostics; no opaque aggregate score."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import stats


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
    centre = float(np.mean(values))
    scale = float(np.std(values, ddof=1))
    standardised = (values - centre) / scale if scale > 0 else np.zeros_like(values)
    counts, edges = np.histogram(values, bins=histogram_bins)
    ordered = np.sort(standardised)
    probabilities = (np.arange(len(ordered)) + 0.5) / len(ordered)
    theoretical = stats.norm.ppf(probabilities)
    lag_limit = min(max_lag or max(1, min(100, len(values) // 4)), len(values) - 1)
    demeaned = values - centre
    denominator = float(np.dot(demeaned, demeaned))
    autocorrelation = np.ones(lag_limit + 1)
    if denominator > 0:
        for lag in range(1, lag_limit + 1):
            autocorrelation[lag] = float(np.dot(demeaned[:-lag], demeaned[lag:]) / denominator)
    else:
        autocorrelation[1:] = np.nan
    squared_difference = float(np.dot(np.diff(values), np.diff(values)))
    durbin_watson = squared_difference / float(np.dot(values, values)) if np.any(values) else None
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
    diagnostics = residual_diagnostics(residual)
    if len(diagnostics.autocorrelation) <= 1:
        return 1
    threshold = math.exp(-1)
    below = np.flatnonzero(np.abs(diagnostics.autocorrelation[1:]) < threshold)
    if below.size:
        return max(1, int(below[0] + 1))
    return max(1, min(len(residual) // 10, len(diagnostics.autocorrelation) - 1))
