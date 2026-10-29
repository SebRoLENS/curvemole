"""Static workflow validation rejects mistakes before any data/plugin I/O."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from curvemole.core.workflow import validate_workflow


def _workflow(schema=3):
    return {
        "schema_version": schema,
        "imports": [{"path": "missing.csv", "columns": {"x": 0, "y": [1]}}],
    }


@pytest.mark.parametrize("schema", [1, 2, 3])
def test_literal_legacy_and_current_schemas_remain_valid(schema):
    assert validate_workflow(_workflow(schema)) == []


@pytest.mark.parametrize("schema", [None, True, False, 1.0, "3", [], {}, 0, -1, 4])
def test_invalid_schema_types_and_versions_return_actionable_errors(schema):
    errors = validate_workflow(_workflow(schema))
    assert errors and any("schema_version" in error for error in errors)


@pytest.mark.parametrize("new_fields", [
    {"preprocess": [{"clear_masks": True}]},
    {"imports": [{"directory": "spectra", "columns": {"x": 0, "y": [1]}}]},
    {"imports": [{"glob": "spectra/*.csv", "columns": {"x": 0, "y": [1]}}]},
    {"models": [{"curves": "all", "components": [{"function": "constant"}]}]},
    {"fit": {"curves": "all"}},
    {"export": {"project": "result.fitproj", "project_overwrite": False}},
])
def test_batch_features_require_the_explicit_schema_three_opt_in(new_fields):
    errors = validate_workflow(_workflow(2) | new_fields)
    assert any("schema_version: 3" in error for error in errors)
    assert validate_workflow(_workflow(3) | new_fields) == []


@pytest.mark.parametrize("location, bad_field", [
    ("workflow", "improts"),
    ("import", "recusrive"),
    ("config", "skip_row"),
    ("columns", "sigma"),
    ("model", "component"),
    ("component", "initial"),
    ("constraint", "minumum"),
    ("fit", "worker"),
    ("settings", "max_eval"),
    ("export", "overwite"),
    ("custom", "derived_formulas"),
    ("preprocess", "mask"),
])
def test_unknown_fields_are_not_silently_ignored(location, bad_field):
    value = _workflow()
    component = {"function": "gaussian", "constraints": {"sigma": {}}}
    value["models"] = [{"curve": "sample", "components": [component]}]
    if location == "workflow":
        target = value
    elif location == "import":
        target = value["imports"][0]
    elif location == "config":
        target = value["imports"][0].setdefault("config", {})
    elif location == "columns":
        target = value["imports"][0]["columns"]
    elif location == "model":
        target = value["models"][0]
    elif location == "component":
        target = component
    elif location == "constraint":
        target = component["constraints"]["sigma"]
    elif location == "fit":
        target = value.setdefault("fit", {})
    elif location == "settings":
        target = value.setdefault("fit", {}).setdefault("settings", {})
    elif location == "export":
        target = value.setdefault("export", {})
    elif location == "custom":
        target = {"identifier": "decay", "formula": "a*exp(-x/tau)"}
        value["custom_functions"] = [target]
    else:
        target = {"clear_masks": True}
        value["preprocess"] = [target]
    target[bad_field] = 1
    errors = validate_workflow(value)
    assert any("unknown field" in error and bad_field in error for error in errors)


@pytest.mark.parametrize("columns", [
    {"x": 0, "y": [1], "sigma_y": 2, "weights": 3},
    {"x": 0, "y": [1], "variance": 2, "inverse_variance": 3},
    {"x": 0, "y": [1], "error_y_plus": 2},
    {"x": 0, "y": [1], "error_y_minus": 2},
    {"spectra": [{"x": 0, "y": [1, 2]}]},
    {"spectra": [{"x": 0, "y": [1], "pairs": [[0, 1]]}]},
    {"spectra": [{"x": 0, "y": [1], "sigma_y": 2, "weights": 3}]},
    {"spectra": [{"x": 0, "y": [1], "error_y_plus": 2}]},
    {"spectra": [{"spectra": [{"x": 0, "y": [1]}]}]},
])
def test_column_mapping_semantic_errors_are_caught_without_loading_data(columns):
    value = _workflow()
    value["imports"][0]["columns"] = columns
    errors = validate_workflow(value)
    assert errors and any("columns" in error for error in errors)


@pytest.mark.parametrize("name", [1, False, "", ("sigma",)])
def test_constraint_keys_must_be_parameter_names(name):
    value = _workflow()
    value["models"] = [{"curve": "sample", "components": [{
        "function": "gaussian", "constraints": {name: {"minimum": 0}},
    }]}]
    assert any("parameter names" in error for error in validate_workflow(value))


@pytest.mark.parametrize("key,value", [
    ("header", "false"), ("header", 1), ("skip_rows", True), ("skip_rows", -1),
    ("delimiter", []), ("encoding", ""), ("comment_prefixes", "#"),
])
def test_import_config_boolean_and_container_errors_are_explicit(key, value):
    workflow = _workflow()
    workflow["imports"][0]["config"] = {key: value}
    assert any(f"config.{key}" in error for error in validate_workflow(workflow))


@pytest.mark.parametrize("settings", [
    {"use_data_errors": "false"}, {"absolute_sigma": "true"}, {"workers": True},
    {"max_nfev": 0}, {"seed": -1}, {"f_scale": float("nan")},
    {"ftol": "1e-10"}, {"x_scale": []}, {"nm_initial_simplex": [[1, 2]]},
])
def test_fit_setting_type_and_numeric_errors_are_checked_before_execution(settings):
    errors = validate_workflow(_workflow() | {"fit": {"settings": settings}})
    assert errors and any("fit.settings" in error for error in errors)


def test_static_validation_reads_no_data_or_plugin_files(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Static validation attempted filesystem/plugin I/O")

    for name in ("open", "read_bytes", "read_text", "iterdir", "exists", "is_file", "is_dir"):
        monkeypatch.setattr(Path, name, forbidden)
    monkeypatch.setattr("curvemole.core.workflow.import_file", forbidden)
    monkeypatch.setattr("curvemole.core.plugins.PluginManager.load", forbidden)
    value = _workflow() | {
        "plugins": ["missing/plugin.curvemole-plugin.json"],
        "custom_functions": [{
            "identifier": "decay", "formula": "amplitude*exp(-x/tau)",
            "defaults": {"amplitude": 1, "tau": 2}, "bounds": {"tau": [0.001, 100]},
        }],
        "models": [{"curves": "all", "components": [{"function": "plugin_function"}]}],
        "preprocess": [{"transformations": [{
            "operation": "custom_formula", "axis": "y", "formula": "2*y",
        }]}],
        "fit": {"settings": {"solver": "org.example:solver"}},
        "export": {"project": "missing/result.fitproj", "project_overwrite": False},
    }
    assert validate_workflow(value) == []


def test_structured_malformed_values_always_return_errors_instead_of_raising():
    values = [None, False, True, 0, -1, 2.5, "", "bad", [], {}, [{}], {"bad": []}]
    for value in values:
        assert isinstance(validate_workflow(value), list)
    for key in ("schema_version", "imports", "models", "fit", "export", "plugins",
                "custom_functions", "preprocess"):
        for value in values:
            assert isinstance(validate_workflow(_workflow() | {key: value}), list)
    for key in ("x", "y", "pairs", "spectra", "sigma_y", "weights", "error_confidence_level"):
        for value in values:
            workflow = _workflow()
            workflow["imports"][0]["columns"][key] = value
            assert isinstance(validate_workflow(workflow), list)
    for key in ("sort", "exclude", "recursive", "allow_empty", "alias_template", "curve_ids"):
        for value in values:
            workflow = _workflow()
            workflow["imports"][0][key] = deepcopy(value)
            assert isinstance(validate_workflow(workflow), list)


@pytest.mark.parametrize("configuration", [
    {"defaults": {"tao": 10}},
    {"bounds": {"tao": [0.01, 100]}},
    {"derived": {"half_life": "tao*log(2)"}},
    {"derived": {"coordinate_value": "x*2"}},
    {"derived": {"project_value": "${other.peak.tau}"}},
])
def test_custom_formula_configuration_cannot_silently_reference_unknown_parameters(configuration):
    value = _workflow() | {"custom_functions": [{
        "identifier": "decay", "formula": "amplitude*exp(-x/tau)", **configuration,
    }]}
    errors = validate_workflow(value)
    assert errors and any("custom_functions[0]" in error for error in errors)


def test_custom_derived_quantities_accept_declared_parameters_and_safe_constants():
    value = _workflow() | {"custom_functions": [{
        "identifier": "decay", "formula": "amplitude*exp(-x/tau)",
        "defaults": {"amplitude": 2, "tau": 1},
        "bounds": {"tau": [0.01, 100]},
        "derived": {"half_life": "tau*log(2)", "constant": "2*pi+log(e)"},
    }]}
    assert validate_workflow(value) == []
