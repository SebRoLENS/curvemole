from curvemole.core.results_store import ResultKey

"""Warnings shared by saved uncertainty reports and spectrum-list tags."""


def uncertainty_warning(project, curve_id, method):
    from curvemole.core.background_uncertainty import background_uncertainty_note

    method = "parametric_monte_carlo" if method == "monte_carlo" else method
    failures = project.results.get(ResultKey.UNCERTAINTY_FAILURES_BY_CURVE, {}).get(curve_id, {})
    reports = project.results.get(ResultKey.UNCERTAINTY_REPORTS_BY_CURVE, {}).get(curve_id, {})
    if method is None:
        return next((warning for name in dict.fromkeys([*failures, *reports])
                     if (warning := uncertainty_warning(project, curve_id, name))), None)
    failure = failures.get(method)
    if failure:
        if failure.get("reason") == "timeout" or "timeout" in failure.get("message", "").lower():
            return ("Timeout: the new uncertainty analysis was stopped. "
                    "Any previous completed result has been retained.")
        return "Uncertainty analysis failed: " + failure.get("message", "Unknown reason.")
    report = reports.get(method, {})
    analysis = report.get("analysis", {})
    if hasattr(analysis, "to_dict"):
        analysis = analysis.to_dict()
    adaptive = analysis.get("configuration", {}).get("adaptive")
    note = background_uncertainty_note(report.get("baseline", {}))
    warnings = [note] if note else []
    if adaptive and (adaptive.get("converged") is False or adaptive.get("stop_reason") == "maximum_attempts"):
        attempts = adaptive.get("attempted", "?")
        maximum = adaptive.get("maximum_attempts", "?")
        warnings.append(f"Adaptive limit reached ({attempts}/{maximum} attempts): "
                        "confidence intervals did not reach the required stability. "
                        "The recorded intervals are retained, but stability has not been established.")
    failed = analysis.get("failed", 0)
    if failed:
        completed = analysis.get("completed", 0)
        warnings.append(f"{failed} replica(s) failed out of {completed + failed} attempts. "
                        f"Intervals use the {completed} successful replicas only; "
                        "excluding failed fits may bias the intervals.")
    return "\n".join(warnings) if warnings else None
