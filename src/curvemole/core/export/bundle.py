"""The complete, versioned analysis bundle (tables, figures, reports, README, replot script)."""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from curvemole.core.data import CurveState
from curvemole.core.diagnostics import residual_diagnostics
from curvemole.core.errors import CurveMoleError
from curvemole.core.fitting import FitResult
from curvemole.core.notebook import export_notebook
from curvemole.core.project import Project
from curvemole.core.results_store import ResultKey
from curvemole.core.serialization import save_fitmodel, save_project
from curvemole.identifiers import CONCEPT_DOI, CONCEPT_DOI_URL, RRID, RRID_URL
from curvemole.version import __version__

if TYPE_CHECKING:
    import pandas as pd
from curvemole.core.export.common import (
    BundleExportSelection,
    ExportSummary,
    _BundleRollbackError,
    _curve_export_stems,
    _json_default,
    _normalise_owned_path,
    _registry_for_project,
    _safe_name,
    _sha256,
    _spectrum_export_names,
)
from curvemole.core.export.figures import export_figure
from curvemole.core.export.reports import generate_html_report, generate_pdf_report
from curvemole.core.export.tables import (
    _write_labeled_matrix,
    analysis_dataframes,
    export_dataframe,
    export_function_parameters,
    export_parameter_covariances,
    fit_settings_dataframe,
    parameter_dataframe,
    uncertainty_dataframe,
    wide_dataframe,
)


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
    if result is None and isinstance(project.results.get(ResultKey.LAST_FIT), FitResult):
        result = project.results[ResultKey.LAST_FIT]
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
            "Export would overwrite existing files. Update the existing export (CLI: --force) or create a "
            "versioned export (CLI: --versioned): "
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

    root.parent.mkdir(parents=True, exist_ok=True)
    before = {relative: _sha256(root / relative) for relative in collisions}
    summary = ExportSummary(root)
    staging = Path(tempfile.mkdtemp(prefix=".curvemole-bundle-", dir=root.parent))
    preserve_staging = False
    try:
        stage = staging / "files"
        stage.mkdir()
        written, config = _write_bundle_files(
            project, stage, root, result, selection, delimiter, current_view, registry,
            planned, previous_owned, include_uncertainty_samples,
        )
        updated = {relative for relative in written
                   if relative not in before or before[relative] != _sha256(stage / relative)}
        _publish_bundle(stage, root, written, before, updated)
        project.export_config.update(config)
    except _BundleRollbackError:
        preserve_staging = True
        raise
    finally:
        if not preserve_staging:
            shutil.rmtree(staging, ignore_errors=True)
    for relative in written:
        target = root / relative
        if relative not in before:
            summary.created.append(target)
        elif relative in updated:
            summary.updated.append(target)
        else:
            summary.unchanged.append(target)
    return summary


def _publish_bundle(stage, root, written, before, updated):
    """Publish only after staging succeeds, backing up in-place updates for rollback."""
    backup = stage.parent / "previous"
    for relative in written:
        target = root / relative
        parents = [root.joinpath(*Path(relative).parts[:depth]) for depth in range(len(Path(relative).parts) + 1)]
        if any(path.is_symlink() for path in parents):
            raise FileExistsError(f"Export destination changed: {target}")
        if relative in before:
            if not target.is_file() or _sha256(target) != before[relative]:
                raise FileExistsError(f"Export destination changed: {target}")
            if relative in updated:
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
        elif target.exists():
            raise FileExistsError(f"Export destination changed: {target}")
    committed = []
    created_directories = []
    try:
        for relative in sorted(updated, key=lambda path: (path in {"manifest.json", "README.txt"}, path)):
            target = root / relative
            parent = target.parent
            missing = []
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir()
                created_directories.append(directory)
            os.replace(stage / relative, target)
            committed.append(relative)
    except OSError as exc:
        unrecovered = []
        for relative in reversed(committed):
            try:
                if relative in before:
                    os.replace(backup / relative, root / relative)
                else:
                    (root / relative).unlink(missing_ok=True)
            except OSError:
                unrecovered.append(relative)
        for directory in reversed(created_directories):
            with suppress(OSError):  # A concurrent writer may have populated the directory.
                directory.rmdir()
        if unrecovered:
            raise _BundleRollbackError(
                f"The export failed and some files could not be restored. Backups: {backup}. "
                f"Affected files: {', '.join(unrecovered)}."
            ) from exc
        raise


