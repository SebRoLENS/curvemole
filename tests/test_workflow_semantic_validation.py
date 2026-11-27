from curvemole.core.workflow import validate_workflow


def _workflow(function="gaussian", parameter="center", curve="Synthetic Gaussian"):
    return {
        "schema_version": 1,
        "imports": [{"path": "gaussian.csv", "columns": {"x": "x", "y": ["y"]}, "aliases": ["Synthetic Gaussian"]}],
        "models": [{"curve": curve, "components": [{"function": function, "parameters": {parameter: 0.3}}]}],
        "fit": {"mode": "independent", "curves": ["Synthetic Gaussian"]},
    }


def test_valid_workflow_has_no_failures():
    assert validate_workflow(_workflow()) == []


def test_misspelt_function_parameter_and_curve_are_reported_with_suggestions():
    (function,) = validate_workflow(_workflow(function="gausian"))
    assert "gausian" in function and "Did you mean 'gaussian'" in function
    (parameter,) = validate_workflow(_workflow(parameter="centre"))
    assert "Did you mean 'center'" in parameter and "Available: area, center, sigma" in parameter
    (curve,) = validate_workflow(_workflow(curve="Synthetic Gausian"))
    assert "unknown curve 'Synthetic Gausian'" in curve


def test_plugin_functions_are_left_to_run():
    workflow = _workflow(function="plugin_peak")
    workflow["plugins"] = ["plugins/example/plugin.json"]
    assert validate_workflow(workflow) == []
