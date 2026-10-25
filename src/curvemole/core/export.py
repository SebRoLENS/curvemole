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
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
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
    import pandas as pd

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
    import pandas as pd

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
    import pandas as pd

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
    import pandas as pd

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
    import pandas as pd

    columns = ["timestamp", "curve_ids", "mode", "setting", "value"]
    if result is None:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame([
        {"timestamp": result.timestamp, "curve_ids": ";".join(result.curve_outputs),
         "mode": result.mode.value, "setting": name, "value": json.dumps(value)}
        for name, value in asdict(result.settings).items()
    ], columns=columns)


def uncertainty_dataframe(project: Project) -> pd.DataFrame:
    import pandas as pd

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
    import pandas as pd

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
    import pandas as pd

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
            export_figure([curve], project.models, root / "figures" / "png" / f"{stems[curve.id]}.png", registry=registry)

    if selection.main_plot_svg:
        for curve in project.curves:
            export_figure([curve], project.models, root / "figures" / "svg" / f"{stems[curve.id]}.svg", registry=registry)

    if selection.current_view and current_view is not None:
        from curvemole.core.figure_export import export_plot_snapshot

        for relative in ("figures/png/current_view.png", "figures/svg/current_view.svg", "figures/pdf/current_view.pdf"):
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
            export_figure([curve], project.models, root / "figures" / "pdf" / f"{stems[curve.id]}.pdf", registry=registry)
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
        paths.extend(f"figures/png/{stems[curve.id]}.png" for curve in project.curves)
    if selection.main_plot_svg:
        paths.extend(f"figures/svg/{stems[curve.id]}.svg" for curve in project.curves)
    if selection.current_view and current_view is not None:
        paths.extend(("figures/png/current_view.png", "figures/svg/current_view.svg", "figures/pdf/current_view.pdf"))
    if selection.html_summary:
        paths.append("summary_report.html")
    if selection.html_reproducibility:
        paths.append("report/full_reproducibility.html")
    if selection.pdf_summary:
        paths.append("report/summary.pdf")
        paths.extend(f"figures/pdf/{stems[curve.id]}.pdf" for curve in project.curves)
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
    import pandas as pd

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
                ("png_file", selection.main_plot_png, f"figures/png/{stem}.png"),
                ("svg_file", selection.main_plot_svg, f"figures/svg/{stem}.svg"),
                ("pdf_file", selection.pdf_summary, f"figures/pdf/{stem}.pdf"),
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
        "fit_results.csv": "Current parameter values, units, bounds and links, with recorded fit errors. One row per parameter.",
        "fit_settings.csv": "Solver and loss settings recorded for the last fit.",
        "function_parameters.csv": "Quick-export parameter table: one row per spectrum, with function and parameter names in two header rows.",
        "index.csv": "Look up each spectrum's name, source, axis units and exported filenames using its stable ID.",
        "manifest.json": "Exact file inventory and export settings for software or automated processing.",
        "README.txt": "This guide to the exported files, their interpretation and use.",
        "python/observations.csv": "Measured points, current model, residuals, background, errors, weights and exclusion flags. One row per point.",
        "python/components.csv": "Evaluated values for each enabled model component, with its identity and composition operator.",
        "python/curves.csv": "Spectrum names, sources, axis labels and units, fit state and applied transformations.",
        "python/replot.py": "Run this pandas/Matplotlib script to redraw each spectrum from the exported tables, without CurveMole.",
        "python/results.json": "Stored fit records, including settings, statistics, warnings and parameter estimates, with their scope and timestamps.",
        "summary_report.html": "Open in a browser to read the project, parameter and last-fit statistics summary.",
        "report/full_reproducibility.html": "Extended browser report with recorded fit settings and project metadata.",
        "report/summary.pdf": "Combined PDF report, with one page for each spectrum.",
        "laboratory_notebook.txt": "Project notes and recorded analysis history.",
        "uncertainty/covariance.csv": "Last-fit parameter covariance matrix, including relationships across jointly fitted spectra.",
        "uncertainty/correlation.csv": "Last-fit parameter correlation matrix, labeled by parameter path.",
        "uncertainty/parameter_assessments.csv": "Recorded uncertainty estimates, methods, bounds and diagnostic information for parameters.",
    }
    if relative in descriptions:
        return descriptions[relative]
    if relative.startswith("figures/") and Path(relative).stem == "current_view":
        return "Snapshot of the visible plot when Export was pressed, redrawn with Matplotlib using the captured traces and view settings."
    if relative.startswith("spectra/"):
        return "Quick-export spectrum tables with data, errors, current model, components and residuals; source extensions and delimiters are retained."
    if relative.startswith("data/"):
        return "One CSV per spectrum, with measured data, current model and components, residuals, errors, weights and exclusion flags in columns."
    if relative.startswith("models/"):
        return "One reusable model per spectrum, including its components and custom-function definitions."
    if relative.startswith("function_parameters_covariance/"):
        return ("Guide to the covariance files: fitted spectra, fit or analysis source, method, matrix filename and sample count."
                if relative.endswith("index.csv") else
                "Parameter covariance matrices from fits or selected sample analyses; joint fits retain cross-spectrum relationships.")
    if relative.startswith("figures/") or relative.startswith("report/") and relative.endswith(".pdf"):
        image_format = Path(relative).suffix.lstrip(".").upper()
        format_note = {
            "PNG": "PNG images for documents and presentations.",
            "SVG": "Editable SVG vector images that stay sharp when resized.",
            "PDF": "Vector PDF figures for printing and sharing.",
        }.get(image_format, "Spectrum figures.")
        return f"{format_note} One file per spectrum, with data, current model, components, errors and residuals."
    if relative.startswith("diagnostics/"):
        return "Residual autocorrelation versus lag, one CSV per spectrum covered by the last fit."
    if relative.endswith(".fitproj"):
        return "Open in CurveMole to resume the analysis: spectra, models, transformations, masks, parameter links, fit records and saved uncertainty samples."
    return "Selected CurveMole export output."


