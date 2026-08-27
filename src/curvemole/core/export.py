"""Human-friendly and automation-friendly exports and analysis bundles."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if "MPLCONFIGDIR" not in os.environ:
    preferred_cache = Path.home() / ".cache" / "curvemole" / "matplotlib"
    try:
        preferred_cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        preferred_cache = Path(tempfile.gettempdir()) / "curvemole-matplotlib"
        preferred_cache.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(preferred_cache)
import matplotlib  # noqa: E402

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from curvemole.core.data import Curve
from curvemole.core.diagnostics import residual_diagnostics
from curvemole.core.errors import CurveMoleError
from curvemole.core.fitting import FitResult
from curvemole.core.functions import formula_definition
from curvemole.core.models import Model
from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry, default_registry
from curvemole.core.serialization import save_fitmodel, save_project
from curvemole.version import __version__


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
    """User-selectable contents for an analysis export."""

    fit_results: bool = True
    wide_tables: bool = False
    tidy_table: bool = False
    results_json: bool = False
    fitmodel: bool = False
    project_copy: bool = False
    main_plot_png: bool = False
    main_plot_svg: bool = False
    html_summary: bool = False
    html_reproducibility: bool = False
    pdf_summary: bool = False
    uncertainty: bool = False
    diagnostics: bool = False
    readme: bool = False

    def any_selected(self) -> bool:
        return any(self.to_dict().values())

    def to_dict(self) -> dict[str, bool]:
        return {
            "fit_results": self.fit_results,
            "wide_tables": self.wide_tables,
            "tidy_table": self.tidy_table,
            "results_json": self.results_json,
            "fitmodel": self.fitmodel,
            "project_copy": self.project_copy,
            "main_plot_png": self.main_plot_png,
            "main_plot_svg": self.main_plot_svg,
            "html_summary": self.html_summary,
            "html_reproducibility": self.html_reproducibility,
            "pdf_summary": self.pdf_summary,
            "uncertainty": self.uncertainty,
            "diagnostics": self.diagnostics,
            "readme": self.readme,
        }


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
        columns[f"{curve.x_label} original"] = curve.original_x
    if selection.x:
        columns[_label(curve.x_label, curve.x_unit)] = curve.x
    if selection.y:
        columns[_label(curve.y_label, curve.y_unit)] = curve.y
    if model is not None and model.components:
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
                curve.x, curve_id=curve.id, values=parameter_values, registry=registry
            )
        if selection.components:
            for component in model.components:
                if component.enabled and component.id in components:
                    columns[f"Component | {component.name} | {component.function_id}"] = components[
                        component.id
                    ]
    if selection.sigma_y and curve.current_sigma_y is not None:
        columns["sigma_y"] = curve.current_sigma_y
    if selection.weights and curve.weights is not None:
        columns["weight"] = curve.weights
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
            for component in model.components:
                definition = registry.get(component.function_id)
                component_derived = derived.get(component.id, {})
                for name, parameter in component.parameters.items():
                    path = model.parameter_path(curve.id, component.id, name)
                    estimate = estimates.get(path)
                    value = float(
                        getattr(estimate, "value", parameter_values.get(path, parameter.value))
                    )
                    error = getattr(estimate, "standard_error", parameter.standard_error)
                    ci_low = getattr(estimate, "ci_low", parameter.ci_low)
                    ci_high = getattr(estimate, "ci_high", parameter.ci_high)
                    rows.append(
                        {
                            "series": series.name,
                            "curve": curve.name,
                            "curve_id": curve.id,
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
                            "status": parameter.status,
                            "link": parameter.link or "",
                            "unit": parameter.unit,
                            "human_readable": value_with_error(value, error),
                            "derived_area": component_derived.get("area"),
                            "derived_FWHM": component_derived.get("FWHM"),
                        }
                    )
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
    curves: Iterable[Curve],
    models: Mapping[str, Model],
    path: str | Path,
    *,
    registry: FunctionRegistry | None = None,
    dpi: int = 300,
    width: float = 7.0,
    height: float = 5.0,
    transparent: bool = False,
    include_components: bool = True,
    include_residuals: bool = True,
) -> Path:
    registry = registry or default_registry()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    curves = list(curves)
    parameter_values = _resolved_values(models)
    figure = plt.figure(figsize=(width, height), constrained_layout=True)
    if include_residuals:
        grid = figure.add_gridspec(4, 1)
        axis = figure.add_subplot(grid[:3, 0])
        residual_axis = figure.add_subplot(grid[3, 0], sharex=axis)
    else:
        axis = figure.add_subplot(111)
        residual_axis = None
    for curve in curves:
        valid = np.isfinite(curve.x) & np.isfinite(curve.y)
        line = axis.plot(curve.x[valid], curve.y[valid], color=curve.colour, linewidth=1.0, label=curve.name)[0]
        masked = curve.effective_mask & valid
        if np.any(masked):
            axis.scatter(curve.x[masked], curve.y[masked], color=line.get_color(), alpha=0.25, s=8)
        model = models.get(curve.id)
        if model and model.components:
            total, components = model.evaluate(
                curve.x,
                curve_id=curve.id,
                values=parameter_values,
                registry=registry,
                components=True,
            )
            axis.plot(curve.x[valid], total[valid], color="#D55E00", linewidth=1.8, label=f"{curve.name} fit")
            if include_components:
                for component in model.components:
                    if component.enabled and component.id in components:
                        axis.plot(curve.x[valid], components[component.id][valid], "--", linewidth=0.8, alpha=0.75)
            if residual_axis is not None:
                residual_axis.axhline(0, color="0.4", linewidth=0.7)
                residual_axis.plot(curve.x[valid], (curve.y - total)[valid], color=curve.colour, linewidth=0.8)
    if curves:
        axis.set_xlabel(_label(curves[0].x_label, curves[0].x_unit))
        axis.set_ylabel(_label(curves[0].y_label, curves[0].y_unit))
        if residual_axis is not None:
            residual_axis.set_ylabel("Residual")
            residual_axis.set_xlabel(_label(curves[0].x_label, curves[0].x_unit))
            axis.tick_params(labelbottom=False)
    axis.legend(loc="best", frameon=False)
    figure.savefig(destination, dpi=dpi, transparent=transparent)
    plt.close(figure)
    return destination


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
    sections = [
        f"<h1>{_escape(title or project.name)}</h1>",
        f"<p><strong>CurveMole {__version__}</strong> — generated {_escape(datetime.now(UTC).isoformat())}</p>",
        f"<p>{_escape(notes)}</p>" if notes else "",
        "<h2>Data and models</h2>",
        f"<p>{len(project.curves)} curve(s), {sum(len(model.components) for model in project.models.values())} component(s).</p>",
        "<h2>Fit statistics</h2>",
        pd.DataFrame([statistics]).to_html(index=False, border=0) if statistics else "<p>No fit result.</p>",
        "<h2>Parameters</h2>",
        parameters.to_html(index=False, border=0, float_format=lambda value: f"{value:.12g}"),
        "<h2>Warnings</h2>",
        "<ul>" + "".join(f"<li>{_escape(item)}</li>" for item in warnings) + "</ul>" if warnings else "<p>None.</p>",
    ]
    if full:
        sections.extend(
            [
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
    project: Project,
    path: str | Path,
    *,
    result: FitResult | None = None,
    title: str | None = None,
    registry: FunctionRegistry | None = None,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(destination) as pdf:
        temporary_plot = destination.with_suffix(".plot.tmp.png")
        export_figure(project.curves, project.models, temporary_plot, dpi=180, registry=registry)
        image = plt.imread(temporary_plot)
        figure, axis = plt.subplots(figsize=(8.27, 11.69))
        axis.axis("off")
        axis.text(0.02, 0.98, title or project.name, fontsize=18, weight="bold", va="top")
        axis.text(0.02, 0.94, f"CurveMole {__version__}", fontsize=9, va="top")
        axis.imshow(image, extent=(0.02, 0.98, 0.38, 0.89), aspect="auto")
        stats_text = "\n".join(f"{key}: {value}" for key, value in (result.statistics if result else {}).items())
        axis.text(0.02, 0.34, stats_text or "No fit result.", fontsize=8, va="top", family="monospace")
        pdf.savefig(figure, bbox_inches="tight")
        plt.close(figure)
        temporary_plot.unlink(missing_ok=True)
    return destination


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
) -> ExportSummary:
    selection = selection or BundleExportSelection()
    if not selection.any_selected():
        raise CurveMoleError("Select at least one item to export.")

    root = Path(directory)
    if versioned:
        root = root / datetime.now(UTC).strftime("export-%Y%m%d-%H%M%S")

    registry = _registry_for_project(project)
    planned = _bundle_paths(project, result, selection)
    if not planned:
        raise CurveMoleError("The selected export items have no available data to write.")

    # New exports keep ownership metadata inside the project so the default export
    # can genuinely contain one visible file. Old hidden manifests remain readable
    # for backwards-compatible updates, but are not created for new exports.
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

    root.mkdir(parents=True, exist_ok=True)
    summary = ExportSummary(root)
    before = {relative: _sha256(root / relative) for relative in collisions}
    base = _safe_name(project.name) or "curvemole"

    if selection.fit_results:
        export_dataframe(
            parameter_dataframe(project, result, registry=registry),
            root / "fit_results.csv",
            delimiter=delimiter,
        )

    if selection.wide_tables:
        for curve in project.curves:
            frame = wide_dataframe(
                curve,
                project.models.get(curve.id),
                registry=registry,
                parameter_values=project.resolved_parameter_values(),
            )
            export_dataframe(
                frame,
                root / "data" / f"{_safe_name(curve.name)}_wide.csv",
                delimiter=delimiter,
            )

    if selection.tidy_table:
        export_dataframe(
            tidy_dataframe(project, registry=registry),
            root / "python" / "data_tidy.csv",
            delimiter=delimiter,
        )

    if selection.results_json:
        results_path = root / "python" / "results.json"
        results_path.parent.mkdir(parents=True, exist_ok=True)
        results_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "application_version": __version__,
                    "result": result.to_dict(arrays=False) if result else None,
                },
                indent=2,
                default=_json_default,
            )
            + "\n",
            encoding="utf-8",
        )

    if selection.fitmodel:
        first_model = next(iter(project.models.values()), Model())
        save_fitmodel(
            first_model,
            root / f"{base}.fitmodel",
            custom_functions=project.custom_functions,
        )

    if selection.project_copy:
        save_project(
            project,
            root / f"{base}.fitproj",
            include_uncertainty_samples=include_uncertainty_samples,
            update_project_path=False,
        )

    if selection.main_plot_png:
        export_figure(project.curves, project.models, root / "main_plot.png", registry=registry)

    if selection.main_plot_svg:
        export_figure(
            project.curves,
            project.models,
            root / "figures" / "main_plot.svg",
            registry=registry,
        )

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
            np.savetxt(covariance_path, result.covariance, delimiter=delimiter)
        if result.correlation is not None:
            correlation_path = root / "uncertainty" / "correlation.csv"
            correlation_path.parent.mkdir(parents=True, exist_ok=True)
            np.savetxt(correlation_path, result.correlation, delimiter=delimiter)

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

    if selection.readme:
        (root / "README.txt").write_text(
            "CurveMole selected analysis export\n\n"
            "fit_results.csv contains the fitted functions and their parameters, grouped by data curve.\n"
            "Additional files are present only when explicitly selected in the export dialog.\n",
            encoding="utf-8",
        )

    written = sorted(relative for relative in planned if (root / relative).is_file())
    owned = sorted(previous_owned | set(written))
    for relative in written:
        output_path = root / relative
        if relative in before:
            (summary.unchanged if before[relative] == _sha256(output_path) else summary.updated).append(
                output_path
            )
        else:
            summary.created.append(output_path)

    project.export_config["directory"] = str(root)
    project.export_config["owned_files"] = owned
    project.export_config["selection"] = selection.to_dict()
    return summary


def _bundle_paths(
    project: Project,
    result: FitResult | None,
    selection: BundleExportSelection,
) -> list[str]:
    base = _safe_name(project.name) or "curvemole"
    paths: list[str] = []
    if selection.fit_results:
        paths.append("fit_results.csv")
    if selection.wide_tables:
        paths.extend(
            f"data/{_safe_name(curve.name)}_wide.csv"
            for curve in project.curves
        )
    if selection.tidy_table:
        paths.append("python/data_tidy.csv")
    if selection.results_json:
        paths.append("python/results.json")
    if selection.fitmodel:
        paths.append(f"{base}.fitmodel")
    if selection.project_copy:
        paths.append(f"{base}.fitproj")
    if selection.main_plot_png:
        paths.append("main_plot.png")
    if selection.main_plot_svg:
        paths.append("figures/main_plot.svg")
    if selection.html_summary:
        paths.append("summary_report.html")
    if selection.html_reproducibility:
        paths.append("report/full_reproducibility.html")
    if selection.pdf_summary:
        paths.append("report/summary.pdf")
    if selection.uncertainty and result:
        if result.covariance is not None:
            paths.append("uncertainty/covariance.csv")
        if result.correlation is not None:
            paths.append("uncertainty/correlation.csv")
    if selection.diagnostics and result:
        paths.extend(
            f"diagnostics/{curve_id}_autocorrelation.csv"
            for curve_id in result.curve_outputs
        )
    if selection.readme:
        paths.append("README.txt")
    return paths


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

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(type(value).__name__)
