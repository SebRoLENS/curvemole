"""Project-wide display choice and errors from each spectrum's recorded analysis."""

from __future__ import annotations

import math

from curvemole.core.data import CurveState

DISPLAY_METHODS = {
    "covariance": "Fit covariance",
    "parametric_monte_carlo": "Parametric Monte Carlo",
    "residual_bootstrap": "Residual bootstrap",
    "block_bootstrap": "Block bootstrap",
    "profile_likelihood": "Profile likelihood",
}


def restore_uncertainty_reports(project) -> None:
    """Promote legacy saved reports to the same per-spectrum records the GUI uses."""
    reports = project.results.get("uncertainty_reports_by_curve", {})
    for methods in reports.values():
        if "monte_carlo" in methods:
            methods.setdefault("parametric_monte_carlo", methods.pop("monte_carlo"))
    legacy = project.results.get("uncertainty_reports", {})
    for saved_method, record in list(legacy.items()):
        baseline = record.get("baseline", {})
        parameters = baseline.parameters if hasattr(baseline, "parameters") else baseline.get("parameters", {})
        curve_ids = [curve.id for curve in project.curves
                     if any(path.startswith(curve.id + ".") for path in parameters)]
        if not curve_ids:
            continue
        method = "parametric_monte_carlo" if saved_method == "monte_carlo" else saved_method
        for curve_id in curve_ids:
            reports.setdefault(curve_id, {}).setdefault(method, record)
        # A later refit can now invalidate these reports without a legacy
        # fallback resurrecting an analysis of the previous fit.
        legacy.pop(saved_method)
    if reports:
        project.results["uncertainty_reports_by_curve"] = reports
    choice = project.results.get("uncertainty_display_method")
    if choice == "monte_carlo":
        project.results["uncertainty_display_method"] = "parametric_monte_carlo"
    # Older projects stored separate preferences. Migrate the first available
    # preference in spectrum order to one project choice; never vary it by curve.
    choices = project.results.pop("uncertainty_display_method_by_curve", {})
    if "uncertainty_display_method" not in project.results:
        available = available_methods(project)
        for curve in project.curves:
            method = choices.get(curve.id)
            method = "parametric_monte_carlo" if method == "monte_carlo" else method
            if method in available:
                project.results["uncertainty_display_method"] = method
                break


def available_methods(project) -> tuple[str, ...]:
    """Methods recorded for at least one spectrum still in this project."""
    reports = project.results.get("uncertainty_reports_by_curve", {})
    names = {method for curve in project.curves for method in reports.get(curve.id, {})}
    return tuple(method for method in DISPLAY_METHODS if method in names)


def display_method(project) -> str | None:
    """Resolve one display method for the whole project without changing it."""
    available = available_methods(project)
    method = project.results.get("uncertainty_display_method")
    if method in available:
        return method
    # The single available method needs no persisted preference. A deterministic
    # default also lets older projects without any choice show recorded results.
    return available[-1] if available else None


def selected_method(project, curve_id: str) -> str | None:
    method = display_method(project)
    reports = project.results.get("uncertainty_reports_by_curve", {}).get(curve_id, {})
    return method if method in reports else None


def analysis_error(project, curve_id: str, path: str) -> tuple[float, float] | None:
    """Return distances below/above the fitted value, only for a valid saved fit."""
    if project.dataset.curve(curve_id).state != CurveState.FITTED:
        return None
    return recorded_analysis_error(project, curve_id, path)


def recorded_analysis_error(project, curve_id: str, path: str) -> tuple[float, float] | None:
    """Recorded errors around the recorded fit value, including historical fits."""
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
    estimate = baseline.get("parameters", {}).get(path, {})
    if method == "covariance":
        interval = (estimate.get("ci_low"), estimate.get("ci_high"))
    elif method == "profile_likelihood":
        if analysis.get("parameter_path") != path:
            return None
        interval = analysis.get("interval")
    else:
        interval = analysis.get("intervals", {}).get(path)
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