def _bundle_readme_text(value: str) -> str:
    """Keep user-controlled names on one line without breaking table columns."""
    escapes = {"\n": r"\n", "\r": r"\r", "\t": r"\t", "|": r"\u007c"}
    return "".join(escapes.get(char, char if char.isprintable() else f"\\u{ord(char):04x}")
                   for char in str(value))


def _bundle_readme_inventory(paths: list[str]) -> list[tuple[str, list[tuple[str, str]]]]:
    """Group repeated per-spectrum files while keeping snapshots and metadata explicit."""
    categories: dict[str, list[tuple[str, str]]] = {
        "Figures": [],
        "Data tables": [],
        "Fit parameters and uncertainty": [],
        "Project and Python": [],
        "Reports and documentation": [],
    }
    families: dict[str, list[str]] = {}
    for relative in sorted(set(paths)):
        family = None
        if relative.startswith("figures/"):
            category = "Figures"
            if Path(relative).stem != "current_view":
                family = str(Path(relative).parent.as_posix()) + "/*" + Path(relative).suffix
        elif relative.startswith(("spectra/", "data/")):
            category = "Data tables"
            family = "spectra/*" if relative.startswith("spectra/") else "data/*_wide.csv"
        elif relative in {"fit_results.csv", "fit_settings.csv", "function_parameters.csv"} or relative.startswith(("function_parameters_covariance/", "uncertainty/", "diagnostics/")):
            category = "Fit parameters and uncertainty"
            if relative.startswith("diagnostics/"):
                family = "diagnostics/*_autocorrelation.csv"
            elif relative.startswith("function_parameters_covariance/") and not relative.endswith("/index.csv"):
                family = "function_parameters_covariance/[0-9]*.csv"
        elif relative.endswith(".fitproj") or relative.startswith(("models/", "python/")) or relative == "index.csv":
            category = "Project and Python"
            if relative.startswith("models/"):
                family = "models/*.fitmodel"
        else:
            category = "Reports and documentation"
        if family is None:
            categories[category].append((relative, _bundle_file_description(relative)))
        else:
            families.setdefault(family, []).append(relative)
            if len(families[family]) == 1:
                categories[category].append((family, _bundle_file_description(relative)))

    output = []
    for category, rows in categories.items():
        if not rows:
            continue
        expanded = []
        for name, description in sorted(rows):
            if name in families:
                count = len(families[name])
                name += f" ({count} {'file' if count == 1 else 'files'})"
            expanded.append((name, description))
        output.append((category, expanded))
    return output


