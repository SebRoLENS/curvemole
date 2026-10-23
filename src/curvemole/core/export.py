"""Human-friendly and automation-friendly exports and analysis bundles."""

from __future__ import annotations

import csv
import json
import math
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from curvemole.core.data import Curve, CurveState
from curvemole.core.diagnostics import residual_diagnostics
from curvemole.core.errors import CurveMoleError
from curvemole.core.fitting import FitResult
from curvemole.core.functions import formula_definition
from curvemole.core.matrices import BlockDiagonalMatrix, matrix_from_value
from curvemole.core.models import Model
from curvemole.core.notebook import export_notebook
from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry, default_registry
from curvemole.core.serialization import save_fitmodel, save_project
from curvemole.version import __version__


def _export_figure(**kwargs):
    """Create a lazy, standalone renderer without changing the caller's backend.

    A plugin/API caller may already own interactive pyplot figures. Using an
    explicit Agg canvas avoids changing their global backend or creating GUI
    figure managers when exports run on a worker thread.
    """
    if "MPLCONFIGDIR" not in os.environ:
        preferred_cache = Path.home() / ".cache" / "curvemole" / "matplotlib"
        try:
            preferred_cache.mkdir(parents=True, exist_ok=True)
        except OSError:
            preferred_cache = Path(tempfile.gettempdir()) / "curvemole-matplotlib"
            preferred_cache.mkdir(parents=True, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = str(preferred_cache)
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(**kwargs)
    FigureCanvasAgg(figure)
    return figure


def _release_export_figure(figure):
    """Release raster/artist data immediately, including after failed writes."""
    figure.clear()
    figure.set_canvas(None)


@dataclass(slots=True)
class ExportSelection:
    original_x: bool = False
    x: bool = True
    y: bool = True
    total_fit: bool = True
    residual: bool = True
    background: bool = True
    components: bool = True
    sigma_y: bool = True
    weights: bool = True
    mask_flag: bool = True


@dataclass(slots=True)
class BundleExportSelection:
    """Contents of a complete analysis export; use ``none`` for a subset."""

    fit_results: bool = True
    fit_settings: bool = True
    wide_tables: bool = True
    tidy_table: bool = True
    results_json: bool = True
    fitmodel: bool = True
    project_copy: bool = True
    main_plot_png: bool = True
    main_plot_svg: bool = True
    html_summary: bool = True
    html_reproducibility: bool = True
    pdf_summary: bool = True
    uncertainty: bool = True
    diagnostics: bool = True
    readme: bool = True
    laboratory_notebook: bool = True
    spectra: bool = True
    function_parameters: bool = True
    parameter_covariances: bool = True
    current_view: bool = True

    @classmethod
    def none(cls, **enabled: bool) -> BundleExportSelection:
        """Create an explicit subset, independent of complete-bundle defaults."""
        return cls(**(dict.fromkeys(cls.__dataclass_fields__, False) | enabled))

    def any_selected(self) -> bool:
        return any(self.to_dict().values())

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(slots=True)
class ExportSummary:
    directory: Path
    created: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    preserved_external: list[Path] = field(default_factory=list)


def wide_dataframe(
    curve: Curve,
    model: Model | None = None,
    *,
    registry: FunctionRegistry | None = None,
    selection: ExportSelection | None = None,
    parameter_values: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    selection = selection or ExportSelection()
    registry = registry or default_registry()
    columns: dict[str, Any] = {}
    if selection.original_x:
        columns[f"{curve.x_label} original"] = curve.original_x[curve.row_indices]
    if selection.x:
        columns[_label(curve.x_label, curve.x_unit)] = curve.x
    if selection.y:
        columns[_label(curve.y_label, curve.y_unit)] = curve.y
    if model is not None and model.components and any((selection.total_fit, selection.residual, selection.background, selection.components)):
        total, components = model.evaluate(
            curve.x,
            curve_id=curve.id,
            values=parameter_values,
            registry=registry,
            components=True,
        )
        if selection.total_fit:
            columns["Total fit"] = total
        if selection.residual:
            columns["Residual (data - fit)"] = curve.y - total
        if selection.background:
            columns["Background"] = model.background(
                curve.x, curve_id=curve.id, values=parameter_values, registry=registry,
                evaluated_components=components,
            )
        if selection.components:
            component_labels: set[str] = set()
            for component in model.display_components:
                if component.enabled and component.id in components:
                    label = f"Component | {component.name} | {component.function_id}"
                    if label in component_labels:
                        label += f" | {component.id}"
                    component_labels.add(label)
                    columns[label] = components[component.id]
    if selection.sigma_y and curve.current_sigma_y is not None:
        columns["sigma_y"] = curve.current_sigma_y
    if selection.sigma_y and curve.current_error_y_minus is not None:
        columns["error_y_minus"] = curve.current_error_y_minus
        columns["error_y_plus"] = curve.current_error_y_plus
        columns["error_confidence_percent"] = curve.error_confidence_level * 100
    if selection.weights and curve.current_weights is not None:
        columns["weight"] = curve.current_weights
    if selection.mask_flag:
        columns["masked"] = curve.effective_mask
    return pd.DataFrame(columns)


def tidy_dataframe(
    project: Project,
    *,
    registry: FunctionRegistry | None = None,
    selection: ExportSelection | None = None,
) -> pd.DataFrame:
    registry = registry or default_registry()
    selection = selection or ExportSelection()
    frames: list[pd.DataFrame] = []
    parameter_values = project.resolved_parameter_values()
    for series in project.dataset.series:
        for curve in series.curves:
            wide = wide_dataframe(
                curve,
                project.models.get(curve.id),
                registry=registry,
                selection=selection,
                parameter_values=parameter_values,
            )
            x_column = _label(curve.x_label, curve.x_unit)
            x_values = curve.x if x_column not in wide else wide[x_column].to_numpy()
            for column in wide.columns:
                if column == x_column or column.endswith(" original"):
                    continue
                component, quantity = _tidy_column(column)
                frames.append(
                    pd.DataFrame(
                        {
                            "series_id": series.id,
                            "series": series.name,
                            "curve_id": curve.id,
                            "curve": curve.name,
                            "quantity": quantity,
                            "component": component,
                            "x": x_values,
                            "value": wide[column].to_numpy(),
                            "masked": curve.effective_mask,
                            "valid": np.isfinite(curve.x) & np.isfinite(curve.y),
                        }
                    )
                )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def analysis_dataframes(
    project: Project, *, registry: FunctionRegistry | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return observations, component samples, and curve metadata for Python.

    A point is identified by (curve_id, point_index), never by its X value.
    The original row index also survives sorting and row transformations.
    """
    registry = registry or _registry_for_project(project)
    values = project.resolved_parameter_values()
    observations: list[pd.DataFrame] = []
    components: list[pd.DataFrame] = []
    metadata: list[dict[str, Any]] = []
    stems = _curve_export_stems(project)
    for series in project.dataset.series:
        for curve in series.curves:
            n = len(curve)
            model = project.models.get(curve.id)
            total = np.full(n, np.nan)
            background = np.full(n, np.nan)
            evaluated: dict[str, np.ndarray] = {}
            if model is not None and model.components:
                total, evaluated = model.evaluate(
                    curve.x, curve_id=curve.id, values=values, registry=registry, components=True,
                )
                background = model.background(
                    curve.x, curve_id=curve.id, values=values, registry=registry,
                    evaluated_components=evaluated,
                )
                for component in model.display_components:
                    if component.enabled and component.id in evaluated:
                        components.append(pd.DataFrame({
                            "curve_id": curve.id, "point_index": np.arange(n),
                            "component_id": component.id, "component": component.name,
                            "function_id": component.function_id,
                            "is_background": component.is_background,
                            "composition": component.operator,
                            "x_unit": curve.x_unit, "y_unit": curve.y_unit,
                            "value": evaluated[component.id],
                        }))
            observations.append(pd.DataFrame({
                "curve_id": curve.id, "point_index": np.arange(n),
                "original_row_index": curve.row_indices,
                "x": curve.x, "y": curve.y,
                "model_y": total, "residual": curve.y - total, "background": background,
                "sigma_x": curve.current_sigma_x, "sigma_y": curve.current_sigma_y,
                "error_y_minus": curve.current_error_y_minus,
                "error_y_plus": curve.current_error_y_plus,
                "weight": curve.current_weights,
                "masked": curve.effective_mask,
                "valid": ~curve.invalid,
                "finite_xy": np.isfinite(curve.x) & np.isfinite(curve.y),
                "model_valid": np.isfinite(total),
            }))
            metadata.append({
                "series_id": series.id, "series": series.name,
                "curve_id": curve.id, "curve": curve.name, "file_stem": stems[curve.id],
                "source": curve.source or "", "state": str(curve.state),
                "x_label": curve.x_label, "x_unit": curve.x_unit,
                "y_label": curve.y_label, "y_unit": curve.y_unit,
                "points": n, "error_confidence_level": curve.error_confidence_level,
                "weights_are_inverse_variance": curve.weights_are_inverse_variance,
                "fit_ranges": json.dumps(curve.fit_ranges),
                "transformations": json.dumps([item.to_dict() for item in curve.transformations]),
            })
    observation_columns = [
        "curve_id", "point_index", "original_row_index", "x", "y", "model_y", "residual",
        "background", "sigma_x", "sigma_y", "error_y_minus", "error_y_plus", "weight",
        "masked", "valid", "finite_xy", "model_valid",
    ]
    component_columns = [
        "curve_id", "point_index", "component_id", "component", "function_id",
        "is_background", "composition", "x_unit", "y_unit", "value",
    ]
    curve_columns = [
        "series_id", "series", "curve_id", "curve", "file_stem", "source", "state",
        "x_label", "x_unit", "y_label", "y_unit", "points", "error_confidence_level",
        "weights_are_inverse_variance", "fit_ranges", "transformations",
    ]
    return (
        pd.concat(observations, ignore_index=True) if observations else pd.DataFrame(columns=observation_columns),
        pd.concat(components, ignore_index=True) if components else pd.DataFrame(columns=component_columns),
        pd.DataFrame(metadata, columns=curve_columns),
    )


def parameter_dataframe(
    project: Project,
    result: FitResult | Mapping[str, Any] | None = None,
    *,
    registry: FunctionRegistry | None = None,
) -> pd.DataFrame:
    registry = registry or default_registry()
    rows: list[dict[str, Any]] = []
    estimates: Mapping[str, Any] = result.parameters if isinstance(result, FitResult) else {}
    parameter_values = project.resolved_parameter_values()
    for series in project.dataset.series:
        for curve in series.curves:
            model = project.models.get(curve.id)
            if model is None:
                continue
            derived = model.derived_quantities(
                curve_id=curve.id, values=parameter_values, registry=registry
            )
            for component in model.display_components:
                definition = registry.get(component.function_id)
                component_derived = derived.get(component.id, {})
                for name, parameter in component.parameters.items():
                    path = model.parameter_path(curve.id, component.id, name)
                    estimate = estimates.get(path)
                    value = float(parameter_values.get(path, parameter.value))
                    error = getattr(estimate, "standard_error", parameter.standard_error)
                    ci_low = getattr(estimate, "ci_low", parameter.ci_low)
                    ci_high = getattr(estimate, "ci_high", parameter.ci_high)
                    effective_minimum, effective_maximum = parameter.minimum, parameter.maximum
                    if parameter.link and parameter.link_relation != "equal":
                        from curvemole.core.expressions import SafeExpression

                        source = SafeExpression.compile(parameter.link).references[0]
                        effective_minimum, effective_maximum = parameter.link_bounds(parameter_values[source])
                    effective_minimum = getattr(estimate, "minimum", effective_minimum)
                    effective_maximum = getattr(estimate, "maximum", effective_maximum)
                    rows.append(
                        {
                            "series_id": series.id,
                            "series": series.name,
                            "curve": curve.name,
                            "curve_id": curve.id,
                            "curve_state": str(curve.state),
                            "group": component.group or "",
                            "component": component.name,
                            "component_id": component.id,
                            "function": definition.display_name,
                            "function_id": component.function_id,
                            "enabled": component.enabled,
                            "is_background": component.is_background,
                            "composition": component.operator,
                            "parameter": name,
                            "parameter_path": path,
                            "value": value,
                            "standard_error": error,
                            "confidence_interval_low": ci_low,
                            "confidence_interval_high": ci_high,
                            "minimum": parameter.minimum,
                            "maximum": parameter.maximum,
                            "effective_minimum": effective_minimum,
                            "effective_maximum": effective_maximum,
                            "global_minimum": (
                                getattr(estimate, "global_minimum", None)
                                if getattr(estimate, "global_minimum", None) is not None else parameter.minimum
                            ),
                            "global_maximum": (
                                getattr(estimate, "global_maximum", None)
                                if getattr(estimate, "global_maximum", None) is not None else parameter.maximum
                            ),
                            "fixed": parameter.fixed and not (parameter.link and parameter.link_relation == "equal"),
                            "status": parameter.status,
                            "link": parameter.link or "",
                            "link_relation": parameter.link_relation,
                            "link_tolerance": parameter.link_tolerance,
                            "link_tolerance_mode": parameter.link_tolerance_mode,
                            "link_scope": parameter.link_scope,
                            "link_reference_scopes": json.dumps(parameter.link_reference_scopes),
                            "unit": parameter.unit,
                            "human_readable": value_with_error(value, error),
                            "derived_area": component_derived.get("area"),
                            "derived_FWHM": component_derived.get("FWHM"),
                        }
                    )
    return pd.DataFrame(rows, columns=[
        'series_id', 'series', 'curve', 'curve_id',
        'curve_state', 'group', 'component', 'component_id',
        'function', 'function_id', 'enabled', 'is_background',
        'composition', 'parameter', 'parameter_path', 'value',
        'standard_error', 'confidence_interval_low', 'confidence_interval_high', 'minimum',
        'maximum', 'effective_minimum', 'effective_maximum', 'global_minimum',
        'global_maximum', 'fixed', 'status', 'link',
        'link_relation', 'link_tolerance', 'link_tolerance_mode', 'link_scope',
        'link_reference_scopes', 'unit', 'human_readable', 'derived_area',
        'derived_FWHM',
    ])


def export_function_parameters(
    project: Project, path: str | Path, *, include_covariance: bool = False,
) -> Path:
    """Write fit errors and, when selected, separate analysis error bounds."""
    from curvemole.core.analysis_errors import DISPLAY_METHODS, analysis_error, selected_method

    include_analysis = any(selected_method(project, curve.id) for curve in project.curves)
    columns: list[tuple[str, str]] = []
    values: list[dict[tuple[str, str], str]] = []
    resolved = project.resolved_parameter_values()
    for curve in project.curves:
        cells: dict[tuple[str, str], str] = {}
        model = project.models.get(curve.id)
        occurrences: dict[str, int] = {}
        if model is not None:
            for component in model.display_components:
                occurrences[component.name] = occurrences.get(component.name, 0) + 1
                # Keep separately named instances aligned across spectra, even
                # when a model contains more than one with the same name.
                label = (component.name if occurrences[component.name] == 1 else
                         f"{component.name} ({occurrences[component.name]})")
                for name, parameter in component.parameters.items():
                    key = (label, name)
                    if key not in columns:
                        columns.extend((key, (label, f"{name}_err")))
                        if include_analysis:
                            columns.extend(((label, f"{name}_analysis_err_minus"),
                                            (label, f"{name}_analysis_err_plus")))
                    if curve.state == CurveState.FITTED:
                        parameter_path = model.parameter_path(curve.id, component.id, name)
                        value = resolved.get(parameter_path, parameter.value)
                        error = parameter.standard_error
                        cells[key] = f"{value:.12g}"
                        if error is not None and math.isfinite(error) and error >= 0:
                            cells[(label, f"{name}_err")] = f"{error:.12g}"
                        if include_analysis:
                            offsets = analysis_error(project, curve.id, parameter_path)
                            if offsets:
                                cells[(label, f"{name}_analysis_err_minus")] = f"{offsets[0]:.12g}"
                                cells[(label, f"{name}_analysis_err_plus")] = f"{offsets[1]:.12g}"
        values.append(cells)

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Spectrum", *(function for function, _ in columns),
                         *(["Analysis"] if include_analysis else [])])
        writer.writerow(["", *(parameter for _, parameter in columns),
                         *(["method"] if include_analysis else [])])
        for curve, cells in zip(project.curves, values, strict=True):
            method = selected_method(project, curve.id) if include_analysis else None
            writer.writerow([curve.name, *(cells.get(key, "") for key in columns),
                             *([DISPLAY_METHODS.get(method, "")] if include_analysis else [])])
    if include_covariance:
        export_parameter_covariances(project, destination)
    return destination


def export_parameter_covariances(
    project: Project, parameter_path: str | Path, *, _dry_run: bool = False,
) -> list[Path]:
    """Export fit covariance and separate sample covariance for selected analyses.

    A coupled global fit is written once with all cross-spectrum terms intact.
    Profile intervals are not covariance estimates and therefore have no matrix.
    """
    from curvemole.core.analysis_errors import selected_method

    destination = Path(parameter_path)
    directory = destination.with_name(destination.stem + "_covariance")
    records = project.results.get("fit_by_curve", {})
    written: list[Path] = []
    manifest: list[tuple[str, str, str, str, int]] = []
    seen: set[tuple[str, str]] = set()

    def write_matrix(paths: list[str], matrix: np.ndarray, source: str,
                     method: str, curve_name: str, samples: int = 0) -> None:
        if matrix.shape != (len(paths), len(paths)) or not len(paths):
            return
        if not all(np.isfinite(block).all() for block in (matrix.blocks if isinstance(matrix, BlockDiagonalMatrix) else (matrix,))):
            return
        filename = f"{len(written) + 1:03d}_{source}_{method}.csv"
        output = directory / filename
        if not _dry_run:
            directory.mkdir(parents=True, exist_ok=True)
            _write_labeled_matrix(output, matrix, paths)
        written.append(output)
        manifest.append((curve_name, source, method, filename, samples))

    for curve in project.curves:
        if curve.state != CurveState.FITTED:
            continue
        record = records.get(curve.id, {})
        global_key = record.get("global_key")
        key = str(global_key or curve.id)
        fit = (project.results.get("global_fit_baselines", {}).get(global_key)
               if global_key is not None else record.get("baseline"))
        if fit is None:
            latest = project.results.get("last_fit")
            if latest is not None:
                curve_outputs = (latest.curve_outputs if isinstance(latest, FitResult)
                                 else latest.get("curve_outputs", {}))
                if curve.id in curve_outputs:
                    fit = latest
                    key = "legacy-fit"
        if fit is not None and (key, "fit") not in seen:
            seen.add((key, "fit"))
            paths = fit.free_parameter_paths if isinstance(fit, FitResult) else fit.get("free_parameter_paths", [])
            covariance = fit.covariance if isinstance(fit, FitResult) else fit.get("covariance")
            if covariance is not None:
                write_matrix(paths, matrix_from_value(covariance), "fit", "covariance",
                             "Global fit" if global_key is not None else curve.name)
        method = selected_method(project, curve.id)
        if method not in {"parametric_monte_carlo", "residual_bootstrap", "block_bootstrap"}:
            continue
        if (key, method) in seen:
            continue
        seen.add((key, method))
        result = project.results.get("uncertainty_by_curve", {}).get(curve.id, {}).get(method)
        if result is None:
            continue
        paths = result.parameter_paths if hasattr(result, "parameter_paths") else result.get("parameter_paths", [])
        samples = result.samples if hasattr(result, "samples") else result.get("samples")
        if samples is None:
            continue
        samples = np.asarray(samples, dtype=float)
        if samples.ndim != 2 or samples.shape[0] < 2 or samples.shape[1] != len(paths):
            continue
        with np.errstate(invalid="ignore", divide="ignore"):
            covariance = np.atleast_2d(np.cov(samples, rowvar=False))
        write_matrix(paths, covariance, "analysis", method,
                     "Global fit" if global_key is not None else curve.name,
                     len(samples))
    if manifest and not _dry_run:
        with (directory / "index.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Spectrum or scope", "Source", "Method", "File", "Samples"])
            writer.writerows(manifest)
    return written


def _write_labeled_matrix(
    path: Path, matrix: Any, parameter_paths: list[str], *, delimiter: str = ",",
) -> None:
    """Stream matrix rows, retaining labels and block-diagonal memory usage."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter)
        writer.writerow(["parameter_path", *parameter_paths])
        for parameter, row in zip(parameter_paths, matrix, strict=True):
            writer.writerow([parameter, *(f"{value:.12g}" for value in row)])


def fit_settings_dataframe(result: FitResult | None) -> pd.DataFrame:
    """Export the recorded fit configuration, never the current dialog edits."""
    columns = ["timestamp", "curve_ids", "mode", "setting", "value"]
    if result is None:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame([
        {"timestamp": result.timestamp, "curve_ids": ";".join(result.curve_outputs),
         "mode": result.mode.value, "setting": name, "value": json.dumps(value)}
        for name, value in asdict(result.settings).items()
    ], columns=columns)


def uncertainty_dataframe(project: Project) -> pd.DataFrame:
    from curvemole.core.uncertainty_summary import summarize
    rows = []
    by_curve = project.results.get("uncertainty_reports_by_curve", {})
    for curve_id, reports in by_curve.items():
        for method, record in reports.items():
            rows.extend(row for row in summarize(project, record["baseline"], record["analysis"], method)
                        if row["path"].startswith(curve_id + "."))
    for method, record in project.results.get("uncertainty_reports", {}).items():
        rows.extend(row for row in summarize(project, record["baseline"], record["analysis"], method)
                    if method not in by_curve.get(row["path"].split(".", 1)[0], {}))
    return pd.DataFrame(rows)


def value_with_error(value: float, error: float | None) -> str:
    if error is None or not math.isfinite(error) or error <= 0:
        return f"{value:.10g}"
    exponent = math.floor(math.log10(abs(error)))
    digits = max(0, 1 - exponent)
    return f"{value:.{digits}f} ± {error:.{digits}f}"


def export_dataframe(frame: pd.DataFrame, path: str | Path, *, delimiter: str = ",") -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, sep=delimiter, index=False, encoding="utf-8", lineterminator="\n")
    return destination


def export_figure(
    curves: Iterable[Curve], models: Mapping[str, Model], path: str | Path, **kwargs,
) -> Path:
    """Render a standalone scientific figure without loading pyplot."""
    from curvemole.core.figure_export import export_figure as render
    return render(curves, models, path, **kwargs)


def generate_html_report(
    project: Project,
    path: str | Path,
    *,
    result: FitResult | None = None,
    title: str | None = None,
    notes: str = "",
    full: bool = False,
    registry: FunctionRegistry | None = None,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    parameters = parameter_dataframe(project, result, registry=registry)
    statistics = result.statistics if result else {}
    warnings = result.warnings if result else []
    fitted_ids = list(result.curve_outputs) if result else []
    curve_names = {curve.id: curve.name for curve in project.curves}
    fit_scope = "; ".join(f"{curve_names.get(identity, 'Removed spectrum')} ({identity})" for identity in fitted_ids)
    sections = [
        f"<h1>{_escape(title or project.name)}</h1>",
        f"<p><strong>CurveMole {__version__}</strong> — generated {_escape(datetime.now(UTC).isoformat())}</p>",
        f"<p>{_escape(notes)}</p>" if notes else "",
        "<h2>Data and models</h2>",
        f"<p>{len(project.curves)} curve(s), {sum(len(model.components) for model in project.models.values())} component(s).</p>",
        "<h2>Recorded last-fit statistics</h2>",
        (f"<p>Timestamp: {_escape(result.timestamp)}. Scope: {_escape(fit_scope)}. "
         "These statistics cover only this recorded fit, which may contain a subset of the project spectra.</p>") if result else "",
        pd.DataFrame([statistics]).to_html(index=False, border=0) if statistics else "<p>No fit result.</p>",
        "<h2>Parameters</h2>",
        "<p>Current resolved model values. Recorded errors can be stale for modified or unfitted models; check curve_state.</p>",
        parameters.to_html(index=False, border=0, float_format=lambda value: f"{value:.12g}"),
        "<h2>Warnings</h2>",
        "<ul>" + "".join(f"<li>{_escape(item)}</li>" for item in warnings) + "</ul>" if warnings else "<p>None.</p>",
    ]
    if full:
        sections.extend(
            [
                "<h2>Recorded solver and loss settings</h2>",
                fit_settings_dataframe(result).to_html(index=False, border=0),
                "<h2>Reproducibility</h2>",
                f"<pre>{_escape(json.dumps(project.to_metadata(), indent=2, default=str))}</pre>",
            ]
        )
    html = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<style>body{font-family:Arial,sans-serif;max-width:1100px;margin:2rem auto;color:#17212b}
table{border-collapse:collapse;width:100%;font-size:.86rem}th,td{border:1px solid #ccd6df;padding:.35rem;text-align:left}
th{background:#e9f4f2}h1,h2{color:#185c5a}pre{white-space:pre-wrap;font-size:.75rem}</style>
</head><body>""" + "\n".join(sections) + "</body></html>\n"
    destination.write_text(html, encoding="utf-8")
    return destination


def generate_pdf_report(
    project: Project, path: str | Path, *, result: FitResult | None = None,
    title: str | None = None, registry: FunctionRegistry | None = None, **kwargs,
) -> Path:
    """Write vector PDF pages for individual curves with their own fit scope."""
    from curvemole.core.figure_export import generate_pdf_report as render
    return render(project, path, result=result, title=title, registry=registry, **kwargs)


def export_bundle(
    project: Project,
    directory: str | Path,
    *,
    result: FitResult | None = None,
    delimiter: str = ",",
    versioned: bool = False,
    overwrite: bool = False,
    include_uncertainty_samples: bool = True,
    selection: BundleExportSelection | None = None,
    current_view: Any | None = None,
) -> ExportSummary:
    selection = selection or BundleExportSelection()
    if result is None and isinstance(project.results.get("last_fit"), FitResult):
        result = project.results["last_fit"]
    if not selection.any_selected():
        raise CurveMoleError("Select at least one item to export.")

    root = Path(directory)
    if versioned:
        root = root / datetime.now(UTC).strftime("export-%Y%m%d-%H%M%S")

    registry = _registry_for_project(project)
    planned = _bundle_paths(project, result, selection, current_view=current_view)
    if not planned:
        raise CurveMoleError("The selected export items have no available data to write.")

    # Ownership remains in the project; the readable manifest is documentation,
    # never sufficient authority to overwrite somebody else's files.
    previous_owned: set[str] = set()
    stored_directory = project.export_config.get("directory")
    if stored_directory:
        try:
            same_root = Path(str(stored_directory)).resolve(strict=False) == root.resolve(strict=False)
        except OSError:
            same_root = Path(str(stored_directory)) == root
        if same_root:
            previous_owned.update(
                _normalise_owned_path(relative)
                for relative in project.export_config.get("owned_files", [])
            )

    legacy_manifest = root / ".curvemole-export.json"
    if legacy_manifest.exists():
        try:
            previous_owned.update(
                _normalise_owned_path(relative)
                for relative in json.loads(legacy_manifest.read_text(encoding="utf-8")).get(
                    "owned_files", []
                )
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise CurveMoleError(
                f"Existing export manifest is unreadable: {legacy_manifest}. No files were changed."
            ) from exc

    collisions = [relative for relative in planned if (root / relative).exists()]
    if collisions and not overwrite:
        raise FileExistsError(
            "Export would overwrite existing files. Confirm update or choose versioned export: "
            + ", ".join(collisions[:8])
        )
    if collisions and overwrite and not previous_owned:
        raise FileExistsError(
            "Export refused because CurveMole cannot verify ownership of the existing files: "
            + ", ".join(collisions[:8])
        )
    if previous_owned:
        protected_collision = [relative for relative in collisions if relative not in previous_owned]
        if protected_collision:
            raise FileExistsError(
                "Export refused to overwrite files not owned by CurveMole: "
                + ", ".join(protected_collision[:8])
            )

    for relative in planned:
        output = root / relative
        if output.exists() and not output.is_file():
            raise FileExistsError(f"An export file is occupied by a directory: {output}")
        # Protect the chosen bundle tree; system ancestors such as /tmp may
        # legitimately be symlinks on supported platforms.
        destinations = [root.joinpath(*Path(relative).parts[:count])
                        for count in range(len(Path(relative).parts) + 1)]
        if any(destination.is_symlink() for destination in destinations):
            raise FileExistsError(f"Export refuses symbolic-link destinations: {output}")

    root.mkdir(parents=True, exist_ok=True)
    summary = ExportSummary(root)
    before = {relative: _sha256(root / relative) for relative in collisions}
    base = _safe_name(project.name) or "curvemole"
    stems = _curve_export_stems(project)
    parameter_values = project.resolved_parameter_values()

    if selection.spectra and project.curves:
        from curvemole.core.spectrum_export import export_spectra

        export_spectra(project, root / "spectra", [curve.id for curve in project.curves], registry=registry)

    parameter_path = root / "function_parameters.csv"
    if selection.function_parameters:
        export_function_parameters(project, parameter_path)
    if selection.parameter_covariances:
        export_parameter_covariances(project, parameter_path)

    if selection.fit_results:
        export_dataframe(
            parameter_dataframe(project, result, registry=registry),
            root / "fit_results.csv",
            delimiter=delimiter,
        )

    if selection.fit_settings and result is not None:
        export_dataframe(fit_settings_dataframe(result), root / "fit_settings.csv", delimiter=delimiter)

    if selection.wide_tables:
        for curve in project.curves:
            frame = wide_dataframe(
                curve,
                project.models.get(curve.id),
                registry=registry,
                parameter_values=parameter_values,
            )
            export_dataframe(
                frame,
                root / "data" / f"{stems[curve.id]}_wide.csv",
                delimiter=delimiter,
            )

    if selection.tidy_table:
        for name, frame in zip(("observations.csv", "components.csv", "curves.csv"),
                               analysis_dataframes(project, registry=registry), strict=True):
            export_dataframe(frame, root / "python" / name, delimiter=delimiter)
        (root / "python" / "replot.py").write_text(_replot_script(delimiter), encoding="utf-8")

    if selection.results_json:
        results_path = root / "python" / "results.json"
        results_path.parent.mkdir(parents=True, exist_ok=True)
        results_path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "application_version": __version__,
                    "scope": "Recorded fits; current model evaluations are in observations.csv.",
                    "result": result.to_dict(arrays=False) if result else None,
                    "fit_by_curve": project.results.get("fit_by_curve", {}),
                    "global_fit_baselines": project.results.get("global_fit_baselines", {}),
                },
                indent=2,
                default=_json_default,
            )
            + "\n",
            encoding="utf-8",
        )

    if selection.fitmodel:
        for curve in project.curves:
            model = project.models.get(curve.id)
            if model is not None:
                save_fitmodel(model, root / "models" / f"{stems[curve.id]}.fitmodel",
                              custom_functions=project.custom_functions)

    if selection.main_plot_png:
        for curve in project.curves:
            export_figure([curve], project.models, root / "figures" / f"{stems[curve.id]}.png", registry=registry)

    if selection.main_plot_svg:
        for curve in project.curves:
            export_figure([curve], project.models, root / "figures" / f"{stems[curve.id]}.svg", registry=registry)

    if selection.current_view and current_view is not None:
        from curvemole.core.figure_export import export_plot_snapshot

        for relative in ("figures/current_view.png", "figures/current_view.svg", "report/current_view.pdf"):
            export_plot_snapshot(current_view, root / relative)

    if selection.html_summary:
        generate_html_report(
            project,
            root / "summary_report.html",
            result=result,
            registry=registry,
        )

    if selection.html_reproducibility:
        generate_html_report(
            project,
            root / "report" / "full_reproducibility.html",
            result=result,
            full=True,
            registry=registry,
        )

    if selection.pdf_summary:
        for curve in project.curves:
            export_figure([curve], project.models, root / "report" / f"{stems[curve.id]}.pdf", registry=registry)
        generate_pdf_report(
            project,
            root / "report" / "summary.pdf",
            result=result,
            registry=registry,
        )

    if selection.uncertainty and result:
        if result.covariance is not None:
            covariance_path = root / "uncertainty" / "covariance.csv"
            covariance_path.parent.mkdir(parents=True, exist_ok=True)
            _write_labeled_matrix(covariance_path, result.covariance, result.free_parameter_paths, delimiter=delimiter)
        if result.correlation is not None:
            correlation_path = root / "uncertainty" / "correlation.csv"
            correlation_path.parent.mkdir(parents=True, exist_ok=True)
            _write_labeled_matrix(correlation_path, result.correlation, result.free_parameter_paths, delimiter=delimiter)

    if selection.uncertainty and (project.results.get("uncertainty_reports") or
                                  project.results.get("uncertainty_reports_by_curve")):
        export_dataframe(uncertainty_dataframe(project), root / "uncertainty" / "parameter_assessments.csv",
                         delimiter=delimiter)

    if selection.diagnostics and result:
        for curve_id, output in result.curve_outputs.items():
            diagnostics = residual_diagnostics(output.residual)
            diagnostics_path = root / "diagnostics" / f"{curve_id}_autocorrelation.csv"
            diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                {
                    "lag": np.arange(len(diagnostics.autocorrelation)),
                    "autocorrelation": diagnostics.autocorrelation,
                }
            ).to_csv(diagnostics_path, index=False)

    if selection.laboratory_notebook:
        export_notebook(project, root / "laboratory_notebook.txt")

    if "index.csv" in planned:
        export_dataframe(_bundle_curve_index(project, selection, root), root / "index.csv", delimiter=delimiter)

    if selection.readme:
        documented = {"README.txt", "manifest.json"}
        if selection.project_copy:
            documented.add(f"{base}.fitproj")
        actual_paths = sorted(relative for relative in planned
                              if (root / relative).is_file() or relative in documented)
        (root / "manifest.json").write_text(json.dumps({
            "schema_version": 2, "application_version": __version__,
            "project": project.name, "exported_at": datetime.now(UTC).isoformat(),
            "csv_delimiter": delimiter, "selection": selection.to_dict(),
            "files": [{"path": relative, "description": _bundle_file_description(relative)}
                      for relative in actual_paths],
            "curves": _bundle_curve_index(project, selection, root).to_dict(orient="records"),
        }, indent=2, default=_json_default) + "\n", encoding="utf-8")
        (root / "README.txt").write_text(_bundle_readme(project, actual_paths, delimiter), encoding="utf-8")

    written = sorted(relative for relative in planned if (root / relative).is_file()
                     or selection.project_copy and relative == f"{base}.fitproj")
    owned = sorted(previous_owned | set(written))
    project.export_config["directory"] = str(root)
    project.export_config["owned_files"] = owned
    project.export_config["selection"] = selection.to_dict()
    if selection.project_copy:
        # The reopenable copy must know the ownership of this very bundle, not
        # the prior export, so updating it after reopening remains safe.
        save_project(project, root / f"{base}.fitproj",
                     include_uncertainty_samples=include_uncertainty_samples,
                     update_project_path=False)
    for relative in written:
        output_path = root / relative
        if relative in before:
            (summary.unchanged if before[relative] == _sha256(output_path) else summary.updated).append(
                output_path
            )
        else:
            summary.created.append(output_path)

    return summary


def _bundle_paths(
    project: Project,
    result: FitResult | None,
    selection: BundleExportSelection,
    *, current_view: Any | None = None,
) -> list[str]:
    base = _safe_name(project.name) or "curvemole"
    paths: list[str] = []
    stems = _curve_export_stems(project)
    if selection.spectra:
        paths.extend(f"spectra/{name}" for name in _spectrum_export_names(project).values())
    if selection.function_parameters:
        paths.append("function_parameters.csv")
    if selection.parameter_covariances:
        matrices = export_parameter_covariances(project, "function_parameters.csv", _dry_run=True)
        paths.extend(path.as_posix() for path in matrices)
        if matrices:
            paths.append("function_parameters_covariance/index.csv")
    if selection.fit_results:
        paths.append("fit_results.csv")
    if selection.fit_settings and result is not None:
        paths.append("fit_settings.csv")
    if selection.wide_tables:
        paths.extend(
            f"data/{stems[curve.id]}_wide.csv"
            for curve in project.curves
        )
    if selection.tidy_table:
        paths.extend(f"python/{name}" for name in ("observations.csv", "components.csv", "curves.csv", "replot.py"))
    if selection.results_json:
        paths.append("python/results.json")
    if selection.fitmodel:
        paths.extend(f"models/{stems[curve.id]}.fitmodel" for curve in project.curves if curve.id in project.models)
    if selection.project_copy:
        paths.append(f"{base}.fitproj")
    if selection.main_plot_png:
        paths.extend(f"figures/{stems[curve.id]}.png" for curve in project.curves)
    if selection.main_plot_svg:
        paths.extend(f"figures/{stems[curve.id]}.svg" for curve in project.curves)
    if selection.current_view and current_view is not None:
        paths.extend(("figures/current_view.png", "figures/current_view.svg", "report/current_view.pdf"))
    if selection.html_summary:
        paths.append("summary_report.html")
    if selection.html_reproducibility:
        paths.append("report/full_reproducibility.html")
    if selection.pdf_summary:
        paths.append("report/summary.pdf")
        paths.extend(f"report/{stems[curve.id]}.pdf" for curve in project.curves)
    if selection.uncertainty and result:
        if result.covariance is not None:
            paths.append("uncertainty/covariance.csv")
        if result.correlation is not None:
            paths.append("uncertainty/correlation.csv")
    if selection.uncertainty and (project.results.get("uncertainty_reports") or
                                  project.results.get("uncertainty_reports_by_curve")):
        paths.append("uncertainty/parameter_assessments.csv")
    if selection.diagnostics and result:
        paths.extend(
            f"diagnostics/{curve_id}_autocorrelation.csv"
            for curve_id in result.curve_outputs
        )
    if selection.readme:
        paths.extend(("README.txt", "manifest.json"))
    if selection.laboratory_notebook:
        paths.append("laboratory_notebook.txt")
    if project.curves and any((selection.spectra, selection.wide_tables, selection.tidy_table,
                              selection.fitmodel, selection.main_plot_png, selection.main_plot_svg,
                              selection.pdf_summary)):
        paths.append("index.csv")
    return paths


def _curve_export_stems(project: Project) -> dict[str, str]:
    import hashlib

    return {
        curve.id: f"{(_safe_name(curve.name) or 'spectrum')[:64]}__{hashlib.sha256(curve.id.encode()).hexdigest()[:12]}"
        for curve in project.curves
    }


def _spectrum_export_names(project: Project) -> dict[str, str]:
    from curvemole.core.spectrum_export import _deduplicate_filename, spectrum_export_filename

    names: dict[str, str] = {}
    used: set[str] = set()
    for curve in project.curves:
        filename = _deduplicate_filename(spectrum_export_filename(curve), used)
        names[curve.id] = filename
        used.add(filename.casefold())
    return names


def _bundle_curve_index(
    project: Project, selection: BundleExportSelection, root: Path,
) -> pd.DataFrame:
    stems = _curve_export_stems(project)
    spectra = _spectrum_export_names(project) if selection.spectra else {}
    rows = []
    for series in project.dataset.series:
        for curve in series.curves:
            stem = stems[curve.id]
            row = {
                "series_id": series.id, "series": series.name,
                "curve_id": curve.id, "curve": curve.name, "file_stem": stem,
                "source": curve.source or "", "state": str(curve.state),
                "x_label": curve.x_label, "x_unit": curve.x_unit,
                "y_label": curve.y_label, "y_unit": curve.y_unit,
            }
            for key, enabled, relative in (
                ("spectrum_file", selection.spectra, f"spectra/{spectra.get(curve.id, '')}"),
                ("wide_file", selection.wide_tables, f"data/{stem}_wide.csv"),
                ("png_file", selection.main_plot_png, f"figures/{stem}.png"),
                ("svg_file", selection.main_plot_svg, f"figures/{stem}.svg"),
                ("pdf_file", selection.pdf_summary, f"report/{stem}.pdf"),
                ("model_file", selection.fitmodel, f"models/{stem}.fitmodel"),
            ):
                row[key] = relative if enabled and (root / relative).is_file() else ""
            rows.append(row)
    return pd.DataFrame(rows, columns=[
        "series_id", "series", "curve_id", "curve", "file_stem", "source", "state",
        "x_label", "x_unit", "y_label", "y_unit", "spectrum_file", "wide_file",
        "png_file", "svg_file", "pdf_file", "model_file",
    ])


def _bundle_file_description(relative: str) -> str:
    descriptions = {
        "fit_results.csv": "One row per current model parameter, with stable curve/component IDs, links, bounds, units and recorded fit errors.",
        "fit_settings.csv": "Recorded solver and loss settings for the last fit; current dialog edits are excluded.",
        "function_parameters.csv": "Exact quick-export function-parameter matrix: two header rows; one row per spectrum; unfitted spectra have empty parameter cells.",
        "index.csv": "Map stable curve and series IDs, names, source paths, labels and units to each spectrum's exported files.",
        "manifest.json": "Machine-readable inventory, selected export options, delimiter, application version and curve-to-file mapping.",
        "README.txt": "Contents, data schema, units, mask and model-state interpretation, and Python instructions for this export.",
        "python/observations.csv": "One row per curve/point: transformed x/y, current model, residual, background, errors, weights, mask and validity flags.",
        "python/components.csv": "One row per enabled component/point, joined by curve_id and point_index; includes stable component IDs and composition operators.",
        "python/curves.csv": "Curve/series identities, axis labels and units, source, fit state, original row metadata and transformations.",
        "python/replot.py": "Standalone pandas/Matplotlib loader and per-spectrum replot script using the exported numeric evaluations; no CurveMole installation needed.",
        "python/results.json": "Last fit plus per-curve stored fit records and global fit baselines; includes solver settings, statistics, warnings and parameter estimates.",
        "summary_report.html": "Readable project and parameter summary with last-fit statistics; numeric figures are exported separately per spectrum.",
        "report/full_reproducibility.html": "Expanded HTML summary with recorded last-fit settings and project metadata.",
        "report/summary.pdf": "Multi-page vector report with a separate page for every spectrum.",
        "laboratory_notebook.txt": "Project laboratory notebook, notes and recorded analysis history.",
        "uncertainty/covariance.csv": "Last-fit covariance matrix with free_parameter_paths on both axes; cross-spectrum terms are retained.",
        "uncertainty/correlation.csv": "Last-fit correlation matrix with free_parameter_paths on both axes.",
        "uncertainty/parameter_assessments.csv": "Recorded parameter uncertainty assessments, method, bounds and diagnostics.",
    }
    if relative in descriptions:
        return descriptions[relative]
    if "current_view" in relative:
        return "Matplotlib rendering of the screen view captured when Export was pressed, including its visible traces and view settings."
    if relative.startswith("spectra/"):
        return "Exact quick-export spectrum table, retaining the source extension and delimiter; all rows, data, errors, enabled components, current total model and residual."
    if relative.startswith("data/"):
        return "One spectrum in a wide CSV: current transformed data and model evaluations, components, residual, data errors, weights and effective mask."
    if relative.startswith("models/"):
        return "Reusable model for the spectrum identified in index.csv, including its components and project custom-function definitions."
    if relative.startswith("function_parameters_covariance/"):
        return ("Index linking fitted scope, fit/analysis source, uncertainty method, matrix file and sample count."
                if relative.endswith("index.csv") else
                "Labeled fit covariance or selected sample-analysis covariance; independent estimates remain separate, coupled global terms remain together.")
    if relative.startswith("figures/") or relative.startswith("report/") and relative.endswith(".pdf"):
        return "Separate spectrum figure: transformed observations, current model and enabled components, masks, data errors and residual panel."
    if relative.startswith("diagnostics/"):
        return "Residual autocorrelation versus lag from the recorded last-fit output for this curve ID."
    if relative.endswith(".fitproj"):
        return "Complete reopenable CurveMole project snapshot, including all spectra, models, transformations, masks, links, fit records and selected uncertainty samples."
    return "Selected CurveMole export output."


def _bundle_readme(project: Project, paths: list[str], delimiter: str) -> str:
    grouped: dict[str, list[str]] = {}
    individual = []
    for relative in paths:
        directory = relative.split("/", 1)[0]
        if directory in {"spectra", "data", "models", "figures", "diagnostics", "function_parameters_covariance"}:
            grouped.setdefault(directory + "/", []).append(relative)
        elif relative.startswith("report/") and relative.endswith(".pdf") and Path(relative).name not in {"summary.pdf", "current_view.pdf"}:
            grouped.setdefault("report/<spectrum>.pdf", []).append(relative)
        else:
            individual.append(relative)
    inventory = "\n".join([
        *(f"  {relative}\n    {_bundle_file_description(relative)}" for relative in individual),
        *(f"  {directory} ({len(files)} files)\n    {_bundle_file_description(files[0])} See index.csv and manifest.json for individual filenames."
          for directory, files in grouped.items()),
    ])
    return (
        f"CurveMole analysis bundle — {project.name}\n"
        f"Application version: {__version__}\n"
        f"Spectra: {len(project.curves)}. CSV delimiter: {delimiter!r}; encoding: UTF-8.\n\n"
        "START HERE\n"
        "Open the .fitproj to resume the whole analysis. Use per-spectrum figures for sharing, spectra/ for quick numeric exchange, "
        "or python/observations.csv with python/replot.py for independent analysis. "
        "Only selected and available outputs are written. The compact contents list below describes this export; manifest.json contains its exact file inventory.\n\n"
        "IDENTITIES AND FILES\n"
        "index.csv and manifest.json map files to curve_id/series_id, display names, source paths, axis labels and units. "
        "Per-spectrum CSVs, PNGs, SVGs, PDFs and models use a readable name plus a stable ID digest; duplicate names never share files. "
        "The spectra/ folder uses exactly the Quick export spectra format and its source delimiter/extension (a vendor extension still contains a plain text table). "
        "The two header rows of function_parameters.csv are function name and parameter/error name; rows follow project spectrum order, which index.csv also records.\n\n"
        "CURRENT DATA AND RECORDED FITS\n"
        "Wide tables, observations, component samples and per-spectrum figures evaluate the CURRENT model on the CURRENT transformed observations, including unfitted or modified models. "
        "model_y and Total fit are model evaluations, not proof of a converged or up-to-date fit. Check curve_state/state in fit_results.csv or index.csv. "
        "fit_results.csv values are the current resolved model parameters, while its error and confidence columns may retain recorded fit estimates. "
        "Recorded errors should not be interpreted as uncertainties of an unfitted or modified model. "
        "Function quick-export values are populated only for spectra in the Fitted state. "
        "results.json contains the recorded last fit AND fit_by_curve/global_fit_baselines, whose curve IDs and timestamps define their scope. "
        "The fit settings, HTML fit statistics, uncertainty/covariance.csv, uncertainty/correlation.csv and residual autocorrelation describe the LAST fit only. "
        "A last fit can cover a subset of the project. Selected per-curve/sample covariance exports live separately in function_parameters_covariance/. "
        "A .fitmodel contains one spectrum model; use the .fitproj to preserve cross-spectrum relationships and the complete analysis.\n\n"
        "PYTHON TABLE SCHEMA\n"
        "python/observations.csv has exactly one row per CURRENT point. Its unique key is (curve_id, point_index), with point_index zero-based in current row order. "
        "original_row_index is zero-based in the imported data. X values may repeat: never join on x alone. "
        "x/y are transformed observations; model_y is the current total; residual = y - model_y; background is the current background evaluation. "
        "Absent errors, weights or model values are empty, not zero. python/curves.csv supplies series/name/source, axis units, transformations and state. "
        "python/components.csv joins on (curve_id, point_index), with component_id distinguishing duplicate component names. "
        "Component values are individual function evaluations; follow their composition operators (add/multiply/divide/convolve) rather than summing them blindly. "
        "Background subtraction is not applied to the exported observations.\n\n"
        "UNITS, ERRORS AND MASKS\n"
        "x and sigma_x use x_unit; y, model_y, residual, background, sigma_y and error_y_minus/plus use y_unit. "
        "Component values carry their curve's axis units as context; multiplicative or divisive factors may have different dimensional meaning according to the model. "
        "Parameter units are in fit_results.csv; covariance entry (i,j) has parameter-unit(i) times parameter-unit(j), and correlation is dimensionless. "
        "sigma_y is a standard deviation; error_y_minus/plus are confidence-interval half-widths at curves.csv error_confidence_level, not standard deviations. "
        "weight follows weights_are_inverse_variance: true means inverse variance; false means a direct residual multiplier. "
        "masked=true is the CURRENT effective exclusion, combining all masks, nonfinite/invalid observations or Y errors/weights, and fit ranges. "
        "valid checks current observation/Y-error/weight validity; finite_xy only checks x and y; model_valid checks the current total evaluation. "
        "All points remain in the tables, including exclusions. masked is not a historical fit-inclusion flag: recorded solver options may have ignored data errors, or masks may have changed since fitting.\n\n"
        "RELOAD AND REPLOT\n"
        "Install pandas and matplotlib, then run: python python/replot.py\n"
        "The script resolves tables relative to itself and writes separate SVG/PNG figures into python/replotted/. "
        "It uses exported evaluated arrays and therefore does not require CurveMole or rerun a fit. "
        "Residuals exclude currently masked points; models with multiplication, division or convolution show their total without misleading raw-operand overlays. "
        "To resume or refit the full analysis, open the .fitproj in CurveMole. "
        "The legacy tidy_dataframe Python API remains available; the bundle uses observations/components tables to avoid repeated masks, weights and observations as artificial traces.\n\n"
        "CONTENTS OF THIS EXPORT\n" + inventory + "\n"
    )


def _replot_script(delimiter: str) -> str:
    return '''"""Reload CurveMole analysis tables and replot each spectrum independently.

Requires: pandas, matplotlib. Run from any directory: python /path/to/python/replot.py
The saved model/component arrays are reproduced; this script does not refit data.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
SEPARATOR = ''' + repr(delimiter) + '''


def load():
    """Return observations, components and curve metadata; join by IDs, never X."""
    observations = pd.read_csv(ROOT / "observations.csv", sep=SEPARATOR)
    components = pd.read_csv(ROOT / "components.csv", sep=SEPARATOR)
    curves = pd.read_csv(ROOT / "curves.csv", sep=SEPARATOR, keep_default_na=False)
    return observations, components, curves


def replot():
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    observations, components, curves = load()
    destination = ROOT / "replotted"
    destination.mkdir(exist_ok=True)
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": "#A7B4BC", "axes.labelcolor": "#263D48",
                         "xtick.color": "#52636C", "ytick.color": "#52636C"}):
        for curve in curves.itertuples(index=False):
            sample = observations.loc[observations.curve_id == curve.curve_id].sort_values("point_index")
            figure, (axis, residual) = plt.subplots(2, 1, figsize=(8, 5.5), sharex=True,
                                                   gridspec_kw={"height_ratios": [3, 1]},
                                                   layout="constrained")
            keep = sample.finite_xy & ~sample.masked
            excluded = sample.finite_xy & sample.masked
            axis.plot(sample.loc[keep, "x"], sample.loc[keep, "y"], ".", ms=3,
                      color="#087F8C", label="Data")
            axis.plot(sample.loc[excluded, "x"], sample.loc[excluded, "y"], "x", ms=3,
                      color="#B4BDC3", label="Excluded" if excluded.any() else None)
            if sample.model_y.notna().any():
                axis.plot(sample.x, sample.model_y, color="#E88B52", lw=1.8, label="Current model")
                residual.plot(sample.loc[keep, "x"], sample.loc[keep, "residual"], color="#087F8C", lw=.8)
            selected = components.loc[components.curve_id == curve.curve_id]
            # Raw multiplication/division/convolution operands are not
            # independently additive traces on the observed Y axis.
            additive = selected.loc[selected.composition == "add"] if selected.composition.eq("add").all() else selected.iloc[:0]
            for _, component in additive.groupby("component_id", sort=False):
                component = component.sort_values("point_index")
                points = component.merge(sample[["point_index", "x"]], on="point_index", validate="one_to_one")
                axis.plot(points.x, points.value, "--", lw=.9, alpha=.8, label=str(component.component.iloc[0]))
            axis.set_title(str(curve.curve), loc="left", fontweight="bold", color="#263D48")
            axis.set_ylabel(str(curve.y_label) + (f" [{curve.y_unit}]" if curve.y_unit else ""))
            residual.set_xlabel(str(curve.x_label) + (f" [{curve.x_unit}]" if curve.x_unit else ""))
            residual.set_ylabel("Residual")
            residual.axhline(0, color="#A7B4BC", lw=.7)
            axis.legend(frameon=False, fontsize=8)
            for panel in (axis, residual):
                panel.grid(axis="y", color="#E6ECEF", lw=.6)
            for extension in ("svg", "png"):
                figure.savefig(destination / (str(curve.file_stem) + "." + extension), dpi=240)
            plt.close(figure)
    return destination


if __name__ == "__main__":
    print(replot())
'''


def _registry_for_project(project: Project) -> FunctionRegistry:
    registry = default_registry()
    for value in project.custom_functions:
        if not value.get("formula"):
            continue
        definition = formula_definition(
            value["identifier"],
            value.get("display_name", value["identifier"]),
            value["formula"],
            kind=value.get("kind", "generic"),
            defaults=value.get("defaults"),
            bounds={key: tuple(bounds) for key, bounds in value.get("bounds", {}).items()},
            derived_formulas=value.get("derived_formulas", {}),
        )
        registry.register(definition, replace=True)
    return registry


def _resolved_values(models: Mapping[str, Model]) -> dict[str, float]:
    from curvemole.core.parameters import resolve_parameter_values

    parameters = {
        path: parameter
        for curve_id, model in models.items()
        for path, parameter in model.parameter_map(curve_id).items()
    }
    return resolve_parameter_values(parameters)


def _tidy_column(column: str) -> tuple[str, str]:
    if column.startswith("Component | "):
        parts = column.split(" | ")
        return parts[1], "component"
    return "", column


def _label(name: str, unit: str) -> str:
    return f"{name} [{unit}]" if unit else name


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")


def _normalise_owned_path(value: object) -> str:
    """Return a platform-independent key for an export-manifest path."""
    return str(value).replace("\\", "/")


def _escape(value: str) -> str:
    import html

    return html.escape(value)


def _sha256(path: Path) -> str:
    import hashlib

    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(type(value).__name__)
