"""Static validation of declarative workflow contracts without reading input data."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import fields
from numbers import Real
from typing import Any

from curvemole.core.errors import CurveMoleError
from curvemole.core.expressions import SafeExpression
from curvemole.core.fitting import FitMode, FitSettings
from curvemole.core.functions import formula_definition
from curvemole.core.importers import ColumnMapping, ImportConfig
from curvemole.core.workflow_inputs import validate_import_source
from curvemole.core.workflow_selection import SELECTOR_KEYS, validate_curve_selector
from curvemole.core.workflow_steps import validate_preprocessing
from curvemole.version import WORKFLOW_SCHEMA_VERSION

_ROOT_KEYS = {
    "schema_version", "name", "series_name", "imports", "models", "custom_functions",
    "plugins", "preprocess", "fit", "export",
}
_IMPORT_KEYS = {
    "path", "glob", "directory", "pattern", "recursive", "exclude", "sort",
    "allow_empty", "config", "columns", "aliases", "curve_ids", "alias_template",
    "curve_id_template",
}
_COMPONENT_KEYS = {
    "function", "id", "name", "parameters", "metadata", "operator", "enabled",
    "is_background", "constraints",
}
_RULE_KEYS = {
    "minimum", "maximum", "fixed", "link", "link_scope", "link_reference_scopes",
    "link_relation", "link_tolerance", "link_tolerance_mode",
}
_CUSTOM_KEYS = {"identifier", "display_name", "formula", "kind", "defaults", "bounds", "derived"}
_FIT_KEYS = SELECTOR_KEYS | {"mode", "settings", "spectrum_weights", "equal_contribution"}
_EXPORT_KEYS = {"project", "bundle", "project_overwrite", "versioned", "overwrite"}
_SELECTORS = {
    "x", "sigma_x", "sigma_y", "weights", "variance", "inverse_variance",
    "error_y_plus", "error_y_minus",
}
_SETTING_BOOLEANS = {"absolute_sigma", "nm_adaptive", "use_data_errors"}
_SETTING_INTEGERS = {
    "max_nfev", "seed", "workers", "de_maxiter", "de_popsize", "minimize_maxiter",
    "lbfgsb_maxls", "lbfgsb_maxcor",
}
_SETTING_STRINGS = {"solver", "local_method", "loss"}
_BUILTIN_SOLVERS = {
    "local", "trf", "dogbox", "lm", "differential_evolution", "nelder_mead", "powell",
    "lbfgsb",
}


def _mapping(value: Any, prefix: str, allowed: set | frozenset, errors: list[str]):
    if not isinstance(value, Mapping):
        errors.append(f"{prefix} must be a mapping")
        return None
    unknown = value.keys() - allowed
    if unknown:
        errors.append(f"{prefix} has unknown field(s): " + ", ".join(sorted(map(str, unknown))))
    return value


def _string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _number(value: Any, *, finite: bool = True) -> bool:
    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    try:
        return math.isfinite(value) if finite else not math.isnan(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _selector(value: Any) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool) and value >= 0) or _string(value)


def _enum(value: Any, choices: set[str], label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or value not in choices:
        errors.append(f"{label} must be one of " + ", ".join(sorted(choices)))


def _columns(value: Any, prefix: str, errors: list[str], *, nested: bool = False) -> None:
    before = len(errors)
    mapping = _mapping(value, prefix, {f.name for f in fields(ColumnMapping)}, errors)
    if mapping is None:
        return
    for key in _SELECTORS:
        if key in mapping and mapping[key] is not None and not _selector(mapping[key]):
            errors.append(f"{prefix}.{key} must be a column name or a zero-based index")
    for key in ("y", "pairs", "spectra"):
        if key in mapping and not isinstance(mapping[key], list):
            errors.append(f"{prefix}.{key} must be a list")
    if isinstance(mapping.get("y"), list) and any(not _selector(v) for v in mapping["y"]):
        errors.append(f"{prefix}.y must contain column names or zero-based indices")
    if isinstance(mapping.get("pairs"), list):
        for pair in mapping["pairs"]:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2 or not all(_selector(v) for v in pair):
                errors.append(f"{prefix}.pairs must contain two-column pairs")
    if "as_separated_files" in mapping and not isinstance(mapping["as_separated_files"], bool):
        errors.append(f"{prefix}.as_separated_files must be a boolean")
    if "error_confidence_level" in mapping and (
        not _number(mapping["error_confidence_level"]) or not 0 < mapping["error_confidence_level"] < 1
    ):
        errors.append(f"{prefix}.error_confidence_level must be between zero and one")
    spectra = mapping.get("spectra", [])
    if isinstance(spectra, list) and spectra:
        if nested:
            errors.append(f"{prefix}.spectra cannot contain another spectra list")
        if mapping.get("x") is not None or mapping.get("y") or mapping.get("pairs"):
            errors.append(f"{prefix}.spectra cannot be combined with x/y or pairs")
        if any(mapping.get(key) is not None for key in _SELECTORS - {"x"}):
            errors.append(f"{prefix}: put uncertainty selectors inside each spectra mapping")
        if "error_confidence_level" in mapping:
            errors.append(f"{prefix}: put error_confidence_level inside each spectra mapping")
        if not nested:
            for index, item in enumerate(spectra):
                _columns(item, f"{prefix}.spectra[{index}]", errors, nested=True)
    elif not mapping.get("pairs") and (mapping.get("x") is None or not mapping.get("y")):
        errors.append(f"{prefix} requires x and nonempty y, pairs, or spectra")
    if len(errors) == before:
        try:
            _column_object(mapping).validate()
        except (CurveMoleError, TypeError, ValueError) as exc:
            errors.append(f"{prefix}: {exc}")


def _column_object(value: Mapping[str, Any]) -> ColumnMapping:
    specification = dict(value)
    if "spectra" in specification:
        specification["spectra"] = [_column_object(item) for item in specification["spectra"]]
    return ColumnMapping(**specification)


def _imports(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list) or not value:
        errors.append("imports must be a non-empty list")
        return
    for index, item in enumerate(value):
        prefix = f"imports[{index}]"
        item = _mapping(item, prefix, _IMPORT_KEYS, errors)
        if item is None:
            continue
        errors.extend(f"{prefix}: {error}" for error in validate_import_source(item))
        _columns(item.get("columns"), f"{prefix}.columns", errors)
        if "config" in item:
            config = _mapping(item["config"], f"{prefix}.config", {f.name for f in fields(ImportConfig)}, errors)
            if config is not None:
                if "header" in config and config["header"] is not None and not isinstance(config["header"], bool):
                    errors.append(f"{prefix}.config.header must be a boolean or null")
                if "skip_rows" in config and (
                    not isinstance(config["skip_rows"], int) or isinstance(config["skip_rows"], bool)
                    or config["skip_rows"] < 0
                ):
                    errors.append(f"{prefix}.config.skip_rows must be a nonnegative integer")
                for name in ("decimal", "encoding"):
                    if name in config and not _string(config[name]):
                        errors.append(f"{prefix}.config.{name} must be a nonempty string")
                if "delimiter" in config and config["delimiter"] is not None and (
                    not isinstance(config["delimiter"], str) or not config["delimiter"]
                ):
                    errors.append(f"{prefix}.config.delimiter must be a nonempty string or null")
                if "comment_prefixes" in config and (
                    not isinstance(config["comment_prefixes"], (list, tuple))
                    or any(not _string(v) for v in config["comment_prefixes"])
                ):
                    errors.append(f"{prefix}.config.comment_prefixes must contain nonempty strings")
        for name, template in (("aliases", "alias_template"), ("curve_ids", "curve_id_template")):
            if name in item and (
                not isinstance(item[name], list) or any(not _string(v) for v in item[name])
            ):
                errors.append(f"{prefix}.{name} must be a list of nonempty strings")
            if name in item and template in item:
                errors.append(f"{prefix}: choose {name} or {template}, not both")
        if isinstance(item.get("curve_ids"), list):
            for identity in item["curve_ids"]:
                if _string(identity) and any(c.isspace() or c in ".{}" for c in identity):
                    errors.append(f"{prefix}.curve_ids cannot contain dots, braces or whitespace")


def _custom_functions(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("custom_functions must be a list")
        return
    seen = set()
    for index, custom in enumerate(value):
        prefix = f"custom_functions[{index}]"
        before = len(errors)
        custom = _mapping(custom, prefix, _CUSTOM_KEYS, errors)
        if custom is None:
            continue
        for key in ("identifier", "formula"):
            if not _string(custom.get(key)):
                errors.append(f"{prefix}.{key} must be a nonempty string")
        identifier = custom.get("identifier")
        if _string(identifier):
            if identifier in seen:
                errors.append(f"{prefix}: duplicate function identifier {identifier}")
            seen.add(identifier)
        for key in ("display_name", "kind"):
            if key in custom and not _string(custom[key]):
                errors.append(f"{prefix}.{key} must be a nonempty string")
        for key in ("defaults", "bounds", "derived"):
            if key in custom and not isinstance(custom[key], Mapping):
                errors.append(f"{prefix}.{key} must be a mapping")
        if isinstance(custom.get("defaults"), Mapping) and any(
            not _string(k) or not _number(v) for k, v in custom["defaults"].items()
        ):
            errors.append(f"{prefix}.defaults must map names to finite numbers")
        if isinstance(custom.get("bounds"), Mapping):
            for key, pair in custom["bounds"].items():
                if (not _string(key) or not isinstance(pair, (list, tuple)) or len(pair) != 2
                        or not all(_number(v, finite=False) for v in pair) or pair[0] > pair[1]):
                    errors.append(f"{prefix}.bounds must map names to ordered numeric pairs")
        if isinstance(custom.get("derived"), Mapping) and any(
            not _string(k) or not _string(v) for k, v in custom["derived"].items()
        ):
            errors.append(f"{prefix}.derived must map names to formula strings")
        if len(errors) == before:
            try:
                definition = formula_definition(
                    custom["identifier"], custom.get("display_name", custom["identifier"]), custom["formula"],
                    kind=custom.get("kind", "generic"), defaults=custom.get("defaults"),
                    bounds=custom.get("bounds"), derived_formulas=custom.get("derived"),
                )
                parameters = {spec.name for spec in definition.specs()}
                for key in ("defaults", "bounds"):
                    unknown = custom.get(key, {}).keys() - parameters
                    if unknown:
                        errors.append(f"{prefix}.{key} has unknown parameter(s): " + ", ".join(sorted(unknown)))
                if SafeExpression.compile(custom["formula"]).references:
                    errors.append(f"{prefix}.formula cannot reference project parameters")
                for name, formula in custom.get("derived", {}).items():
                    expression = SafeExpression.compile(formula)
                    unknown = set(expression.variables) - parameters
                    if unknown or expression.references:
                        errors.append(f"{prefix}.derived.{name} must use only the function's parameters")
            except (CurveMoleError, TypeError, ValueError) as exc:
                errors.append(f"{prefix}: {exc}")


def _models(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("models must be a list")
        return
    for index, model in enumerate(value):
        prefix = f"models[{index}]"
        model = _mapping(model, prefix, SELECTOR_KEYS | {"name", "components", "operation_order", "composition_mode"}, errors)
        if model is None:
            continue
        errors.extend(f"{prefix}: {e}" for e in validate_curve_selector(model))
        if "name" in model and not _string(model["name"]):
            errors.append(f"{prefix}.name must be a nonempty string")
        if "composition_mode" in model:
            _enum(model["composition_mode"], {"global", "ordered"}, f"{prefix}.composition_mode", errors)
        if "operation_order" in model and (
            not isinstance(model["operation_order"], list) or any(not _string(v) for v in model["operation_order"])
        ):
            errors.append(f"{prefix}.operation_order must be a list of component IDs")
        components = model.get("components", [])
        if not isinstance(components, list):
            errors.append(f"{prefix}.components must be a list")
            continue
        for number, component in enumerate(components):
            label = f"{prefix}.components[{number}]"
            component = _mapping(component, label, _COMPONENT_KEYS, errors)
            if component is None:
                continue
            if not _string(component.get("function")):
                errors.append(f"{label}.function must be a registered function ID")
            for key in ("id", "name"):
                if key in component and not _string(component[key]):
                    errors.append(f"{label}.{key} must be a nonempty string")
            if _string(component.get("id")) and any(c.isspace() or c in ".{}" for c in component["id"]):
                errors.append(f"{label}.id cannot contain dots, braces or whitespace")
            for key in ("enabled", "is_background"):
                if key in component and not isinstance(component[key], bool):
                    errors.append(f"{label}.{key} must be a boolean")
            if "operator" in component:
                _enum(component["operator"], {"add", "subtract", "multiply", "divide", "convolve"}, f"{label}.operator", errors)
            if "metadata" in component and not isinstance(component["metadata"], Mapping):
                errors.append(f"{label}.metadata must be a mapping")
            if "parameters" in component and (
                not isinstance(component["parameters"], Mapping)
                or any(not _string(k) or not _number(v) for k, v in component["parameters"].items())
            ):
                errors.append(f"{label}.parameters must map names to finite numbers")
            constraints = component.get("constraints", {})
            if not isinstance(constraints, Mapping):
                errors.append(f"{label}.constraints must be a mapping")
                continue
            for name, rules in constraints.items():
                location = f"{label}.constraints.{name}"
                if not _string(name):
                    errors.append(f"{label}.constraints keys must be parameter names")
                rules = _mapping(rules, location, _RULE_KEYS, errors)
                if rules is None:
                    continue
                for key in ("minimum", "maximum"):
                    if key in rules and not _number(rules[key], finite=False):
                        errors.append(f"{location}.{key} must be numeric (infinite bounds are allowed)")
                if "fixed" in rules and not isinstance(rules["fixed"], bool):
                    errors.append(f"{location}.fixed must be a boolean")
                if "link" in rules and rules["link"] is not None and not _string(rules["link"]):
                    errors.append(f"{location}.link must be a nonempty expression or null")
                for key, choices in (
                    ("link_scope", {"relative", "absolute"}),
                    ("link_relation", {"equal", "lower", "upper", "similar"}),
                    ("link_tolerance_mode", {"absolute", "percent"}),
                ):
                    if key in rules:
                        _enum(rules[key], choices, f"{location}.{key}", errors)
                if "link_reference_scopes" in rules and (
                    not isinstance(rules["link_reference_scopes"], list)
                    or any(v not in ("relative", "absolute") for v in rules["link_reference_scopes"])
                ):
                    errors.append(f"{location}.link_reference_scopes must contain relative/absolute")
                if "link_tolerance" in rules and (
                    not _number(rules["link_tolerance"]) or rules["link_tolerance"] < 0
                ):
                    errors.append(f"{location}.link_tolerance must be finite and nonnegative")


def _fit(value: Any, errors: list[str]) -> None:
    value = _mapping(value, "fit", _FIT_KEYS, errors)
    if value is None or not value:
        return
    errors.extend(f"fit: {e}" for e in validate_curve_selector(value, default_all=True))
    if "mode" in value:
        _enum(value["mode"], {mode.value for mode in FitMode}, "fit.mode", errors)
    if "equal_contribution" in value and not isinstance(value["equal_contribution"], bool):
        errors.append("fit.equal_contribution must be a boolean")
    if "spectrum_weights" in value and (
        not isinstance(value["spectrum_weights"], Mapping)
        or any(not _string(k) or not _number(v) or v <= 0 for k, v in value["spectrum_weights"].items())
    ):
        errors.append("fit.spectrum_weights must map curve selectors to positive numbers")
    settings = _mapping(value.get("settings", {}), "fit.settings", {f.name for f in fields(FitSettings)}, errors)
    if settings is None:
        return
    before = len(errors)
    for key, item in settings.items():
        if key in _SETTING_BOOLEANS:
            if not isinstance(item, bool) and not (key == "absolute_sigma" and item is None):
                errors.append(f"fit.settings.{key} must be a boolean")
        elif key in _SETTING_INTEGERS:
            if not isinstance(item, int) or isinstance(item, bool):
                errors.append(f"fit.settings.{key} must be an integer")
        elif key in _SETTING_STRINGS:
            if not _string(item):
                errors.append(f"fit.settings.{key} must be a nonempty string")
        elif key == "x_scale":
            if item != "jac" and not _number(item):
                errors.append("fit.settings.x_scale must be jac or a positive number")
        elif key != "nm_initial_simplex" and not _number(item):
            errors.append(f"fit.settings.{key} must be a finite number")
    if before == len(errors):
        try:
            instance = FitSettings(**settings)
            # Validation must not execute plugins or reject a not-yet-loaded plugin solver.
            if instance.solver not in _BUILTIN_SOLVERS:
                instance.solver = "local"
            instance.validate()
        except (CurveMoleError, TypeError, ValueError, OverflowError) as exc:
            errors.append(f"fit.settings: {exc}")


def _requires_batch_schema(value: Mapping[str, Any]) -> bool:
    if "preprocess" in value:
        return True
    for item in value.get("imports", []) if isinstance(value.get("imports"), list) else []:
        if not isinstance(item, Mapping):
            continue
        if item.keys() & {
            "glob", "directory", "pattern", "recursive", "exclude", "sort", "allow_empty",
            "alias_template", "curve_id_template",
        }:
            return True
        columns = item.get("columns", {})
        if isinstance(columns, Mapping) and columns.get("spectra"):
            return True
    for model in value.get("models", []) if isinstance(value.get("models"), list) else []:
        if isinstance(model, Mapping) and model.keys() & {"curves", "match"}:
            return True
    fit = value.get("fit", {})
    if isinstance(fit, Mapping) and (
        fit.keys() & {"curve", "match"} or isinstance(fit.get("curves"), str)
    ):
        return True
    export = value.get("export", {})
    return isinstance(export, Mapping) and "project_overwrite" in export


def validate_workflow_structure(value: Any) -> list[str]:
    """Return static errors; runtime checks still verify files, functions and fits."""
    errors: list[str] = []
    value = _mapping(value, "workflow", _ROOT_KEYS, errors)
    if value is None:
        return errors
    schema = value.get("schema_version")
    if isinstance(schema, bool) or not isinstance(schema, int) or schema not in {1, 2, WORKFLOW_SCHEMA_VERSION}:
        errors.append(f"schema_version must be 1, 2, or {WORKFLOW_SCHEMA_VERSION}")
    elif schema < 3 and _requires_batch_schema(value):
        errors.append("Batch imports, selectors and preprocessing require schema_version: 3")
    for key in ("name", "series_name"):
        if key in value and not _string(value[key]):
            errors.append(f"{key} must be a nonempty string")
    _imports(value.get("imports"), errors)
    if "custom_functions" in value:
        _custom_functions(value["custom_functions"], errors)
    if "plugins" in value and (
        not isinstance(value["plugins"], list) or any(not _string(v) for v in value["plugins"])
    ):
        errors.append("plugins must be a list of manifest paths")
    if "models" in value:
        _models(value["models"], errors)
    if "preprocess" in value:
        errors.extend(validate_preprocessing(value["preprocess"]))
    if "fit" in value:
        _fit(value["fit"], errors)
    if "export" in value:
        export = _mapping(value["export"], "export", _EXPORT_KEYS, errors)
        if export is not None:
            for key in ("project", "bundle"):
                if key in export and not _string(export[key]):
                    errors.append(f"export.{key} must be a nonempty path")
            for key in ("versioned", "overwrite", "project_overwrite"):
                if key in export and not isinstance(export[key], bool):
                    errors.append(f"export.{key} must be a boolean")
    return errors