def _write_bundle_files(project, root, destination, result, selection, delimiter, current_view, registry,
                        planned, previous_owned, include_uncertainty_samples):
    import pandas as pd

    base = _safe_name(project.name) or "curvemole"
    stems = _curve_export_stems(project)
    parameter_values = project.resolved_parameter_values()

    if selection.spectra and project.curves:
        from curvemole.core.spectrum_export import export_spectra

        export_spectra(project, root / "spectra", [curve.id for curve in project.curves],
                       registry=registry, overwrite=False)

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
                    "application_version": __version__, "software_rrid": RRID, "software_concept_doi": CONCEPT_DOI,
                    "scope": "Recorded fits; current model evaluations are in observations.csv.",
                    "result": result.to_dict(arrays=False) if result else None,
                    "fit_by_curve": project.results.get(ResultKey.FIT_BY_CURVE, {}),
                    "global_fit_baselines": project.results.get(ResultKey.GLOBAL_FIT_BASELINES, {}),
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

    if selection.uncertainty and (project.results.get(ResultKey.LEGACY_UNCERTAINTY_REPORTS) or
                                  project.results.get(ResultKey.UNCERTAINTY_REPORTS_BY_CURVE)):
        export_dataframe(uncertainty_dataframe(project), root / "uncertainty" / "parameter_assessments.csv",
                         delimiter=delimiter)

    if selection.diagnostics and result:
        for curve_id, output in result.curve_outputs.items():
            curve = next((item for item in project.curves if item.id == curve_id), None)
            indices = output.indices
            if curve is not None and curve.state == CurveState.FITTED and indices.max(initial=-1) < len(curve):
                indices = curve.row_indices[indices]
            standardized = bool(output.statistics.get("standardized_residuals"))
            diagnostics = residual_diagnostics(
                output.weighted_residual if standardized else output.residual,
                indices=indices, x=output.x,
            )
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
            "schema_version": 2, "application_version": __version__, "software_rrid": RRID, "software_concept_doi": CONCEPT_DOI,
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
    config = {**project.export_config, "directory": str(destination), "owned_files": owned,
              "selection": selection.to_dict()}
    if selection.project_copy:
        export_project = copy.copy(project)
        export_project.export_config = config
        save_project(export_project, root / f"{base}.fitproj",
                     include_uncertainty_samples=include_uncertainty_samples,
                     update_project_path=False)
    return written, config


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
    if selection.uncertainty and (project.results.get(ResultKey.LEGACY_UNCERTAINTY_REPORTS) or
                                  project.results.get(ResultKey.UNCERTAINTY_REPORTS_BY_CURVE)):
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
             f"Software RRID: RRID:{RRID} ({RRID_URL})",
             f"Concept DOI (all versions): {CONCEPT_DOI} ({CONCEPT_DOI_URL})",
             f"Spectra: {len(project.curves)}. CSV delimiter: {delimiter!r}; encoding: UTF-8.",
             "", "This folder contains the selected, available outputs of your analysis.",
             "Only files included in this export are listed below.", "",
             "Software citation", "=================",
             "Bibliography: cite the Zenodo DOI of the exact CurveMole version used.",
             f"Methods: Data were analysed with CurveMole version {__version__} (RRID:{RRID}).",
             "The Concept DOI is a general project reference and may resolve to a beta.",
             "Citation guide and BibTeX: https://github.com/SebRoLENS/curvemole/blob/main/docs/citing.md",
             "", "Contents of this export", "======================="]
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

