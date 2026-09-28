"""Per-spectrum choice and asymmetric errors from recorded uncertainty analyses."""

from __future__ import annotations

import math

from curvemole.core.data import CurveState

DISPLAY_METHODS = {
    "parametric_monte_carlo": "Parametric Monte Carlo",
    "residual_bootstrap": "Residual bootstrap",
    "block_bootstrap": "Block bootstrap",
    "profile_likelihood": "Profile likelihood",
}


def selected_method(project, curve_id: str) -> str | None:
    method = project.results.get("uncertainty_display_method_by_curve", {}).get(curve_id)
    if method not in DISPLAY_METHODS:
        return None
    reports = project.results.get("uncertainty_reports_by_curve", {}).get(curve_id, {})
    return method if method in reports else None


def analysis_error(project, curve_id: str, path: str) -> tuple[float, float] | None:
    """Return distances below/above the fitted value, only for a valid saved fit."""
    if project.dataset.curve(curve_id).state != CurveState.FITTED:
        return None
    method = selected_method(project, curve_id)
    if method is None:
        return None
    record = project.results["uncertainty_reports_by_curve"][curve_id][method]
    analysis = record.get("analysis", {})
    baseline = record.get("baseline", {})
    if hasattr(analysis, "to_dict"):
        analysis = analysis.to_dict()
    if hasattr(baseline, "to_dict"):
        baseline = baseline.to_dict(arrays=False)
    if method == "profile_likelihood":
        if analysis.get("parameter_path") != path:
            return None
        interval = analysis.get("interval")
    else:
        interval = analysis.get("intervals", {}).get(path)
    estimate = baseline.get("parameters", {}).get(path, {})
    value = estimate.get("value")
    if interval is None or len(interval) != 2 or value is None:
        return None
    low, high = interval
    if low is None or high is None or not all(math.isfinite(v) for v in (low, high, value)):
        return None
    # A confidence interval excluding the original estimate must not be
    # presented as a conventional negative/positive error around that estimate.
    if not low <= value <= high:
        return None
    return float(value - low), float(high - value)