def _bundle_readme_table(rows: list[tuple[str, str]]) -> str:
    from textwrap import wrap

    name_width, description_width = 48, 66
    lines = [f"{'File or folder':<{name_width}} | What it contains",
             f"{'-' * name_width}-+-{'-' * description_width}"]
    for name, description in rows:
        names = wrap(_bundle_readme_text(name), name_width, break_on_hyphens=False) or [""]
        descriptions = wrap(_bundle_readme_text(description), description_width,
                            break_on_hyphens=False) or [""]
        for index in range(max(len(names), len(descriptions))):
            name_line = names[index] if index < len(names) else ""
            description_line = descriptions[index] if index < len(descriptions) else ""
            lines.append(f"{name_line:<{name_width}} | {description_line}")
    return "\n".join(lines)


def _bundle_readme(project: Project, paths: list[str], delimiter: str) -> str:
    from textwrap import fill

    available = set(paths)
    lines = [f"CurveMole analysis bundle — {_bundle_readme_text(project.name)}",
             f"Application version: {__version__}",
             f"Spectra: {len(project.curves)}. CSV delimiter: {delimiter!r}; encoding: UTF-8.",
             "", "This folder contains the selected, available outputs of your analysis.",
             "Only files included in this export are listed below.", "", "Contents of this export", "======================="]
    for category, rows in _bundle_readme_inventory(paths):
        lines.extend(("", category, _bundle_readme_table(rows)))
    if any(path.startswith("figures/") and Path(path).stem == "current_view" for path in paths):
        lines.extend(("", "Figure groups (*) cover per-spectrum images; current_view files are listed separately."))

    def section(title: str, paragraphs: list[str]) -> None:
        if paragraphs:
            lines.extend(("", title, "-" * len(title)))
            lines.extend(fill(paragraph, width=100, initial_indent="- ", subsequent_indent="  ",
                              break_long_words=False, break_on_hyphens=False)
                         for paragraph in paragraphs)

    start = []
    project_files = sorted(path for path in paths if path.endswith(".fitproj"))
    if project_files:
        start.append(f"Open {_bundle_readme_text(project_files[0])} in CurveMole to resume or refit the complete analysis.")
    figure_formats = [(extension, explanation) for extension, explanation in (
        ("png", "convenient image sharing"), ("svg", "editable vector graphics"),
        ("pdf", "individual printable figures"),
    ) if any(path.startswith(f"figures/{extension}/") for path in paths)]
    if figure_formats:
        choices = "; ".join(f"figures/{extension} for {explanation}"
                            for extension, explanation in figure_formats)
        start.append(f"Use {choices}. Each format has its own folder.")
    if "index.csv" in available:
        start.append("Use index.csv to find the files belonging to a spectrum. Names include a stable ID suffix, so spectra with the same display name still have different files.")
    if "manifest.json" in available:
        start.append("manifest.json contains its exact file inventory, export settings and curve-to-file mapping.")
    if any(path.startswith("spectra/") for path in paths):
        start.append("spectra/ contains the same tables as Quick export spectra. A vendor extension still contains a plain-text table; its delimiter follows the source file.")
    if "function_parameters.csv" in available:
        start.append("function_parameters.csv is the Quick export function parameters table. The first two rows name the function and parameter/error; spectra follow project order. Parameter cells are empty unless the spectrum is in the Fitted state.")
    section("Using these files", start)

    interpretation = []
    if any(path.startswith(("data/", "spectra/")) or path == "python/observations.csv"
           or path.startswith("figures/") and Path(path).stem != "current_view" for path in paths):
        interpretation.append("Data tables and per-spectrum figures use the CURRENT model and CURRENT transformed observations, even if a model is unfitted or has changed. A model curve is not proof of a converged or up-to-date fit. Background subtraction is not applied to the exported observations.")
    if "fit_results.csv" in available:
        interpretation.append("fit_results.csv gives current resolved parameter values. Its error and confidence columns may retain recorded fit estimates; these are not uncertainties of a model changed since fitting. Check curve_state/state for the spectrum's fit status.")
    recorded = {"fit_settings.csv", "python/results.json", "summary_report.html",
                "report/full_reproducibility.html", "uncertainty/covariance.csv", "uncertainty/correlation.csv"}
    if available & recorded or any(path.startswith("diagnostics/") for path in paths):
        interpretation.append("Recorded settings, fit statistics, covariance/correlation matrices and residual autocorrelation describe the LAST fit. It may cover only part of the project. Stored fit records in results.json, when included, identify their curve IDs, scope and timestamps (fit_by_curve/global_fit_baselines).")
    if any(path.startswith("function_parameters_covariance/") for path in paths):
        interpretation.append("function_parameters_covariance/ keeps selected fit or sample-analysis covariance estimates separate. Its index identifies their source and scope; jointly fitted parameters keep their cross-spectrum terms.")
    if any(path.endswith(".fitmodel") for path in paths):
        interpretation.append("Each .fitmodel stores one spectrum's model. A complete .fitproj project snapshot is needed to preserve cross-spectrum relationships and resume the whole analysis.")
    section("Current model and recorded fits", interpretation)

    if "python/observations.csv" in available:
        section("Understanding the Python tables", [
            "observations.csv has one row per current point. Join tables using (curve_id, point_index): point_index starts at zero in current row order. original_row_index starts at zero in the imported data. X values can repeat, so never join on x alone.",
            "x/y are transformed measurements; model_y is the current total model; residual = y - model_y; background is the evaluated background. Missing model values, errors or weights are empty, not zero. curves.csv holds the names, sources, transformations, state and units.",
            "components.csv uses the same point keys plus component_id to distinguish components with the same name. Values are individual function evaluations: follow add/multiply/divide/convolve operators rather than blindly summing them.",
        ])
        section("Units, errors and excluded points", [
            "x and sigma_x use x_unit. y, model_y, residual, background, sigma_y and error_y_minus/plus use y_unit. Component units provide axis context; multiplication or division factors can have a different dimensional meaning.",
            "sigma_y is a standard deviation. error_y_minus/plus are confidence-interval half-widths at error_confidence_level in curves.csv. For weight, weights_are_inverse_variance=true means inverse variance; false means a direct residual multiplier.",
            "masked=true marks a CURRENT exclusion: masks, fit ranges or invalid observations, Y errors or weights. All points stay in the tables. masked is not a historical fit-inclusion flag: masks or solver options may have changed since fitting.",
            "valid checks observations, Y errors and weights; finite_xy checks only x/y; model_valid checks the current model evaluation. These flags describe different checks and are not interchangeable.",
        ])
    if "fit_results.csv" in available or any(path.startswith(("uncertainty/", "function_parameters_covariance/")) for path in paths):
        unit_notes = []
        if "fit_results.csv" in available:
            unit_notes.append("Parameter units are listed in fit_results.csv.")
        if any(path.startswith(("uncertainty/", "function_parameters_covariance/")) for path in paths):
            unit_notes.append("Covariance entry (i,j) has parameter-unit(i) times parameter-unit(j). Correlations are dimensionless; matrix labels identify the parameters.")
        section("Parameter units", unit_notes)
    if "python/replot.py" in available:
        section("Redraw the figures in Python", [
            "Install pandas and matplotlib, then run: python python/replot.py",
            "The script locates its tables relative to itself and writes PNG images in python/replotted/png/ and SVG images in python/replotted/svg/. It redraws exported values without installing CurveMole or rerunning a fit.",
            "Replotted residuals exclude currently masked points. Models using multiplication, division or convolution show their total without misleading raw-component overlays.",
        ])
    return "\n".join(lines) + "\n"


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
    for extension in ("svg", "png"):
        (destination / extension).mkdir(parents=True, exist_ok=True)
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
                figure.savefig(destination / extension / (str(curve.file_stem) + "." + extension), dpi=240)
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
