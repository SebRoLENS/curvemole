"""Standalone, publication-ready Matplotlib renderers.

The renderer consumes either scientific curves or a snapshot of already displayed
traces. It never imports pyplot, changes the process backend, or opens a window.
"""

from __future__ import annotations

import textwrap
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from curvemole.core.data import Curve, CurveState
from curvemole.core.fitting import FitResult
from curvemole.core.models import Model
from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry, default_registry
from curvemole.version import __version__


@dataclass(slots=True)
class PlotTrace:
    """One displayed trace, in original axis coordinates (also on log axes)."""

    label: str
    x: np.ndarray
    y: np.ndarray
    kind: str = "data"
    color: str | None = None
    line_style: str | None = None
    marker: bool | None = None
    y_error_minus: np.ndarray | None = None
    y_error_plus: np.ndarray | None = None
    x_error: np.ndarray | None = None


@dataclass(slots=True)
class PlotSnapshot:
    """An independent snapshot of the visible plot, including its axis limits.

    Traces must already include display transformations such as offsets and
    background subtraction. Ranges are raw axis values, never log10 values.
    """

    traces: list[PlotTrace]
    residuals: list[PlotTrace] = field(default_factory=list)
    x_label: str = "x"
    y_label: str = "y"
    x_range: tuple[float, float] | None = None
    y_range: tuple[float, float] | None = None
    residual_range: tuple[float, float] | None = None
    log_x: bool = False
    log_y: bool = False
    title: str = ""
    theme: str = "light"
    residual_label: str = "Residual (data - fit)"
    masked_ranges: list[tuple[float, float]] = field(default_factory=list)
    caption: str = ""


_THEMES = {
    "light": {
        "paper": "#ffffff", "text": "#23323c", "muted": "#667883",
        "edge": "#a6b2b8", "grid": "#d9e1e5", "data": "#34434d",
        "fit": "#248469", "background": "#87969a", "mask": "#93a0aa",
        "components": ("#8466b2", "#cb8949", "#468eae", "#ba6e83", "#79964e"),
    },
    "dark": {
        "paper": "#111c27", "text": "#d8e5ec", "muted": "#94a9ba",
        "edge": "#405161", "grid": "#405161", "data": "#d8e5ec",
        "fit": "#9bf3cd", "background": "#8da6b8", "mask": "#71818e",
        "components": ("#bca9f6", "#eeb886", "#82c8e1", "#e4a2ba", "#bbd58b"),
    },
}


def _label(name: str, unit: str) -> str:
    return f"{name} [{unit}]" if unit else name


def _palette(theme: str) -> dict:
    if theme not in _THEMES:
        raise ValueError("Figure theme must be 'light' or 'dark'.")
    return _THEMES[theme]


def _style_axis(axis, palette: dict) -> None:
    axis.set_facecolor(palette["paper"])
    axis.spines[["top", "right"]].set_visible(False)
    for spine in axis.spines.values():
        spine.set_color(palette["edge"])
        spine.set_linewidth(.7)
    axis.grid(True, color=palette["grid"], linewidth=.55, alpha=.5)
    axis.set_axisbelow(True)
    axis.tick_params(colors=palette["muted"], labelsize=9, width=.7, length=3)
    for text in (*axis.get_xticklabels(), *axis.get_yticklabels()):
        text.set_fontfamily("DejaVu Sans")
    for label in (axis.xaxis.label, axis.yaxis.label):
        label.set_color(palette["text"])
        label.set_fontsize(10)
        label.set_fontfamily("DejaVu Sans")
    axis.xaxis.get_offset_text().set_color(palette["muted"])
    axis.yaxis.get_offset_text().set_color(palette["muted"])
    axis.margins(x=.025, y=.09)


