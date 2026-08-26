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
