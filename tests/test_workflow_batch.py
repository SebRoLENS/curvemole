"""Exercise batch YAML recipes through importing, scientific operations and saves."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from curvemole.cli import EXIT_OK, main
from curvemole.core.data import CurveState
from curvemole.core.errors import CurveMoleError
from curvemole.core.functions import builtin_definitions
from curvemole.core.registry import FunctionRegistry
from curvemole.core.serialization import load_project
from curvemole.core.workflow import dump_workflow, run_workflow

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "gaussian.csv"


def write_recipe(root: Path, specification: dict, name: str = "workflow.yml") -> Path:
    path = root / name
    path.write_text(yaml.safe_dump({"schema_version": 3, **specification}, sort_keys=False), encoding="utf-8")
    return path


def gaussian_file(root: Path, name: str, *, scale: float = 1.0) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.loadtxt(EXAMPLE, delimiter=",", skiprows=1)
    data[:, 1:] *= scale
    np.savetxt(path, data, delimiter=",", header="x,y,sigma_y", comments="")
    return path


def mapping() -> dict:
    return {"config": {"delimiter": ",", "header": True}, "columns": {"x": "x", "y": ["y"], "sigma_y": "sigma_y"}}


def gaussian_components(*, x_shift: float = 0, scale: float = 1) -> list[dict]:
    return [
        {"function": "constant", "id": "background", "is_background": True,
         "parameters": {"offset": 0.1 * scale}},
        {"function": "gaussian", "id": "peak",
         "parameters": {"area": 3.0 * scale, "center": 0.4 + x_shift, "sigma": 1.0},
         "constraints": {"sigma": {"minimum": 0.001, "maximum": 5.0}}},
    ]


def fresh_registry() -> FunctionRegistry:
    registry = FunctionRegistry()
    registry.extend(builtin_definitions())
    return registry


def test_folder_recipe_orders_preprocesses_fits_and_saves(tmp_path):
    second = gaussian_file(tmp_path, "data/scan2.csv")
    tenth = gaussian_file(tmp_path, "data/scan10.csv")
    nested = gaussian_file(tmp_path, "data/z/scan3.csv")
    (tmp_path / "data/z/skip_calibration.csv").write_text("not numeric data", encoding="utf-8")
    unchanged_input = second.read_bytes()
    recipe = write_recipe(tmp_path, {
        "imports": [{
            "directory": "data", "recursive": True, "exclude": ["skip_*.csv"],
            "sort": "natural", "alias_template": "{stem}_{curve_index}",
            "curve_id_template": "batch_{file_index}_{curve_index}", **mapping(),
        }],
        "preprocess": [{
            "curves": "all",
            "transformations": [{"operation": "x_add", "value": 2}, {"operation": "y_multiply", "value": 2}],
            "mask_intervals": [[-3, -2]], "fit_ranges": [[-2.5, 6]],
        }],
        "models": [
            {"curves": "all", "components": gaussian_components(x_shift=2, scale=2)},
            {"curve": "batch_2_1", "name": "Second selected by stable identity"},
        ],
        "fit": {"curves": "all", "mode": "independent"},
        "export": {"project": "out/batch.report", "project_overwrite": False},
    })

    outcome = run_workflow(recipe)

    assert outcome.imported_files == [second.resolve(), tenth.resolve(), nested.resolve()]
    assert [curve.name for curve in outcome.project.curves] == ["scan2_1", "scan10_1", "scan3_1"]
    assert outcome.result is not None and outcome.result.success
    assert len(outcome.result.curve_outputs) == 3
    assert not outcome.warnings
    first = outcome.project.curves[0]
    np.testing.assert_allclose(first.x, first.original_x + 2)
    np.testing.assert_allclose(first.y, first.original_y * 2)
    assert np.count_nonzero(first.effective_mask) == 5
    for curve in outcome.project.curves:
        assert 2 < outcome.project.models[curve.id].component("peak").parameters["center"].value < 3
        output = outcome.result.curve_outputs[curve.id]
        assert np.all(output.x > -2) and np.all(output.x <= 6)
    assert outcome.project.models[outcome.project.curves[1].id].name == "Second selected by stable identity"
    assert second.read_bytes() == unchanged_input
    assert outcome.outputs == [tmp_path / "out/batch.fitproj"]
    restored = load_project(outcome.outputs[0])
    assert restored.results["last_fit"].success
    np.testing.assert_allclose(restored.curves[0].y, first.y)
    np.testing.assert_array_equal(restored.curves[0].effective_mask, first.effective_mask)
    assert len(restored.curves[0].transformations) == 2


def test_glob_models_and_fit_match_only_selected_curves_and_keep_parameters_independent(tmp_path):
    gaussian_file(tmp_path, "data/sample2.csv")
    gaussian_file(tmp_path, "data/sample10.csv", scale=2)
    gaussian_file(tmp_path, "data/reference.csv")
    recipe = write_recipe(tmp_path, {
        "imports": [{"glob": "data/*.csv", "alias_template": "{stem}", **mapping()}],
        "models": [{"match": "sample*", "components": gaussian_components()}],
        "fit": {"match": "sample*", "mode": "independent"},
    })

    outcome = run_workflow(recipe)

    assert outcome.result is not None and outcome.result.success
    selected = {curve.name: curve for curve in outcome.project.curves}
    reference = selected["reference"]
    first, second = selected["sample2"], selected["sample10"]
    assert not outcome.project.models[reference.id].components
    assert set(outcome.result.curve_outputs) == {first.id, second.id}
    first_peak = outcome.project.models[first.id].component("peak")
    second_peak = outcome.project.models[second.id].component("peak")
    assert first_peak is not second_peak
    assert first_peak.parameters["area"] is not second_peak.parameters["area"]
    assert second_peak.parameters["area"].value == pytest.approx(first_peak.parameters["area"].value * 2, rel=0.001)


def test_explicit_aliases_and_identities_flatten_across_files_and_y_columns(tmp_path):
    data = np.column_stack((np.arange(5), np.arange(5) + 1, np.arange(5) + 10))
    for name in ("scan2.csv", "scan10.csv"):
        np.savetxt(tmp_path / name, data, delimiter=",", header="x,a,b", comments="")
    recipe = write_recipe(tmp_path, {
        "imports": [{
            "glob": "*.csv", "config": {"delimiter": ",", "header": True},
            "columns": {"x": "x", "y": ["a", "b"]},
            "aliases": ["A", "B", "C", "D"], "curve_ids": ["aa", "bb", "cc", "dd"],
        }],
        "models": [{"curve": "cc", "components": [{"function": "constant", "parameters": {"offset": 9}}]}],
    })

    outcome = run_workflow(recipe)

    assert [curve.name for curve in outcome.project.curves] == ["A", "B", "C", "D"]
    assert [path.name for path in outcome.imported_files] == ["scan2.csv", "scan10.csv"]
    curves = outcome.project.curves
    np.testing.assert_allclose(curves[0].y, data[:, 1])
    np.testing.assert_allclose(curves[1].y, data[:, 2])
    np.testing.assert_allclose(curves[2].y, data[:, 1])
    assert outcome.project.models[curves[2].id].components[0].parameters["offset"].value == 9
    assert not outcome.project.models[curves[0].id].components


def test_duplicate_generated_identity_fails_before_any_export(tmp_path):
    gaussian_file(tmp_path, "scan1.csv")
    gaussian_file(tmp_path, "scan2.csv")
    recipe = write_recipe(tmp_path, {
        "imports": [{"glob": "*.csv", "curve_id_template": "same", **mapping()}],
        "export": {"project": "out/result.fitproj", "bundle": "out/bundle"},
    })

    with pytest.raises(CurveMoleError, match="Duplicate workflow curve identity"):
        run_workflow(recipe)
    assert not (tmp_path / "out").exists()


def test_allowed_empty_import_reports_warning_and_keeps_valid_files(tmp_path):
    data = gaussian_file(tmp_path, "valid.csv")
    recipe = write_recipe(tmp_path, {
        "imports": [
            {"glob": "missing*.csv", "allow_empty": True, **mapping()},
            {"path": "valid.csv", **mapping()},
        ],
    })

    outcome = run_workflow(recipe)

    assert outcome.imported_files == [data.resolve()]
    assert len(outcome.project.curves) == 1
    assert len(outcome.warnings) == 1 and "imports[0]" in outcome.warnings[0]
    assert outcome.result is None


def test_custom_formula_survives_project_save_and_dump_replay_with_fresh_registry(tmp_path):
    x = np.linspace(-2, 2, 9)
    expected = 1 + 2 * x
    np.savetxt(tmp_path / "line.csv", np.column_stack((x, expected)), delimiter=",", header="x,y", comments="")
    recipe = write_recipe(tmp_path, {
        "imports": [{"path": "line.csv", "config": {"delimiter": ",", "header": True}, "columns": {"x": "x", "y": ["y"]}}],
        "custom_functions": [{
            "identifier": "workflow_batch_linear", "formula": "offset + slope*x",
            "defaults": {"offset": 1, "slope": 2}, "derived": {"double_slope": "2*slope"},
        }],
        "models": [{"curves": "all", "components": [{"function": "workflow_batch_linear", "id": "line"}]}],
        "fit": {"mode": "independent"}, "export": {"project": "line.fitproj"},
    })

    outcome = run_workflow(recipe, registry=fresh_registry())
    assert outcome.result is not None and outcome.result.success
    restored = load_project(tmp_path / "line.fitproj")
    assert restored.custom_functions[0]["derived_formulas"] == {"double_slope": "2*slope"}
    dumped = dump_workflow(restored, tmp_path / "replay.yml")
    dumped_value = yaml.safe_load(dumped.read_text(encoding="utf-8"))
    assert dumped_value["custom_functions"][0]["derived"] == {"double_slope": "2*slope"}

    registry = fresh_registry()
    replayed = run_workflow(dumped, registry=registry)
    curve = replayed.project.curves[0]
    model = replayed.project.models[curve.id]
    np.testing.assert_allclose(model.evaluate(curve.x, curve_id=curve.id, registry=registry), expected)
    assert model.derived_quantities(curve_id=curve.id, registry=registry)["line"]["double_slope"] == pytest.approx(4)


def test_nested_spectrum_mappings_use_each_curves_own_uncertainties(tmp_path):
    x = np.arange(5.0)
    data = np.column_stack((x, x + 1, np.full(5, 0.1), x + 10, np.full(5, 0.2)))
    np.savetxt(tmp_path / "paired.csv", data, delimiter=",", header="x,a,sa,b,sb", comments="")
    recipe = write_recipe(tmp_path, {
        "imports": [{
            "path": "paired.csv", "config": {"delimiter": ",", "header": True},
            "columns": {"spectra": [
                {"x": "x", "y": ["a"], "sigma_y": "sa"},
                {"x": "x", "y": ["b"], "sigma_y": "sb"},
            ]},
            "aliases": ["first", "second"],
        }],
    })

    outcome = run_workflow(recipe)

    first, second = outcome.project.curves
    np.testing.assert_allclose(first.y, x + 1)
    np.testing.assert_allclose(second.y, x + 10)
    np.testing.assert_allclose(first.current_sigma_y, np.full(5, 0.1))
    np.testing.assert_allclose(second.current_sigma_y, np.full(5, 0.2))


def test_project_overwrite_guard_checks_normalized_destination_before_import(tmp_path):
    original = b"preserve existing result"
    destination = tmp_path / "existing.fitproj"
    destination.write_bytes(original)
    recipe = write_recipe(tmp_path, {
        "imports": [{"path": "does-not-exist.csv", **mapping()}],
        "export": {"project": "existing.report", "project_overwrite": False, "bundle": "bundle"},
    })

    with pytest.raises(CurveMoleError, match="already exists"):
        run_workflow(recipe)
    assert destination.read_bytes() == original
    assert not (tmp_path / "bundle").exists()


def test_sequential_recipe_uses_first_model_as_seed_and_fits_only_the_next_curve(tmp_path):
    gaussian_file(tmp_path, "scan2.csv")
    gaussian_file(tmp_path, "scan10.csv")
    recipe = write_recipe(tmp_path, {
        "imports": [{"glob": "scan*.csv", "alias_template": "{stem}", **mapping()}],
        "models": [{"curves": "first", "components": gaussian_components()}],
        "fit": {"mode": "sequential"},
    })

    outcome = run_workflow(recipe)

    assert outcome.result is not None and outcome.result.success
    source, target = outcome.project.curves
    assert source.name == "scan2" and target.name == "scan10"
    assert set(outcome.result.curve_outputs) == {target.id}
    assert source.state == CurveState.NOT_FITTED
    assert target.state == CurveState.FITTED
    source_model, target_model = outcome.project.models[source.id], outcome.project.models[target.id]
    assert len(target_model.components) == len(source_model.components) == 2
    assert source_model.component("peak").parameters["center"].value == 0.4
    assert target_model.component("peak").parameters["center"].value == pytest.approx(0.4, abs=0.1)


def test_cli_json_reports_discovered_files_and_allowed_empty_warning(tmp_path, capsys):
    data = gaussian_file(tmp_path, "valid.csv")
    recipe = write_recipe(tmp_path, {
        "imports": [
            {"glob": "missing*.csv", "allow_empty": True, **mapping()},
            {"glob": "valid*.csv", **mapping()},
        ],
    })

    assert main(["run", str(recipe), "--json"]) == EXIT_OK
    response = json.loads(capsys.readouterr().out)
    assert response["imported_files"] == [str(data.resolve())]
    assert len(response["warnings"]) == 1 and "allow_empty" in response["warnings"][0]
    assert response["success"] is None
