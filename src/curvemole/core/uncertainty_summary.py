"""Conservative, deterministic diagnostics shared by every uncertainty method."""
from __future__ import annotations

import math
import re

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


def _readable_function(project, path, name):
    """Put a space before the index of an automatically numbered builtin."""
    try:
        from curvemole.core.errors import DataValidationError
        from curvemole.core.registry import default_registry

        curve_id, component_id, _ = path.split(".", 2)
        component = project.models[curve_id].component(component_id)
        if component.metadata.get("custom_name"):
            return name
        display = default_registry().get(component.function_id).display_name
        base = re.sub(r"[\W_]+", "", display, flags=re.UNICODE)
        suffix = name[len(base):] if name.startswith(base) else ""
        if base and suffix.isdecimal():
            return f"{display} {suffix}"
    except (KeyError, ValueError, DataValidationError):
        pass
    return name


def summarize(project, baseline, analysis, method):
    """Return recorded values and interpretable intervals, never relative-to-origin errors.

    Correlation/bound heuristics are warnings, not certificates of scientific
    correctness. OK only means none of these checks flagged an issue.
    """
    baseline = baseline.to_dict(arrays=False) if hasattr(baseline, "to_dict") else baseline
    analysis = analysis.to_dict() if hasattr(analysis, "to_dict") else analysis
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
        fixed = bool(estimate.get("fixed", False)) or estimate.get("status") == "fixed"
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
            adaptive = analysis.get("configuration", {}).get("adaptive")
            if adaptive and not adaptive.get("converged", False):
                flag(1, "Maximum attempts reached before interval endpoints met the requested stability criterion.")
        if finite and not fixed:
            global_lower = estimate.get("global_minimum")
            global_upper = estimate.get("global_maximum")
            lower = float(global_lower if global_lower is not None else estimate.get("minimum", -math.inf))
            upper = float(global_upper if global_upper is not None else estimate.get("maximum", math.inf))
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
                if curve is not None and (not curve.has_y_errors or
                        not baseline.get("settings", {}).get("use_data_errors", True)):
                    flag(1, "Profile confidence assumes calibrated noise; no absolute sigma_y was supplied.")
                grid = analysis.get("values", [])
                if grid and (low <= min(grid) + tol or high >= max(grid) - tol):
                    flag(1, "Profile interval reaches the scanned range; extend the scan before interpreting its endpoints.")
                if analysis.get("failed_points", 0):
                    flag(1, "Some profile grid fits failed; the profile is incomplete.")
        if not fixed and correlation is not None and path in paths:
            matrix = np.asarray(correlation, dtype=float)
            i = paths.index(path)
            if matrix.shape == (len(paths), len(paths)):
                linked = []
                source_spectrum, source_function, source_parameter = parameter_label(project, path)
                source_function = _readable_function(project, path, source_function)
                for j, coefficient in enumerate(matrix[i]):
                    if j != i and np.isfinite(coefficient) and abs(coefficient) >= .95:
                        spectrum, function, parameter = parameter_label(project, paths[j])
                        function = _readable_function(project, paths[j], function)
                        other = f"{function} {parameter}"
                        if spectrum != source_spectrum:
                            other = f"{spectrum}: {other}"
                        linked.append(f"{other} (r={coefficient:+.3f})")
                if linked:
                    flag(1, f"Strong correlation in {source_spectrum}: "
                         f"{source_function} {source_parameter} ↔ "
                         + "; ".join(linked)
                         + "; parameters may compensate each other.")
        status = ("Critical" if severity == 2 else "Attention" if severity == 1 else
                  "Fixed" if fixed else "OK")
        if status == "OK":
            reasons.append("No diagnostic issue was flagged by these checks; practical adequacy is not assessed.")
        curve, component, name = parameter_label(project, path)
        rows.append(dict(path=path, spectrum=curve, function=component, parameter=name,
                         value=value, lower=low, upper=high,
                         status=status, reasons=" ".join(reasons), reason_items=reasons,
                         method=method,
                         confidence_level=analysis.get("confidence_level", baseline.get("settings", {}).get("confidence_level", .95))))
    return rows
