"""Conservative, deterministic diagnostics shared by every uncertainty method."""
from __future__ import annotations

import math

import numpy as np

METHOD_LABELS = {
    "covariance": "Fit covariance", "parametric_monte_carlo": "Parametric Monte Carlo",
    "residual_bootstrap": "Residual bootstrap", "block_bootstrap": "Block bootstrap",
    "profile_likelihood": "Profile likelihood",
}


def parameter_label(project, path):
    try:
        curve_id, component_id, name = path.split(".", 2)
        curve = project.dataset.curve(curve_id)
        component = project.models[curve_id].component(component_id)
        return curve.name, component.name, name
    except (KeyError, ValueError):
        return "Removed spectrum", "Removed function", path.rsplit(".", 1)[-1]


def summarize(project, baseline, analysis, method, targets=None):
    """Return recorded values and interpretable intervals, never relative-to-origin errors.

    Green requires a user-defined absolute precision target. Correlation/bound
    heuristics are warnings, not certificates of scientific correctness.
    """
    baseline = baseline.to_dict(arrays=False) if hasattr(baseline, "to_dict") else baseline
    analysis = analysis.to_dict() if hasattr(analysis, "to_dict") else analysis
    targets = targets or {}
    estimates = baseline.get("parameters", {})
    if method == "covariance":
        intervals = {path: (e.get("ci_low"), e.get("ci_high")) for path, e in estimates.items()}
    elif method == "profile_likelihood":
        intervals = {analysis["parameter_path"]: analysis["interval"]}
    else:
        intervals = {path: analysis.get("intervals", {}).get(path, (None, None))
                     for path in analysis.get("parameter_paths", [])}
    paths = baseline.get("free_parameter_paths", [])
    correlation = analysis.get("sample_correlation", baseline.get("correlation"))
    if method not in {"covariance", "profile_likelihood"} and "sample_correlation" in analysis:
        paths = analysis.get("parameter_paths", [])
    # Empirical correlations are more relevant for resampling when available.
    if method not in {"covariance", "profile_likelihood"}:
        samples = np.asarray(analysis.get("samples", []), dtype=float)
        if samples.ndim == 2 and samples.shape[0] >= 3 and samples.shape[1] > 1:
            with np.errstate(invalid="ignore", divide="ignore"):
                correlation = np.corrcoef(samples, rowvar=False)
            paths = analysis.get("parameter_paths", [])
    rows = []
    for path, interval in intervals.items():
        estimate = estimates.get(path, {})
        value = estimate.get("value")
        low, high = interval
        severity, reasons = 0, []
        curve = None
        def flag(level, reason, reasons=reasons):
            nonlocal severity
            severity = max(severity, level)
            reasons.append(reason)
        try:
            curve_id, component_id, parameter_name = path.split(".", 2)
            curve = project.dataset.curve(curve_id)
            project.models[curve_id].component(component_id).parameters[parameter_name]
            if curve.state.value == "Modified/outdated":
                flag(1, "Recorded result: data/model have changed since this fit; refit and rerun analysis.")
        except (KeyError, ValueError):
            flag(2, "The original spectrum/function no longer exists.")
        fixed = estimate.get("status") == "fixed"
        finite = all(v is not None and math.isfinite(v) for v in (value, low, high))
        if fixed:
            reasons.append("Fixed parameter; uncertainty was not estimated.")
        elif not finite or low > high:
            flag(2, "No valid confidence interval; analysis is insufficient.")
        if not baseline.get("success", False):
            flag(2, "The baseline fit did not converge.")
        if not fixed and method == "covariance":
            if any("rank-deficient" in w or "underdetermined" in w for w in baseline.get("warnings", [])):
                flag(2, "Rank-deficient/underdetermined covariance cannot establish identifiability.")
            if baseline.get("settings", {}).get("loss", "linear") != "linear":
                flag(1, "Robust-loss covariance is approximate; compare with resampling.")
        if method not in {"covariance", "profile_likelihood"}:
            completed = analysis.get("completed", 0)
            failed = analysis.get("failed", 0)
            if completed < 20:
                flag(2, "Too few successful replicates for a reliable percentile interval (<20).")
            elif completed < 200:
                flag(1, "Fewer than 200 successful replicates; interval endpoints may be unstable.")
            if failed:
                flag(1, f"{failed} replicates failed; the interval may be biased.")
        if finite and not fixed:
            lower = float(estimate.get("minimum", -math.inf))
            upper = float(estimate.get("maximum", math.inf))
            span = high - low
            tol = max(1e-12, span * 1e-6)
            if estimate.get("at_bound") or (math.isfinite(lower) and low <= lower + tol) or (math.isfinite(upper) and high >= upper - tol):
                flag(1, "The estimate/interval reaches a parameter bound; bounds may limit uncertainty.")
            if math.isfinite(lower) and math.isfinite(upper) and upper > lower and span >= .8 * (upper - lower):
                flag(2, "Interval covers >=80% of the allowed range; parameter is poorly constrained within these bounds.")
            if not low <= value <= high:
                flag(1, "The original fit lies outside the interval; inspect bias or alternative minima.")
            if method == "profile_likelihood":
                if baseline.get("settings", {}).get("loss", "linear") != "linear":
                    flag(1, "Chi-square profile thresholds are not calibrated for a robust-loss optimum.")
                if curve is not None and curve.current_sigma_y is None:
                    flag(1, "Profile confidence assumes calibrated noise; no absolute sigma_y was supplied.")
                grid = analysis.get("values", [])
                if grid and (low <= min(grid) + tol or high >= max(grid) - tol):
                    flag(1, "Profile interval reaches the scanned range; extend the scan before interpreting its endpoints.")
                if analysis.get("failed_points", 0):
                    flag(1, "Some profile grid fits failed; the profile is incomplete.")
            target = targets.get(path)
            if target is not None and target > 0:
                if max(abs(value-low), abs(high-value)) > target:
                    flag(1, "Interval exceeds your acceptable absolute uncertainty.")
                else:
                    reasons.append("Interval satisfies your acceptable absolute uncertainty.")
            else:
                reasons.append("No absolute precision target set; practical adequacy is not assessed.")
        if not fixed and correlation is not None and path in paths:
            matrix = np.asarray(correlation, dtype=float)
            i = paths.index(path)
            if matrix.shape == (len(paths), len(paths)):
                linked = []
                for j, coefficient in enumerate(matrix[i]):
                    if j != i and np.isfinite(coefficient) and abs(coefficient) >= .95:
                        spectrum, function, parameter = parameter_label(project, paths[j])
                        linked.append(f"{spectrum} / {function} / {parameter} (r={coefficient:+.3f})")
                if linked:
                    flag(1, "Strong correlation with " + "; ".join(linked)
                         + "; parameters may compensate each other.")
        target = targets.get(path)
        status = ("Critical" if severity == 2 else "Attention" if severity == 1 else
                  "Fixed" if fixed else "OK" if finite and target and target > 0 else "Not assessed")
        curve, component, name = parameter_label(project, path)
        rows.append(dict(path=path, spectrum=curve, function=component, parameter=name,
                         value=value, lower=low, upper=high, target=target,
                         status=status, reasons=" ".join(reasons), method=method,
                         confidence_level=analysis.get("confidence_level", baseline.get("settings", {}).get("confidence_level", .95))))
    return rows
