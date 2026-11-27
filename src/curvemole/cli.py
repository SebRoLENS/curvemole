"""Automation-safe command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from curvemole.core.errors import CurveMoleError, DataValidationError, FitError, ProjectFormatError
from curvemole.core.export import export_bundle
from curvemole.core.fitting import FitMode, FitPlan, FitSettings, Fitter
from curvemole.core.importers import ColumnMapping, import_file, inspect_file
from curvemole.core.initialization import component_from_suggestion, find_peak_suggestions
from curvemole.core.models import Component
from curvemole.core.project import Project
from curvemole.core.registry import default_registry
from curvemole.core.serialization import (
    load_fitmodel,
    load_project,
    save_project,
    validate_project_archive,
)
from curvemole.core.workflow import load_workflow, run_workflow, validate_workflow
from curvemole.version import __version__

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DATA = 3
EXIT_FIT = 4
EXIT_PROJECT = 5
EXIT_PLUGIN = 6
EXIT_UNEXPECTED = 10


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="curvemole", description="CurveMole — Modular Scientific Curve Fitting"
    )
    parser.add_argument("--version", action="version", version=f"CurveMole {__version__}")
    parser.add_argument("--json", action="store_true", dest="global_json",
                        help="write machine-readable JSON to stdout (also accepted after the command)")
    parser.add_argument("--verbose", action="store_true",
                        help="log debugging details, including tracebacks of unexpected failures")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("gui", help="Open the desktop application")

    run = subparsers.add_parser("run", help="Run a YAML workflow")
    run.add_argument("workflow", type=Path, help="YAML workflow file")
    run.add_argument("--trust-plugin", action="append", default=[], metavar="PLUGIN",
                     help="trust a plugin required by the workflow (repeatable)")
    run.add_argument("--json", action="store_true", dest="local_json", help=argparse.SUPPRESS)

    fit = subparsers.add_parser("fit", help="Fit one imported curve")
    _add_fit_arguments(fit)

    fit_series = subparsers.add_parser("fit-series", help="Fit multiple files independently or sequentially")
    _add_fit_arguments(fit_series, multiple=True)
    fit_series.add_argument("--mode", choices=["independent", "sequential", "global"], default="independent")

    export = subparsers.add_parser("export", help="Export a project analysis bundle")
    export.add_argument("project", type=Path, help="project file (.fitproj)")
    export.add_argument("directory", type=Path, help="output directory")
    export.add_argument("--force", action="store_true", help="update files in an existing export directory")
    export.add_argument("--versioned", action="store_true",
                        help="write a new numbered export next to an existing one")
    export.add_argument("--json", action="store_true", dest="local_json", help=argparse.SUPPRESS)

    inspect = subparsers.add_parser("inspect", help="Inspect a project or data file")
    inspect.add_argument("path", type=Path, help="project (.fitproj) or data file")
    inspect.add_argument("--json", action="store_true", dest="local_json", help=argparse.SUPPRESS)

    validate = subparsers.add_parser("validate", help="Validate a project, model, or workflow")
    validate.add_argument("path", type=Path, help="project (.fitproj), model (.fitmodel) or workflow (.yml)")
    validate.add_argument("--json", action="store_true", dest="local_json", help=argparse.SUPPRESS)

    functions = subparsers.add_parser("functions", help="Inspect the function registry")
    function_sub = functions.add_subparsers(dest="functions_command", required=True)
    function_list = function_sub.add_parser("list", help="List available functions")
    function_list.add_argument("--json", action="store_true", dest="local_json", help=argparse.SUPPRESS)
    return parser


def _add_fit_arguments(parser: argparse.ArgumentParser, *, multiple: bool = False) -> None:
    parser.add_argument("input", type=Path, nargs="+" if multiple else None,
                        help="data files" if multiple else "data file")
    parser.add_argument("--x", required=True, help="x column name or zero-based index")
    parser.add_argument("--y", required=True, help="y column name or zero-based index")
    parser.add_argument(
        "--function",
        choices=["gaussian", "lorentzian", "voigt", "pseudo_voigt"],
        default="gaussian",
        help="peak function (default: gaussian)",
    )
    parser.add_argument("--peaks", type=int, default=1, metavar="N",
                        help="number of peaks, initialised from the N most prominent suggestions (default: 1)")
    parser.add_argument("--center", type=float, help="initial centre of the first peak")
    parser.add_argument("--width", type=float, help="initial width (sigma, gamma or FWHM) of the first peak")
    parser.add_argument("--area", type=float, help="initial area of the first peak")
    parser.add_argument("--background", choices=["none", "constant", "linear"], default="constant",
                        help="background function (default: constant)")
    parser.add_argument("--sigma-y", metavar="COLUMN",
                        help="column of Y standard uncertainties used as fit weights")
    parser.add_argument("--loss", choices=["linear", "soft_l1", "huber", "cauchy"], default="linear",
                        help="residual loss (default: linear least squares)")
    parser.add_argument("--global-search", action="store_true",
                        help="use bounded differential evolution before local refinement")
    parser.add_argument("--output", type=Path, help="save the fitted project to this .fitproj file")
    parser.add_argument("--force", action="store_true", help="replace an existing --output file")
    parser.add_argument("--json", action="store_true", dest="local_json", help=argparse.SUPPRESS)


def main(argv: Sequence[str] | None = None) -> int:
    import multiprocessing
    multiprocessing.freeze_support()
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    json_output = bool(getattr(args, "global_json", False) or getattr(args, "local_json", False))
    try:
        payload = _dispatch(args)
        _print(payload, json_output)
        if args.command == "validate" and not payload["valid"]:
            return EXIT_PROJECT if args.path.suffix.lower() in {".fitproj", ".fitmodel"} else EXIT_DATA
        if isinstance(payload, dict) and payload.get("success") is False:
            return EXIT_FIT  # e.g. a paused sequential fit or a failed optimisation
        return EXIT_OK
    except ProjectFormatError as exc:
        _error(exc, json_output)
        return EXIT_PROJECT
    except FitError as exc:
        _error(exc, json_output)
        return EXIT_FIT
    except DataValidationError as exc:
        _error(exc, json_output)
        return EXIT_DATA
    except CurveMoleError as exc:
        _error(exc, json_output)
        return EXIT_PLUGIN
    except FileExistsError as exc:
        _error(exc, json_output)
        return EXIT_USAGE
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError, PermissionError) as exc:
        _error(exc, json_output)
        return EXIT_DATA
    except Exception as exc:
        logging.debug("Unexpected failure", exc_info=True)
        _error(exc, json_output)
        if not args.verbose:
            print("Run again with --verbose for the full traceback.", file=sys.stderr)
        return EXIT_UNEXPECTED


def _dispatch(args: argparse.Namespace) -> Any:
    if args.command == "gui":
        from curvemole.desktop import main as gui_main

        return {"exit_code": gui_main([])}
    if args.command == "functions":
        return [
            {
                "identifier": definition.identifier,
                "name": definition.display_name,
                "kind": definition.kind,
                "parameters": [spec.name for spec in definition.specs(_default_metadata(definition.identifier))],
            }
            for definition in default_registry().values()
        ]
    if args.command == "run":
        outcome = run_workflow(args.workflow, trust_plugins=set(args.trust_plugin))
        return {
            "project": outcome.project.name,
            "success": outcome.result.success if outcome.result else None,
            "statistics": outcome.result.statistics if outcome.result else None,
            "outputs": [str(path) for path in outcome.outputs],
            "imported_files": [str(path) for path in outcome.imported_files],
            "warnings": outcome.warnings,
        }
    if args.command in {"fit", "fit-series"}:
        inputs = args.input if isinstance(args.input, list) else [args.input]
        return _fit_files(inputs, args)
    if args.command == "export":
        project = load_project(args.project)
        summary = export_bundle(
            project,
            args.directory,
            overwrite=args.force,
            versioned=args.versioned,
        )
        return {
            "directory": str(summary.directory),
            "created": len(summary.created),
            "updated": len(summary.updated),
            "unchanged": len(summary.unchanged),
        }
    if args.command == "inspect":
        if args.path.suffix.lower() == ".fitproj":
            project = load_project(args.path, partial_recovery=True)
            return {
                "format": "fitproj",
                "name": project.name,
                "series": len(project.dataset.series),
                "curves": len(project.curves),
                "models": len(project.models),
                "read_only": project.read_only,
            }
        inspection = inspect_file(args.path)
        return {
            "format": "data",
            "columns": inspection.columns,
            "config": {
                "delimiter": inspection.config.delimiter,
                "decimal": inspection.config.decimal,
                "header": inspection.config.header,
            },
            "preview": inspection.preview.to_dict(orient="records"),
        }
    if args.command == "validate":
        suffix = args.path.suffix.lower()
        if suffix == ".fitproj":
            failures = validate_project_archive(args.path, raise_on_error=False)
        elif suffix == ".fitmodel":
            failures = []
            try:
                load_fitmodel(args.path)
            except ProjectFormatError as exc:
                failures.append(str(exc))
        elif suffix in {".yml", ".yaml"}:
            failures = validate_workflow(load_workflow(args.path))
        else:
            raise CurveMoleError(f"Validation is unsupported for '{suffix}'.")
        return {"valid": not failures, "failures": failures}
    raise CurveMoleError(f"Unknown command: {args.command}")


def _fit_files(inputs: list[Path], args: argparse.Namespace) -> dict[str, Any]:
    if args.peaks < 1:
        raise DataValidationError("--peaks must be at least 1.")
    project = Project(name=inputs[0].stem if len(inputs) == 1 else "CurveMole series")
    x_column = _column_value(args.x)
    y_column = _column_value(args.y)
    sigma_column = None if args.sigma_y is None else _column_value(args.sigma_y)
    warnings: list[str] = []
    width_name = ("sigma" if args.function in {"gaussian", "voigt"}
                  else "gamma" if args.function == "lorentzian" else "fwhm")
    for input_path in inputs:
        curves = import_file(input_path, ColumnMapping(x=x_column, y=[y_column], sigma_y=sigma_column))
        for curve in curves:
            project.add_curve(curve)
            model = project.model_for(curve.id)
            suggestions = find_peak_suggestions(curve, sign="positive")
            if len(suggestions) > args.peaks:
                warnings.append(
                    f"{curve.name}: {len(suggestions)} peak candidates found but only {args.peaks} "
                    "fitted; use --peaks to fit more.")
            components = [component_from_suggestion(suggestion, args.function)
                          for suggestion in suggestions[:args.peaks]]
            components += [Component.create(args.function) for _ in range(args.peaks - len(components))]
            first = components[0]
            if args.center is not None:
                first.parameters["center"].value = args.center
            if args.width is not None:
                first.parameters[width_name].value = args.width
            if args.area is not None:
                first.parameters["area"].value = args.area
            for component in components:
                model.add(component)
            if args.background != "none":
                background = Component.create(args.background)
                if args.background == "constant":
                    background.parameters["offset"].value = float(curve.y[~curve.effective_mask].min())
                model.add(background, 0)
    settings = FitSettings(
        solver="differential_evolution" if args.global_search else "local",
        loss=args.loss,
    )
    mode = FitMode(getattr(args, "mode", "independent"))
    plan = FitPlan([curve.id for curve in project.curves], mode, settings)
    if args.output and args.output.exists() and not args.force:
        raise FileExistsError(f"Output exists; use --force to replace: {args.output}")
    result = Fitter().fit(plan, {curve.id: curve for curve in project.curves}, project.models)
    project.results["last_fit"] = result
    if args.output:
        save_project(project, args.output)
    labels = _parameter_labels(project)
    return {
        "success": result.success,
        "message": result.message,
        "statistics": result.statistics,
        "parameters": {path: {**value.to_dict(), "label": labels.get(path, path)}
                       for path, value in result.parameters.items()},
        "warnings": [*warnings, *result.warnings],
        "output": str(args.output) if args.output else None,
    }


def _parameter_labels(project: Project) -> dict[str, str]:
    """Readable "spectrum / function / parameter" names for internal paths."""
    labels = {}
    for curve in project.curves:
        model = project.models.get(curve.id)
        if model is None:
            continue
        for component in model.components:
            for name in component.parameters:
                path = model.parameter_path(curve.id, component.id, name)
                labels[path] = f"{curve.name} / {component.name} / {name}"
    return labels


def _column_value(value: str) -> str | int:
    return int(value) if value.isdigit() else value


def _json_safe(value: Any) -> Any:
    """Standard JSON has no Infinity/NaN: write them as null."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item") and callable(value.item) and getattr(value, "shape", None) == ():
        return _json_safe(value.item())
    return value


