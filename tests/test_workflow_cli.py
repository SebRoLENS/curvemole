from __future__ import annotations

import json
import shutil
from pathlib import Path

from curvemole.cli import EXIT_OK, main
from curvemole.core.workflow import run_workflow


def test_example_workflow(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "examples"
    shutil.copy(source / "gaussian.csv", tmp_path / "gaussian.csv")
    shutil.copy(source / "gaussian_workflow.yml", tmp_path / "workflow.yml")
    outcome = run_workflow(tmp_path / "workflow.yml")
    assert outcome.result is not None and outcome.result.success
    assert (tmp_path / "gaussian_result.fitproj").exists()


def test_cli_functions_json(capsys) -> None:
    assert main(["--json", "functions", "list"]) == EXIT_OK
    value = json.loads(capsys.readouterr().out)
    assert {item["identifier"] for item in value} >= {"gaussian", "lorentzian", "voigt", "pseudo_voigt"}


def test_folder_example_workflow(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "examples"
    shutil.copy(source / "gaussian.csv", tmp_path / "gaussian.csv")
    shutil.copy(source / "folder_workflow.yml", tmp_path / "workflow.yml")

    outcome = run_workflow(tmp_path / "workflow.yml")

    assert outcome.result is not None and outcome.result.success
    assert outcome.imported_files == [tmp_path / "gaussian.csv"]
    assert (tmp_path / "folder_result.fitproj").exists()


def test_validate_round_trip_and_malformed_fitmodel(tmp_path, capsys):
    from curvemole import Component, Model
    from curvemole.cli import EXIT_PROJECT
    from curvemole.core.serialization import save_fitmodel

    path = save_fitmodel(Model(components=[Component.create("gaussian")]), tmp_path / "valid")
    assert main(["validate", str(path), "--json"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out) == {"valid": True, "failures": []}
    valid = json.loads(path.read_text())
    for invalid in ([], dict(valid, model={}), dict(valid, schema_version="broken"),
                    dict(valid, custom_functions="oops")):
        path.write_text(json.dumps(invalid))
        assert main(["validate", str(path), "--json"]) == EXIT_PROJECT
        result = json.loads(capsys.readouterr().out)
        assert result["valid"] is False and result["failures"]
