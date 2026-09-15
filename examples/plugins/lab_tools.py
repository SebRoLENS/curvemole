"""Small runnable examples using only CurveMole's bundled dependencies."""
import numpy as np
from scipy.optimize import least_squares


def export_csv(context):
    curve = context.project.dataset.curve(context.active_curve_id)
    np.savetxt(context.path, np.column_stack([curve.x, curve.y]), delimiter=",",
               header="x,y", comments="")
    return f"Exported {curve.name} to {context.path}"


def import_csv(context):
    from pathlib import Path

    from curvemole import Curve
    values = np.loadtxt(context.path, delimiter=",", skiprows=1, ndmin=2)
    context.project.add_curve(Curve(Path(context.path).stem, values[:, 0], values[:, 1]))


def duplicate_scaled(context):
    from curvemole import Curve
    curve = context.project.dataset.curve(context.active_curve_id)
    context.project.add_curve(Curve(curve.name + " × 2", curve.x.copy(), 2 * curve.y))
    context.data["scaled_copies"] = context.data.get("scaled_copies", 0) + 1


def analyse(context):
    curve = context.project.dataset.curve(context.active_curve_id)
    return f"{curve.name}\nPoints: {len(curve.x)}\nMean y: {np.mean(curve.y):.8g}"


def solve(request):
    request.cancellation.raise_if_cancelled()
    return least_squares(request.residual, request.initial, jac=request.jacobian,
                         bounds=request.bounds, max_nfev=request.settings.max_nfev,
                         ftol=request.settings.ftol, xtol=request.settings.xtol,
                         gtol=request.settings.gtol, loss=request.settings.loss,
                         f_scale=request.settings.f_scale, x_scale=request.settings.x_scale)


def horizontal_mean(context):
    curve = context.project.dataset.curve(context.active_curve_id)
    return [{"x": curve.x, "y": np.full_like(curve.x, np.mean(curve.y)), "colour": "#cc79a7"}]


def panel(context):
    from PySide6.QtWidgets import QLabel
    return QLabel("Plugin panel\n" + str(len(context.project.curves)) + " spectra in this project")


def workflow(context):
    duplicate_scaled(context)
    context.data["last_workflow"] = "Duplicate with doubled intensity"


def hook(event, context):
    # Hooks are read-only notifications. Changes to this snapshot are discarded.
    # Avoid slow work, file writes and opening dialogs on frequent refresh events.
    return None


def register(api):
    api.add("exporters", "csv", "Laboratory CSV", export_csv,
            description="Active spectrum; x/y columns with a header")
    api.add("importers", "read_csv", "Laboratory CSV", import_csv)
    api.add("fit_solvers", "least_squares", "Laboratory least squares", solve)
    api.add("transformations", "double", "Duplicate with doubled intensity", duplicate_scaled)
    api.add("analysis", "summary", "Spectrum summary", analyse)
    api.add("plot_layers", "mean", "Show mean intensity", horizontal_mean)
    api.add("panels", "overview", "Laboratory overview", panel)
    api.add("actions", "duplicate", "Create scaled copy", duplicate_scaled)
    api.add("workflows", "prepare", "Prepare scaled spectrum", workflow)
    api.add("hooks", "events", "Laboratory notifications", hook)
