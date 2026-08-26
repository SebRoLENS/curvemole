"""Automation-safe command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
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
from curvemole.core.serialization import load_project, save_project, validate_project_archive
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
    parser.add_argument("--json", action="store_true", dest="global_json", help="JSON output")
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("gui", help="Open the desktop application")

    run = subparsers.add_parser("run", help="Run a YAML workflow")
    run.add_argument("workflow", type=Path)
    run.add_argument("--trust-plugin", action="append", default=[])
    run.add_argument("--json", action="store_true", dest="local_json")

    fit = subparsers.add_parser("fit", help="Fit one imported curve")
    _add_fit_arguments(fit)

    fit_series = subparsers.add_parser("fit-series", help="Fit multiple files independently or sequentially")
    _add_fit_arguments(fit_series, multiple=True)
    fit_series.add_argument("--mode", choices=["independent", "sequential", "global"], default="independent")

    export = subparsers.add_parser("export", help="Export a project analysis bundle")
    export.add_argument("project", type=Path)
    export.add_argument("directory", type=Path)
    export.add_argument("--force", action="store_true")
    export.add_argument("--versioned", action="store_true")
    export.add_argument("--json", action="store_true", dest="local_json")

    inspect = subparsers.add_parser("inspect", help="Inspect a project or data file")
    inspect.add_argument("path", type=Path)
    inspect.add_argument("--json", action="store_true", dest="local_json")

    validate = subparsers.add_parser("validate", help="Validate a project, model, or workflow")
    validate.add_argument("path", type=Path)
    validate.add_argument("--json", action="store_true", dest="local_json")

    functions = subparsers.add_parser("functions", help="Inspect the function registry")
    function_sub = functions.add_subparsers(dest="functions_command", required=True)
    function_list = function_sub.add_parser("list", help="List available functions")
    function_list.add_argument("--json", action="store_true", dest="local_json")
    return parser


def _add_fit_arguments(parser: argparse.ArgumentParser, *, multiple: bool = False) -> None:
    parser.add_argument("input", type=Path, nargs="+" if multiple else None)
    parser.add_argument("--x", required=True, help="x column name or zero-based index")
    parser.add_argument("--y", required=True, help="y column name or zero-based index")
    parser.add_argument(
        "--function",
        choices=["gaussian", "lorentzian", "voigt", "pseudo_voigt"],
        default="gaussian",
    )
    parser.add_argument("--center", type=float)
    parser.add_argument("--width", type=float)
    parser.add_argument("--area", type=float)
    parser.add_argument("--background", choices=["none", "constant", "linear"], default="constant")
    parser.add_argument("--loss", choices=["linear", "soft_l1", "huber", "cauchy"], default="linear")
    parser.add_argument("--global-search", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true", dest="local_json")


def main(argv: Sequence[str] | None = None) -> int:
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
    except Exception as exc:
        logging.exception("Unexpected failure")
        _error(exc, json_output)
        return EXIT_UNEXPECTED


def _dispatch(args: argparse.Namespace) -> Any:
    if args.command == "gui":
        from curvemole.gui.app import main as gui_main

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
        elif suffix in {".yml", ".yaml"}:
            failures = validate_workflow(load_workflow(args.path))
        else:
            raise CurveMoleError(f"Validation is unsupported for '{suffix}'.")
        return {"valid": not failures, "failures": failures}
    raise CurveMoleError(f"Unknown command: {args.command}")


def _fit_files(inputs: list[Path], args: argparse.Namespace) -> dict[str, Any]:
    project = Project(name=inputs[0].stem if len(inputs) == 1 else "CurveMole series")
    x_column = _column_value(args.x)
    y_column = _column_value(args.y)
    for input_path in inputs:
        curves = import_file(input_path, ColumnMapping(x=x_column, y=[y_column]))
        for curve in curves:
            project.add_curve(curve)
            model = project.model_for(curve.id)
            suggestions = find_peak_suggestions(curve, sign="positive", max_peaks=1)
            if suggestions:
                component = component_from_suggestion(suggestions[0], args.function)
            else:
                component = Component.create(args.function)
            if args.center is not None:
                component.parameters["center"].value = args.center
            width_name = "sigma" if args.function in {"gaussian", "voigt"} else "gamma" if args.function == "lorentzian" else "fwhm"
            if args.width is not None:
                component.parameters[width_name].value = args.width
            if args.area is not None:
                component.parameters["area"].value = args.area
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
    result = Fitter().fit(plan, {curve.id: curve for curve in project.curves}, project.models)
    project.results["last_fit"] = result
    if args.output:
        if args.output.exists() and not args.force:
            raise CurveMoleError(f"Output exists; use --force to replace: {args.output}")
        save_project(project, args.output)
    return {
        "success": result.success,
        "message": result.message,
        "statistics": result.statistics,
        "parameters": {path: value.to_dict() for path, value in result.parameters.items()},
        "output": str(args.output) if args.output else None,
    }


def _column_value(value: str) -> str | int:
    return int(value) if value.isdigit() else value


def _print(payload: Any, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, default=str))
    elif isinstance(payload, list):
        for item in payload:
            print("\t".join(str(item.get(key, "")) for key in ("identifier", "name", "kind", "parameters")))
    elif isinstance(payload, dict):
        for key, value in payload.items():
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
