"""Tabular exports: data, fitted functions, parameters, covariances and uncertainty."""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from curvemole.core.data import Curve, CurveState
from curvemole.core.export_columns import ExportColumns
from curvemole.core.fitting import FitMode, FitResult
from curvemole.core.matrices import BlockDiagonalMatrix, matrix_from_value
from curvemole.core.models import Model
from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry, default_registry
from curvemole.core.results_store import ResultKey

if TYPE_CHECKING:
    import pandas as pd
from curvemole.core.export.common import (
    ExportSelection,
    _curve_export_stems,
    _label,
    _registry_for_project,
    _tidy_column,
)


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
    columns = ExportColumns()
    if selection.original_x:
        columns.add(f"{curve.x_label} original", curve.original_x[curve.row_indices], role="original_x")
    if selection.x:
        columns.add(_label(curve.x_label, curve.x_unit), curve.x, role="x")
    if selection.y:
        columns.add(_label(curve.y_label, curve.y_unit), curve.y, role="y")
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
    if selection.sigma_y and curve.current_sigma_x is not None:
        # The selection covers data uncertainties; X errors belong with them.
        columns["sigma_x"] = curve.current_sigma_x
    if selection.sigma_y and curve.current_sigma_y is not None:
        columns["sigma_y"] = curve.current_sigma_y
    if selection.sigma_y and curve.current_error_y_minus is not None:
        columns["error_y_minus"] = curve.current_error_y_minus
        columns["error_y_plus"] = curve.current_error_y_plus
        columns["error_confidence_percent"] = curve.error_confidence_level * 100
    if selection.weights and curve.current_weights is not None:
        columns["weight"] = curve.current_weights
        columns["weights_are_inverse_variance"] = np.full(len(curve), int(curve.weights_are_inverse_variance))
    if selection.mask_flag:
        columns["masked"] = curve.effective_mask
    frame = pd.DataFrame(columns)
    frame.attrs["column_roles"] = columns.roles
    return frame


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
            roles = wide.attrs.get("column_roles", {})
            x_column = roles.get("x")
            x_values = curve.x if x_column is None else wide[x_column].to_numpy()
            for column in wide.columns:
                if column in {x_column, roles.get("original_x")}:
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
    incompatible = set()
    if isinstance(result, FitResult):
        from curvemole.core.fit_records import fit_model_matches

        recorded_hashes = result.provenance.get("input_hashes", {})
        schema = result.provenance.get("schema_version", 1)
        current_curves = {curve.id: curve for curve in project.curves}
        for curve_id, output in result.curve_outputs.items():
            curve = current_curves.get(curve_id)
            model = project.models.get(curve_id)
            if (curve is None or model is None
                    or (not result.success and (result.mode == FitMode.GLOBAL or curve.state != CurveState.FITTED))
                    or (curve_id in recorded_hashes and not curve.matches_fit_input_hash(recorded_hashes[curve_id], schema))
                    or np.any(output.indices < 0) or np.any(output.indices >= len(curve))
                    or not np.array_equal(curve.x[output.indices], output.x)
                    or not np.array_equal(curve.y[output.indices], output.observed)
                    or not fit_model_matches(result, curve_id, model, parameter_values)):
                incompatible.add(curve_id)
        if incompatible and result.mode == FitMode.GLOBAL:
            incompatible.update(result.curve_outputs)
    for series in project.dataset.series:
        for curve in series.curves:
            model = project.models.get(curve.id)
            if model is None:
                continue
            derived = model.derived_quantities(
                curve_id=curve.id, values=parameter_values, registry=registry
            )
            compatible_data = curve.id not in incompatible
            for component in model.display_components:
                definition = registry.get(component.function_id)
                component_derived = derived.get(component.id, {})
                for name, parameter in component.parameters.items():
                    path = model.parameter_path(curve.id, component.id, name)
                    estimate = estimates.get(path)
                    value = float(parameter_values.get(path, parameter.value))
                    compatible = compatible_data and (estimate is None or value == estimate.value)
                    if not compatible:
                        estimate = None
                    error = getattr(estimate, "standard_error", parameter.standard_error) if compatible else None
                    ci_low = getattr(estimate, "ci_low", parameter.ci_low) if compatible else None
                    ci_high = getattr(estimate, "ci_high", parameter.ci_high) if compatible else None
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
    # Logical column identities are independent of text labels. A literal
    # "Peak (2)" and the second "Peak" are different functions.
    columns = {}
    values = []
    resolved = project.resolved_parameter_values()
    reserved = {component.name for model in project.models.values() for component in model.components}
    component_labels = {}
    used_fields = {}
    for curve in project.curves:
        cells = {}
        model = project.models.get(curve.id)
        occurrences: dict[str, int] = {}
        if model is not None:
            for component in model.display_components:
                count = occurrences[component.name] = occurrences.get(component.name, 0) + 1
                identity = component.name, count
                if identity not in component_labels:
                    label = component.name
                    if count > 1:
                        suffix = count
                        label = f"{component.name} ({suffix})"
                        while label in reserved:
                            suffix += 1
                            label = f"{component.name} ({suffix})"
                        reserved.add(label)
                    component_labels[identity] = label
                    used_fields[identity] = set()
                label = component_labels[identity]
                fields = ("value", "err", "analysis_err_minus", "analysis_err_plus") if include_analysis else ("value", "err")
                for name, parameter in component.parameters.items():
                    for field in fields:
                        key = identity, name, field
                        if key not in columns:
                            header = name if field == "value" else f"{name}_{field}"
                            while header in used_fields[identity]:
                                header += "_"
                            used_fields[identity].add(header)
                            columns[key] = label, header
                    if curve.state == CurveState.FITTED:
                        parameter_path = model.parameter_path(curve.id, component.id, name)
                        value = resolved.get(parameter_path, parameter.value)
                        error = parameter.standard_error
                        cells[identity, name, "value"] = f"{value:.12g}"
                        if error is not None and math.isfinite(error) and error >= 0:
                            cells[identity, name, "err"] = f"{error:.12g}"
                        if include_analysis:
                            offsets = analysis_error(project, curve.id, parameter_path)
                            if offsets:
                                cells[identity, name, "analysis_err_minus"] = f"{offsets[0]:.12g}"
                                cells[identity, name, "analysis_err_plus"] = f"{offsets[1]:.12g}"
        values.append(cells)

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Spectrum", *(function for function, _ in columns.values()),
                         *(["Analysis"] if include_analysis else [])])
        writer.writerow(["", *(parameter for _, parameter in columns.values()),
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
    records = project.results.get(ResultKey.FIT_BY_CURVE, {})
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
        fit = (project.results.get(ResultKey.GLOBAL_FIT_BASELINES, {}).get(global_key)
               if global_key is not None else record.get("baseline"))
        if fit is None:
            latest = project.results.get(ResultKey.LAST_FIT)
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
        result = project.results.get(ResultKey.UNCERTAINTY_BY_CURVE, {}).get(curve.id, {}).get(method)
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
    by_curve = project.results.get(ResultKey.UNCERTAINTY_REPORTS_BY_CURVE, {})
    for curve_id, reports in by_curve.items():
        for method, record in reports.items():
            rows.extend(row for row in summarize(project, record["baseline"], record["analysis"], method)
                        if row["path"].startswith(curve_id + "."))
    for method, record in project.results.get(ResultKey.LEGACY_UNCERTAINTY_REPORTS, {}).items():
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

