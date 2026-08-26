"""Versioned YAML workflows backed by the same public domain objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from curvemole.core.data import Series
from curvemole.core.errors import CurveMoleError
from curvemole.core.export import export_bundle
from curvemole.core.fitting import FitMode, FitPlan, FitResult, FitSettings, Fitter
from curvemole.core.functions import formula_definition
from curvemole.core.importers import ColumnMapping, ImportConfig, import_file
from curvemole.core.models import Component
from curvemole.core.plugins import PluginManager
from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry, default_registry
from curvemole.core.serialization import save_project
from curvemole.version import WORKFLOW_SCHEMA_VERSION


@dataclass(slots=True)
class WorkflowOutcome:
    project: Project
    result: FitResult | None
    outputs: list[Path]


def load_workflow(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CurveMoleError(f"Cannot read workflow '{source}': {exc}") from exc
    if not isinstance(value, dict):
        raise CurveMoleError("Workflow root must be a mapping.")
    schema = int(value.get("schema_version", -1))
    if schema != WORKFLOW_SCHEMA_VERSION:
        raise CurveMoleError(
            f"Unsupported workflow schema {schema}; expected {WORKFLOW_SCHEMA_VERSION}."
        )
    return value


def validate_workflow(value: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if value.get("schema_version") != WORKFLOW_SCHEMA_VERSION:
        errors.append(f"schema_version must be {WORKFLOW_SCHEMA_VERSION}")
    if not isinstance(value.get("imports"), list) or not value.get("imports"):
        errors.append("imports must be a non-empty list")
    if "models" in value and not isinstance(value["models"], list):
        errors.append("models must be a list")
    if "fit" in value and not isinstance(value["fit"], dict):
        errors.append("fit must be a mapping")
    return errors


def run_workflow(
    path: str | Path,
    *,
    trust_plugins: set[str] | None = None,
    registry: FunctionRegistry | None = None,
) -> WorkflowOutcome:
    source = Path(path).resolve()
    workflow = load_workflow(source)
    errors = validate_workflow(workflow)
    if errors:
        raise CurveMoleError("Invalid workflow: " + "; ".join(errors))
    root = source.parent
    registry = registry or default_registry()
    for custom in workflow.get("custom_functions", []):
        definition = formula_definition(
            custom["identifier"],
            custom.get("display_name", custom["identifier"]),
            custom["formula"],
            kind=custom.get("kind", "generic"),
            defaults=custom.get("defaults"),
            bounds={key: tuple(value) for key, value in custom.get("bounds", {}).items()},
            derived_formulas=custom.get("derived", {}),
        )
        registry.register(definition, replace=True)
    manager = PluginManager(registry, trusted_identifiers=trust_plugins)
    for plugin_path in workflow.get("plugins", []):
        manifest = _resolve(root, plugin_path)
        candidates = manager.discover_local(manifest.parent)
        candidate = next((item for item in candidates if Path(item.reference) == manifest), None)
        if candidate is None:
            raise CurveMoleError(f"Plugin manifest was not discovered: {manifest}")
        manager.load(candidate, trust=candidate.metadata.identifier in (trust_plugins or set()))

    project = Project(name=str(workflow.get("name", source.stem)))
    imported_series = Series(str(workflow.get("series_name", "Workflow data")))
    curve_aliases: dict[str, str] = {}
    for item in workflow["imports"]:
        input_path = _resolve(root, item["path"])
        config = ImportConfig(**item.get("config", {}))
        mapping = ColumnMapping(**item["columns"])
        curves = import_file(input_path, mapping, config)
        aliases = item.get("aliases", [])
        for index, curve in enumerate(curves):
            if index < len(aliases):
                curve.name = str(aliases[index])
            curve_aliases[curve.name] = curve.id
            imported_series.add(curve)
    project.add_series(imported_series)

    for model_spec in workflow.get("models", []):
        curve_id = _curve_id(model_spec["curve"], curve_aliases, project)
        model = project.model_for(curve_id)
        model.name = str(model_spec.get("name", model.name))
        for component_spec in model_spec.get("components", []):
            component = Component.create(
                component_spec["function"],
                registry=registry,
                name=component_spec.get("name"),
                initial=component_spec.get("parameters"),
                metadata=component_spec.get("metadata"),
                operator=component_spec.get("operator", "add"),
            )
            for name, rules in component_spec.get("constraints", {}).items():
                parameter = component.parameters[name]
                if "minimum" in rules:
                    parameter.minimum = float(rules["minimum"])
                if "maximum" in rules:
                    parameter.maximum = float(rules["maximum"])
                parameter.fixed = bool(rules.get("fixed", False))
                parameter.link = rules.get("link")
                parameter.validate()
            model.add(component)

    result: FitResult | None = None
    fit_spec = workflow.get("fit")
    if fit_spec:
        selected = [
            _curve_id(value, curve_aliases, project)
            for value in fit_spec.get("curves", [curve.id for curve in project.curves])
        ]
        settings = FitSettings(**fit_spec.get("settings", {}))
        plan = FitPlan(
            selected,
            FitMode(fit_spec.get("mode", "independent")),
            settings,
            {
                _curve_id(key, curve_aliases, project): float(value)
                for key, value in fit_spec.get("spectrum_weights", {}).items()
            },
            bool(fit_spec.get("equal_contribution", False)),
        )
        result = Fitter(registry).fit(plan, {curve.id: curve for curve in project.curves}, project.models)
        project.results["last_fit"] = result
        project.snapshot("Workflow fit", {"plan": _plan_dict(plan), "result": result.to_dict()})

    outputs: list[Path] = []
    export_spec = workflow.get("export", {})
    if "project" in export_spec:
        outputs.append(
            save_project(project, _resolve(root, export_spec["project"]))
        )
    if "bundle" in export_spec:
        summary = export_bundle(
            project,
            _resolve(root, export_spec["bundle"]),
            result=result,
            versioned=bool(export_spec.get("versioned", False)),
            overwrite=bool(export_spec.get("overwrite", False)),
        )
        outputs.extend(summary.created + summary.updated)
    return WorkflowOutcome(project, result, outputs)


def dump_workflow(project: Project, path: str | Path) -> Path:
    destination = Path(path)
    value: dict[str, Any] = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "name": project.name,
        "imports": [],
        "models": [],
    }
    for curve in project.curves:
        value["imports"].append(
            {
                "path": curve.source or f"data/{curve.name}.csv",
                "columns": {"x": 0, "y": [1]},
                "aliases": [curve.name],
            }
        )
        model = project.models.get(curve.id)
        if model:
            value["models"].append(
                {
                    "curve": curve.name,
                    "components": [
                        {
                            "function": component.function_id,
                            "name": component.name,
                            "operator": component.operator,
                            "metadata": component.metadata,
                            "parameters": {
                                name: parameter.value for name, parameter in component.parameters.items()
                            },
                            "constraints": {
                                name: {
                                    "minimum": parameter.minimum,
                                    "maximum": parameter.maximum,
                                    "fixed": parameter.fixed,
                                    "link": parameter.link,
                                }
                                for name, parameter in component.parameters.items()
                            },
                        }
                        for component in model.components
                    ],
                }
            )
    destination.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return destination


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def _curve_id(value: str, aliases: Mapping[str, str], project: Project) -> str:
    if value in aliases:
        return aliases[value]
    if any(curve.id == value for curve in project.curves):
        return value
    raise CurveMoleError(f"Workflow references unknown curve '{value}'.")


def _plan_dict(plan: FitPlan) -> dict[str, Any]:
    return {
        "curve_ids": plan.curve_ids,
        "mode": plan.mode.value,
        "settings": asdict(plan.settings),
        "spectrum_weights": plan.spectrum_weights,
        "equal_contribution": plan.equal_contribution,
    }