def _trace_arrays(trace: PlotTrace, *, log_x: bool, log_y: bool):
    x, y = np.asarray(trace.x, dtype=float), np.asarray(trace.y, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
        raise ValueError("A plot trace requires equally sized one-dimensional x and y arrays.")
    valid = np.isfinite(x) & np.isfinite(y)
    if log_x:
        valid &= x > 0
    if log_y:
        valid &= y > 0
    # Keep the original ordering and gaps, rather than connecting across NaNs.
    return np.where(valid, x, np.nan), np.where(valid, y, np.nan), valid


def _draw_trace(axis, trace: PlotTrace, palette: dict, index: int, *, log_x=False, log_y=False):
    x, y, valid = _trace_arrays(trace, log_x=log_x, log_y=log_y)
    kind = trace.kind
    default_colors = {
        "data": palette["data"], "fit": palette["fit"],
        "background": palette["background"], "residual": palette["data"],
        "masked": palette["mask"],
    }
    color = trace.color or default_colors.get(kind, palette["components"][index % len(palette["components"])])
    marker = trace.marker if trace.marker is not None else kind in {"data", "residual", "masked"}
    default_style = "none" if kind in {"data", "residual", "masked"} else ":" if kind == "background" else "--" if kind == "component" else "-"
    style = trace.line_style if trace.line_style is not None else default_style
    style = {"solid": "-", "dash": "--", "dashed": "--", "dot": ":", "dotted": ":", "dashdot": "-.", "None": "none", "": "none"}.get(style, style)
    line = axis.plot(
        x, y, color=color, linestyle=style, linewidth=2 if kind == "fit" else 1.15,
        marker="o" if marker else None, markersize=3.0 if kind in {"data", "residual"} else 3.4,
        markeredgewidth=.7 if kind == "masked" else 0,
        markerfacecolor="none" if kind == "masked" else color,
        label=trace.label, alpha=.48 if kind == "masked" else 1,
        zorder=4 if kind == "fit" else 3 if kind == "data" else 2,
    )[0]
    errors = {}
    if trace.y_error_minus is not None:
        minus = np.asarray(trace.y_error_minus, dtype=float)
        plus = np.asarray(trace.y_error_plus if trace.y_error_plus is not None else minus, dtype=float)
        if minus.shape != x.shape or plus.shape != x.shape:
            raise ValueError("Y errors must have the same shape as their plot trace.")
        keep = valid & np.isfinite(minus) & np.isfinite(plus) & (minus >= 0) & (plus >= 0)
        if log_y:
            keep &= y - minus > 0
        errors["yerr"] = (keep, np.array([minus, plus]))
    if trace.x_error is not None:
        error = np.asarray(trace.x_error, dtype=float)
        if error.shape != x.shape:
            raise ValueError("X errors must have the same shape as their plot trace.")
        keep = valid & np.isfinite(error) & (error >= 0)
        if log_x:
            keep &= x - error > 0
        errors["xerr"] = (keep, error)
    # Draw axes independently: a missing Y error must not hide a valid X error.
    for name, (keep, error) in errors.items():
        if np.any(keep):
            axis.errorbar(
                x[keep], y[keep], **{name: error[:, keep] if error.ndim == 2 else error[keep]},
                fmt="none", ecolor=color, elinewidth=.65, capsize=1.8,
                capthick=.65, alpha=.55, zorder=2.5,
            )
    return line


def _valid_range(values: tuple[float, float] | None, *, logarithmic=False):
    if values is None:
        return None
    if len(values) != 2 or not np.all(np.isfinite(values)) or values[0] == values[1]:
        raise ValueError("Plot axis limits must contain two distinct finite numbers.")
    if logarithmic and min(values) <= 0:
        raise ValueError("Logarithmic plot limits must be positive axis values.")
    return values


def _draw_legend(axis, traces: list[PlotTrace], palette: dict) -> str:
    from matplotlib.lines import Line2D

    handles, labels = axis.get_legend_handles_labels()
    if not handles:
        return ""
    unique = dict(zip(labels, handles, strict=True))
    note = ""
    if len(unique) > 20:
        # An exhaustive legend for a large overlay can exceed the entire canvas.
        # Keep every trace, but describe its role instead of listing hundreds of
        # long spectrum/component names over the graph.
        counts = {}
        for trace in traces:
            counts[trace.kind] = counts.get(trace.kind, 0) + 1
        entries = (
            ("data", "Data", palette["data"], "none", "o"),
            ("fit", "Total models", palette["fit"], "-", None),
            ("component", "Components", palette["components"][0], "--", None),
            ("background", "Backgrounds", palette["background"], ":", None),
            ("masked", "Excluded points", palette["mask"], "none", "o"),
        )
        handles, labels = [], []
        for kind, name, color, style, marker in entries:
            if counts.get(kind):
                handles.append(Line2D([], [], color=color, linestyle=style, marker=marker,
                                      markersize=3, linewidth=1.5))
                labels.append(f"{name} ({counts[kind]} traces)")
        note = f"{len(traces)} visible traces; legend grouped by role. All displayed traces are included."
    else:
        handles = list(unique.values())
        # At most two lines per label. Full trace labels remain intact in the
        # snapshot; wrapping only affects their printed legend representation.
        labels = ["\n".join(textwrap.wrap(label if len(label) <= 68 else label[:65] + "...", width=36))
                  for label in unique]
    legend = axis.legend(
        handles, labels, loc="best", fontsize=8,
        frameon=True, facecolor=palette["paper"], edgecolor="none",
        framealpha=.88, labelcolor=palette["text"], ncol=2 if len(handles) > 7 else 1,
        handlelength=2.5, borderpad=.65, labelspacing=.45,
    )
    for text in legend.get_texts():
        text.set_fontfamily("DejaVu Sans")
    return note


def _draw_snapshot(figure, snapshot: PlotSnapshot, *, caption_y=.012):
    palette = _palette(snapshot.theme)
    figure.set_facecolor(palette["paper"])
    if snapshot.residuals:
        grid = figure.add_gridspec(2, 1, height_ratios=(3.3, 1), hspace=.09)
        axis = figure.add_subplot(grid[0])
        residual_axis = figure.add_subplot(grid[1], sharex=axis)
        axis.tick_params(labelbottom=False)
    else:
        axis, residual_axis = figure.add_subplot(111), None
    _style_axis(axis, palette)
    if snapshot.log_x:
        axis.set_xscale("log")
    if snapshot.log_y:
        axis.set_yscale("log")
    component_index = 0
    for trace in snapshot.traces:
        _draw_trace(axis, trace, palette, component_index, log_x=snapshot.log_x, log_y=snapshot.log_y)
        if trace.kind == "component":
            component_index += 1
    for lower, upper in snapshot.masked_ranges:
        axis.axvspan(min(lower, upper), max(lower, upper), color=palette["mask"], alpha=.09, zorder=0)
    if residual_axis is not None:
        _style_axis(residual_axis, palette)
        residual_axis.axhline(0, color=palette["muted"], linewidth=.8, zorder=1)
        for index, trace in enumerate(snapshot.residuals):
            _draw_trace(residual_axis, trace, palette, index, log_x=snapshot.log_x)
        residual_axis.set_ylabel(snapshot.residual_label, fontsize=9)
        residual_axis.set_xlabel(snapshot.x_label)
        if (limits := _valid_range(snapshot.residual_range)) is not None:
            residual_axis.set_ylim(*limits)
    else:
        axis.set_xlabel(snapshot.x_label)
    axis.set_ylabel(snapshot.y_label)
    if (limits := _valid_range(snapshot.x_range, logarithmic=snapshot.log_x)) is not None:
        axis.set_xlim(*limits)
    if (limits := _valid_range(snapshot.y_range, logarithmic=snapshot.log_y)) is not None:
        axis.set_ylim(*limits)
    if snapshot.title:
        axis.set_title("\n".join(textwrap.wrap(snapshot.title, 85)), loc="left", pad=13,
                       color=palette["text"], fontsize=14, fontfamily="DejaVu Sans")
    legend_note = _draw_legend(axis, snapshot.traces, palette)
    caption = "\n".join(item for item in (snapshot.caption, legend_note) if item)
    if caption:
        caption = "\n".join(textwrap.fill(line, width=112) for line in caption.splitlines())
        figure.text(.1, caption_y, caption, color=palette["muted"], fontsize=8,
                    va="bottom", fontfamily="DejaVu Sans", linespacing=1.5)
        # Reserve real space for multi-line operator/statistics notes.
        bottom = caption_y + .025 + .03 * len(caption.splitlines())
        figure.get_layout_engine().set(rect=(0, bottom, 1, 1 - bottom))
    return axis, residual_axis


def export_plot_snapshot(
    snapshot: PlotSnapshot,
    path: str | Path,
    *,
    dpi: int = 300,
    width: float = 9.0,
    height: float = 5.5,
    transparent: bool = False,
) -> Path:
    """Render a frozen screen view, preserving its curves, offsets and ranges."""
    from curvemole.core.export import _export_figure, _release_export_figure

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure = _export_figure(figsize=(width, height), constrained_layout=True)
    try:
        _draw_snapshot(figure, snapshot)
        figure.savefig(destination, dpi=dpi, transparent=transparent)
    finally:
        _release_export_figure(figure)
    return destination


def _component_trace(model, component, x, parts, background):
    """Respect subtract terms and global multiply/divide/convolution operators."""
    has_background = any(c.enabled and c.is_background for c in model.components)
    if component.operator not in {"add", "subtract"}:
        return parts[component.id], f"{component.name} ({component.operator} operand)"
    if component.is_background:
        selected = dict(parts)
        for term in model.components:
            if term.operator in {"add", "subtract"} and term.id != component.id:
                selected[term.id] = np.zeros_like(x)
        return model._evaluate_global(x, selected), component.name
    if any(c.enabled and c.operator not in {"add", "subtract"} for c in model.components):
        selected = dict(parts)
        for term in model.components:
            if term.operator in {"add", "subtract"} and not term.is_background and term.id != component.id:
                selected[term.id] = np.zeros_like(x)
        values = model._evaluate_global(x, selected)
    else:
        values = background + parts[component.id] * (1 if component.operator == "add" else -1)
    label = component.name + (" + background" if has_background else "")
    if component.operator == "subtract":
        label = ("Background - " if has_background else "- ") + component.name
    return values, label


def _snapshot_for_curves(
    curves: list[Curve], models: Mapping[str, Model], *, registry: FunctionRegistry,
    parameter_values: Mapping[str, float], include_components: bool, include_residuals: bool,
    include_error_bars: bool, theme: str,
) -> PlotSnapshot:
    snapshot = PlotSnapshot([], theme=theme)
    if not curves:
        snapshot.title, snapshot.caption = "No spectra to export", "CurveMole " + __version__
        return snapshot
    first = curves[0]
    snapshot.x_label, snapshot.y_label = _label(first.x_label, first.x_unit), _label(first.y_label, first.y_unit)
    snapshot.residual_label = _label("Residual (data - fit)", first.y_unit)
    snapshot.title = first.name if len(curves) == 1 else "Spectra and models"
    included_count, excluded_count = 0, 0
    operator_notes: dict[str, list[str]] = {}
    for curve in curves:
        finite = np.isfinite(curve.x) & np.isfinite(curve.y)
        included = finite & ~curve.effective_mask
        excluded = finite & curve.effective_mask
        included_count += int(np.count_nonzero(included))
        excluded_count += int(np.count_nonzero(excluded))
        prefix = "" if len(curves) == 1 else curve.name + " - "
        data_label = prefix + "Data"
        minus = plus = x_error = None
        if include_error_bars:
            minus, plus = curve.current_error_y_minus, curve.current_error_y_plus
            if minus is not None:
                data_label += f" ({curve.error_confidence_level:.0%} interval)"
            elif curve.current_sigma_y is not None:
                minus = plus = curve.current_sigma_y
                data_label += " ±1σ"
            x_error = curve.current_sigma_x
        data_color = None if len(curves) == 1 else curve.colour
        snapshot.traces.append(PlotTrace(data_label, curve.x[included], curve.y[included], color=data_color,
            y_error_minus=None if minus is None else minus[included],
            y_error_plus=None if plus is None else plus[included],
            x_error=None if x_error is None else x_error[included]))
        if np.any(excluded):
            snapshot.traces.append(PlotTrace(prefix + "Excluded from fit", curve.x[excluded], curve.y[excluded], kind="masked"))
        model = models.get(curve.id)
        if model is None or not any(c.enabled for c in model.components) or not np.any(finite):
            continue
        for component in model.components:
            if component.enabled and component.operator not in {"add", "subtract"}:
                names = operator_notes.setdefault(component.operator, [])
                if component.name not in names:
                    names.append(component.name)
        x = curve.x[finite]
        # Dense and sorted model values are independent of sample spacing/order.
        # Numerical convolution is defined on the sampled grid, so keep its grid
        # rather than changing the convolution domain and therefore the model.
        convolution = any(c.enabled and c.operator == "convolve" for c in model.components)
        if convolution:
            dense_x = np.asarray(curve.x)
        else:
            dense_x = np.linspace(float(np.min(x)), float(np.max(x)), max(650, min(4000, len(x) * 4)))
        total, parts = model.evaluate(dense_x, curve_id=curve.id, values=parameter_values,
                                      registry=registry, components=True)
        snapshot.traces.append(PlotTrace(prefix + "Total model", dense_x, total, kind="fit"))
        if include_components:
            background = model.background(dense_x, curve_id=curve.id, values=parameter_values,
                                          registry=registry, evaluated_components=parts)
            for component in model.display_components:
                if (not component.enabled or component.id not in parts
                        or component.operator not in {"add", "subtract"}):
                    continue
                values, label = _component_trace(model, component, dense_x, parts, background)
                snapshot.traces.append(PlotTrace(prefix + label, dense_x, values,
                    kind="background" if component.is_background else "component"))
        if include_residuals and np.any(included):
            fitted = model.evaluate(curve.x, curve_id=curve.id, values=parameter_values, registry=registry)
            keep = included & np.isfinite(fitted)
            snapshot.residuals.append(PlotTrace(prefix + "Residual", curve.x[keep], (curve.y - fitted)[keep], kind="residual", color=data_color))
    snapshot.caption = f"N = {included_count} included; {excluded_count} excluded from fit"
    if len(curves) == 1:
        snapshot.caption += "  |  " + str(first.state)
    if operator_notes:
        snapshot.caption += "\nGlobal model operators applied: " + "; ".join(
            f"{operator}: {', '.join(names)}" for operator, names in operator_notes.items())
    return snapshot


def export_figure(
    curves: Iterable[Curve], models: Mapping[str, Model], path: str | Path, *,
    registry: FunctionRegistry | None = None, dpi: int = 300, width: float = 9.0,
    height: float = 5.5, transparent: bool = False, include_components: bool = True,
    include_residuals: bool = True, include_error_bars: bool = True,
    parameter_values: Mapping[str, float] | None = None, theme: str = "light",
) -> Path:
    """Export data, a smooth composed model and raw unmasked residuals."""
    if parameter_values is None:
        from curvemole.core.export import _resolved_values
        parameter_values = _resolved_values(models)
    snapshot = _snapshot_for_curves(
        list(curves), models, registry=registry or default_registry(), parameter_values=parameter_values,
        include_components=include_components, include_residuals=include_residuals,
        include_error_bars=include_error_bars, theme=theme,
    )
    return export_plot_snapshot(snapshot, path, dpi=dpi, width=width, height=height, transparent=transparent)


def _curve_fit_result(
    project: Project, curve: Curve, result: FitResult | None, *,
    registry: FunctionRegistry, parameter_values: Mapping[str, float],
) -> FitResult | None:
    if curve.state != CurveState.FITTED:
        return None
    by_curve = project.results.get("fit_by_curve", {}).get(curve.id, {})
    candidates = [result, project.results.get("fit:" + curve.id)]
    if isinstance(by_curve, Mapping):
        candidates.append(by_curve.get("baseline"))
        if by_curve.get("global_key"):
            candidates.append(project.results.get("global_fit_baselines", {}).get(by_curve["global_key"]))
    candidates.append(project.results.get("last_fit"))
    for candidate in candidates:
        if not isinstance(candidate, FitResult) or curve.id not in candidate.curve_outputs:
            continue
        output = candidate.curve_outputs[curve.id]
        indices = np.asarray(output.indices)
        if np.any(indices < 0) or np.any(indices >= len(curve)):
            continue
        if not np.array_equal(output.x, curve.x[indices]) or not np.array_equal(output.observed, curve.y[indices]):
            continue
        model = project.models.get(curve.id)
        if model is None:
            continue
        current = model.evaluate(curve.x, curve_id=curve.id, values=parameter_values, registry=registry)
        if not np.allclose(output.fitted, current[indices], rtol=1e-8, atol=1e-10):
            continue
        return candidate
    return None


def _statistics_caption(result: FitResult | None, curve: Curve) -> str:
    if result is None:
        return ""
    statistics = result.curve_outputs[curve.id].statistics
    values = []
    for key, label in (("RMSE", "RMSE"), ("reduced_chi_square", "reduced chi-square"), ("R_squared", "R-squared")):
        value = statistics.get(key)
        if value is not None and np.isfinite(value):
            values.append(f"{label} = {value:.4g}")
    return "; ".join(values)


def generate_pdf_report(
    project: Project, path: str | Path, *, result: FitResult | None = None,
    title: str | None = None, registry: FunctionRegistry | None = None,
    curves: Iterable[Curve] | None = None,
) -> Path:
    """Write one vector page per spectrum, with only its own current statistics."""
    from matplotlib.backends.backend_pdf import PdfPages

    from curvemole.core.export import _export_figure, _registry_for_project, _release_export_figure

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    selected = list(project.curves if curves is None else curves)
    registry = registry or _registry_for_project(project)
    parameter_values = project.resolved_parameter_values()
    with PdfPages(destination, metadata={"Title": title or project.name, "Creator": f"CurveMole {__version__}"}) as pdf:
        for index, curve in enumerate(selected or [None], 1):
            figure = _export_figure(figsize=(9.0, 6.3), constrained_layout=True)
            try:
                snapshot = _snapshot_for_curves(
                    [] if curve is None else [curve], project.models, registry=registry,
                    parameter_values=parameter_values, include_components=True,
                    include_residuals=True, include_error_bars=True, theme="light",
                )
                if curve is not None:
                    statistic_text = _statistics_caption(_curve_fit_result(project, curve, result, registry=registry, parameter_values=parameter_values), curve)
                    if statistic_text:
                        snapshot.caption += "\n" + statistic_text
                _draw_snapshot(figure, snapshot, caption_y=.042)
                figure.text(.1, .985, textwrap.shorten(title or project.name, width=100, placeholder="..."),
                            va="top", fontsize=9, color=_THEMES["light"]["muted"], fontfamily="DejaVu Sans")
                figure.text(.98, .012, f"CurveMole {__version__}  |  {index}/{max(1, len(selected))}",
                            ha="right", va="bottom", fontsize=7, color=_THEMES["light"]["muted"])
                bottom = max(.09, figure.get_layout_engine().get()["rect"][1])
                figure.get_layout_engine().set(rect=(0, bottom, 1, .94 - bottom))
                pdf.savefig(figure)
            finally:
                _release_export_figure(figure)
    return destination
