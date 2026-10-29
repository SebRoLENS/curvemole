"""Versioned YAML workflows backed by the same public domain objects."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
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
from curvemole.core.workflow_inputs import format_import_name, resolve_import_paths
from curvemole.core.workflow_selection import SELECTOR_KEYS, select_curve_ids
from curvemole.core.workflow_steps import apply_preprocessing
from curvemole.core.workflow_validation import validate_workflow_structure
from curvemole.version import WORKFLOW_SCHEMA_VERSION


@dataclass(slots=True)
class WorkflowOutcome:
    project: Project
    result: FitResult | None
    outputs: list[Path]
    imported_files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_workflow(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CurveMoleError(f"Cannot read workflow '{source}': {exc}") from exc
    if not isinstance(value, dict):
        raise CurveMoleError("Workflow root must be a mapping.")
    schema = value.get("schema_version")
    if isinstance(schema, bool) or not isinstance(schema, int) or schema not in {1, 2, WORKFLOW_SCHEMA_VERSION}:
        raise CurveMoleError(
            f"Unsupported workflow schema {schema}; expected {WORKFLOW_SCHEMA_VERSION}."
        )
    return value


def validate_workflow(value: Mapping[str, Any]) -> list[str]:
    """Check supported fields, nested structures and safe expressions without I/O."""
    return validate_workflow_structure(value)


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
    export_spec = workflow.get("export", {})
    project_output = None
    if "project" in export_spec:
        project_output = _resolve(root, export_spec["project"])
        if project_output.suffix.lower() != ".fitproj":
            project_output = project_output.with_suffix(".fitproj")
        if project_output.exists() and not export_spec.get("project_overwrite", True):
            raise CurveMoleError(f"Project output already exists (project_overwrite is false): {project_output}")

    registry = registry or default_registry()
    custom_specs = []
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
        custom_specs.append({
            "identifier": custom["identifier"],
            "display_name": custom.get("display_name", custom["identifier"]),
            "formula": custom["formula"],
            "kind": custom.get("kind", "generic"),
            "defaults": dict(custom.get("defaults", {})),
            "bounds": dict(custom.get("bounds", {})),
            "derived_formulas": dict(custom.get("derived", {})),
        })
    manager = PluginManager(registry, trusted_identifiers=trust_plugins)
    for plugin_path in workflow.get("plugins", []):
        manifest = _resolve(root, plugin_path)
        candidates = manager.discover_local(manifest.parent)
        candidate = next((item for item in candidates if Path(item.reference) == manifest), None)
        if candidate is None:
            raise CurveMoleError(f"Plugin manifest was not discovered: {manifest}")
        manager.load(candidate, trust=candidate.metadata.identifier in (trust_plugins or set()))

    project = Project(name=str(workflow.get("name", source.stem)))
    project.custom_functions = custom_specs
    imported_series = Series(str(workflow.get("series_name", "Workflow data")))
    curve_aliases: dict[str, str] = {}
    identities: dict[str, str] = {}
    ambiguous: set[str] = set()
    imported_files: list[Path] = []
    warnings: list[str] = []
    for item_index, item in enumerate(workflow["imports"]):
        paths = resolve_import_paths(item, root)
        if not paths:
            warnings.append(f"imports[{item_index}] matched no files; allow_empty is true")
        config = ImportConfig(**item["config"]) if "config" in item else None
        mapping = _column_mapping(item["columns"])
        aliases = item.get("aliases", [])
        saved_ids = item.get("curve_ids", [])
        alias_index = 0
        for file_index, input_path in enumerate(paths, 1):
            try:
                curves = import_file(input_path, mapping, config)
            except CurveMoleError as exc:
                raise type(exc)(f"imports[{item_index}] file '{input_path}': {exc}") from exc
            imported_files.append(input_path)
            for curve_index, curve in enumerate(curves, 1):
                name_arguments = {
                    "file_index": file_index, "curve_index": curve_index, "curve_name": curve.name,
                }
                if "alias_template" in item:
                    curve.name = format_import_name(item["alias_template"], input_path, root, **name_arguments)
                elif alias_index < len(aliases):
                    curve.name = aliases[alias_index]
                if curve.name in curve_aliases:
                    ambiguous.add(curve.name)
                curve_aliases[curve.name] = curve.id

                identity = None
                if "curve_id_template" in item:
                    identity = format_import_name(item["curve_id_template"], input_path, root, **name_arguments)
                elif alias_index < len(saved_ids):
                    identity = saved_ids[alias_index]
                if identity is not None:
                    if any(character.isspace() or character in ".{}" for character in identity):
                        raise CurveMoleError(
                            f"Workflow curve identity '{identity}' contains a dot, brace or whitespace. "
                            "Use a curve_id_template such as batch_{file_index}_{curve_index}."
                        )
                    if identity in identities:
                        raise CurveMoleError(f"Duplicate workflow curve identity: {identity}")
                    identities[identity] = curve.id
                imported_series.add(curve)
                alias_index += 1
    project.add_series(imported_series)
    for alias in ambiguous:
        curve_aliases.pop(alias, None)
    curve_aliases.update(identities)

    apply_preprocessing(project, workflow.get("preprocess", []), curve_aliases)
    _apply_models(project, workflow.get("models", []), curve_aliases, identities, registry)
    project.resolved_parameter_values()

    result: FitResult | None = None
    fit_spec = workflow.get("fit")
    if fit_spec:
        selected = select_curve_ids(project, curve_aliases, default_all=True, **_selectors(fit_spec))
        settings = FitSettings(**fit_spec.get("settings", {}))
        plan = FitPlan(
            selected,
            FitMode(fit_spec.get("mode", "independent")),
            settings,
            {
                _curve_id(key, curve_aliases, project): float(value)
                for key, value in fit_spec.get("spectrum_weights", {}).items()
            },
            fit_spec.get("equal_contribution", False),
        )
        result = Fitter(registry).fit(plan, {curve.id: curve for curve in project.curves}, project.models)
        project.results["last_fit"] = result
        project.snapshot("Workflow fit", {"plan": _plan_dict(plan), "result": result.to_dict()})

    outputs: list[Path] = []
    if project_output is not None:
        outputs.append(save_project(project, project_output))
    if "bundle" in export_spec:
        summary = export_bundle(
            project,
            _resolve(root, export_spec["bundle"]),
            result=result,
            versioned=export_spec.get("versioned", False),
            overwrite=export_spec.get("overwrite", False),
        )
        outputs.extend(summary.created + summary.updated)
    return WorkflowOutcome(project, result, outputs, imported_files, warnings)


def _selectors(specification: Mapping[str, Any]) -> dict[str, Any]:
    return {key: specification[key] for key in SELECTOR_KEYS if key in specification}


def _column_mapping(specification: Mapping[str, Any]) -> ColumnMapping:
    value = dict(specification)
    if "spectra" in value:
        value["spectra"] = [_column_mapping(item) for item in value["spectra"]]
    mapping = ColumnMapping(**value)
    mapping.validate()
    return mapping


def _apply_models(
    project: Project,
    specifications: list[Mapping[str, Any]],
    aliases: Mapping[str, str],
    identities: Mapping[str, str],
    registry: FunctionRegistry,
) -> None:
    for model_index, model_spec in enumerate(specifications):
        targets = select_curve_ids(project, aliases, **_selectors(model_spec))
        for curve_id in targets:
            model = project.model_for(curve_id)
            model.name = model_spec.get("name", model.name)
            for component_spec in model_spec.get("components", []):
                component = Component.create(
                    component_spec["function"],
                    registry=registry,
                    name=component_spec.get("name"),
                    initial=component_spec.get("parameters"),
                    metadata=component_spec.get("metadata"),
                    operator=component_spec.get("operator", "add"),
                )
                unknown = set(component_spec.get("parameters", {})) - component.parameters.keys()
                unknown |= set(component_spec.get("constraints", {})) - component.parameters.keys()
                if unknown:
                    raise CurveMoleError(
                        f"models[{model_index}] function '{component.function_id}' has unknown parameter(s): "
                        + ", ".join(sorted(unknown))
                        + ". Available: " + ", ".join(component.parameters)
                    )
                component.id = component_spec.get("id", component.id)
                component.enabled = component_spec.get("enabled", True)
                component.is_background = component_spec.get("is_background", False)
                for name, rules in component_spec.get("constraints", {}).items():
                    parameter = component.parameters[name]
                    if "minimum" in rules:
                        parameter.minimum = float(rules["minimum"])
                    if "maximum" in rules:
                        parameter.maximum = float(rules["maximum"])
                    parameter.fixed = rules.get("fixed", False)
                    link = rules.get("link")
                    parameter.link = re.sub(
                        r"\$\{([^{}]+)\}",
                        lambda match: "$" + "{" + _remap_reference(match[1], identities) + "}",
                        link,
                    ) if link else None
                    parameter.link_scope = rules.get("link_scope", "relative")
                    parameter.link_reference_scopes = list(rules.get("link_reference_scopes", []))
                    parameter.link_relation = rules.get("link_relation", "equal")
                    parameter.link_tolerance = float(rules.get("link_tolerance", 0.0))
                    parameter.link_tolerance_mode = rules.get("link_tolerance_mode", "absolute")
                    parameter.validate()
                model.add(component)
            if "operation_order" in model_spec:
                order = list(model_spec["operation_order"])
                unknown = set(order) - {component.id for component in model.components}
                if unknown or len(order) != len(set(order)):
                    raise CurveMoleError(f"models[{model_index}] has unknown or duplicate operation_order IDs")
                model.operation_order = order
            model.validate_composition()


def dump_workflow(project: Project, path: str | Path) -> Path:
    destination = Path(path)
    value: dict[str, Any] = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "name": project.name,
        "imports": [],
        "models": [],
    }
    if project.custom_functions:
        value["custom_functions"] = [
            {
                "identifier": spec["identifier"],
                "display_name": spec.get("display_name", spec["identifier"]),
                "formula": spec["formula"],
                "kind": spec.get("kind", "generic"),
                "defaults": spec.get("defaults", {}),
                "bounds": spec.get("bounds", {}),
                "derived": spec.get("derived_formulas", spec.get("derived", {})),
            }
            for spec in project.custom_functions
        ]
    for curve in project.curves:
        value["imports"].append(
            {
                "path": curve.source or f"data/{curve.name}.csv",
                **_import_spec(curve),
                "aliases": [curve.name],
                "curve_ids": [curve.id],
            }
        )
        model = project.models.get(curve.id)
        if model:
            value["models"].append(
                {
                    "curve": curve.id,
                    "composition_mode": model.composition_mode,
                    "operation_order": list(model.operation_order),
                    "components": [
                        {
                            "function": component.function_id,
                            "id": component.id,
                            "name": component.name,
                            "enabled": component.enabled,
                            "is_background": component.is_background,
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
                                    "link_scope": parameter.link_scope,
                                    "link_reference_scopes": list(parameter.link_reference_scopes),
                                    "link_relation": parameter.link_relation,
                                    "link_tolerance": parameter.link_tolerance,
                                    "link_tolerance_mode": parameter.link_tolerance_mode,
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


def _import_spec(curve) -> dict[str, Any]:
    imported = curve.metadata.get("import", {})
    if "config" in imported and "columns" in imported:
        return {"config": imported["config"], "columns": imported["columns"]}
    if "x_column" in imported:
        config = {key: imported[key] for key in ("decimal", "header", "skip_rows") if key in imported}
        config["delimiter"] = None if imported.get("delimiter") == "whitespace" else imported.get("delimiter")
        columns = {"x": imported["x_column"], "y": [imported["y_column"]]}
        for key in ("sigma_x", "sigma_y", "weights", "variance", "inverse_variance", "error_y_plus", "error_y_minus"):
            columns[key] = imported.get(key + "_column")
        columns["error_confidence_level"] = imported.get("error_confidence_level", 0.95)
        return {"config": config, "columns": columns}
    return {"columns": {"x": 0, "y": [1]}}


def _remap_reference(reference: str, identities: Mapping[str, str]) -> str:
    curve, separator, remainder = reference.strip().partition(".")
    return identities.get(curve, curve) + separator + remainder


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def _curve_id(value: str, aliases: Mapping[str, str], project: Project) -> str:
    return select_curve_ids(project, aliases, curve=value)[0]


def _plan_dict(plan: FitPlan) -> dict[str, Any]:
    return {
        "curve_ids": plan.curve_ids,
        "mode": plan.mode.value,
        "settings": asdict(plan.settings),
        "spectrum_weights": plan.spectrum_weights,
        "equal_contribution": plan.equal_contribution,
    }