def _number(value: Any) -> str:
    return "—" if value is None else f"{value:.8g}" if isinstance(value, float) else str(value)


def _print(payload: Any, json_output: bool) -> None:
    if json_output:
        print(json.dumps(_json_safe(payload), indent=2, default=str, allow_nan=False))
    elif isinstance(payload, list):
        for item in payload:
            print("\t".join(str(item.get(key, "")) for key in ("identifier", "name", "kind", "parameters")))
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if key == "parameters" and isinstance(value, dict):
                print("parameters:")
                for path, estimate in value.items():
                    label = estimate.get("label", path) if isinstance(estimate, dict) else path
                    if isinstance(estimate, dict):
                        error = estimate.get("standard_error")
                        text = _number(estimate.get("value"))
                        if error is not None:
                            text += f" ± {_number(error)}"
                        if estimate.get("fixed"):
                            text += " (fixed)"
                    else:
                        text = str(estimate)
                    print(f"  {label}: {text}")
            elif key == "statistics" and isinstance(value, dict):
                print("statistics:")
                for name, statistic in value.items():
                    print(f"  {name}: {_number(statistic)}")
            elif key == "warnings" and isinstance(value, list):
                for warning in value:
                    print(f"warning: {warning}")
            else:
                print(f"{key}: {value}")
    else:
        print(payload)


def _error(error: Exception, json_output: bool) -> None:
    if json_output:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}), file=sys.stderr)
    else:
        print(f"Error: {error}", file=sys.stderr)


def _default_metadata(identifier: str) -> dict[str, Any]:
    if identifier == "polynomial":
        return {"order": 2}
    if identifier == "cubic_spline":
        return {"x_nodes": [0.0, 1.0, 2.0]}
    return {}
