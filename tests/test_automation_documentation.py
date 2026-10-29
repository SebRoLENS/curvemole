"""Execute the examples users give an AI and keep the manual appendices in sync."""

from __future__ import annotations

import re
import shutil
from dataclasses import fields
from pathlib import Path

import numpy as np
import pytest

from curvemole import FitResult, FitSettings
from curvemole.core.importers import ColumnMapping, ImportConfig
from curvemole.core.serialization import load_project
from curvemole.core.workflow import run_workflow

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def _example(document: str, language: str, marker: str) -> str:
    text = (DOCS / document).read_text(encoding="utf-8")
    blocks = re.findall(rf"^```{language}\s*\n(.*?)^```\s*$", text, re.MULTILINE | re.DOTALL)
    selected = [block for block in blocks if f"# example: {marker}" in block]
    assert len(selected) == 1, f"Expected one executable {marker} example in {document}"
    return selected[0]


def _check_saved_fit_and_bundle(directory: Path) -> None:
    projects = list(directory.rglob("*.fitproj"))
    assert projects, "The documented example must save a reusable project"
    restored = load_project(projects[0])
    assert restored.curves
    result = restored.results.get("last_fit")
    assert isinstance(result, FitResult) and result.success
    assert np.isfinite(result.statistics["chi_square"])
    assert all(curve.id in result.curve_outputs for curve in restored.curves)
    assert list(directory.rglob("manifest.json")), "The example must produce an analysis bundle"


@pytest.mark.parametrize("document", ["python-api.md", "ai-python-audit.md"])
def test_documented_python_script_runs(document: str, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    source = _example(document, "python", "python-end-to-end")
    namespace = {"__name__": "__main__", "__file__": str(tmp_path / "example.py")}
    exec(compile(source, str(DOCS / document), "exec"), namespace)
    _check_saved_fit_and_bundle(tmp_path)


@pytest.mark.parametrize("document", ["workflows.md", "ai-yaml-audit.md"])
@pytest.mark.parametrize("marker", ["yaml-end-to-end", "yaml-linked-global"])
def test_documented_yaml_workflow_runs(document: str, marker: str, tmp_path: Path) -> None:
    shutil.copyfile(ROOT / "examples" / "gaussian.csv", tmp_path / "gaussian.csv")
    recipe = tmp_path / "workflow.yml"
    recipe.write_text(_example(document, "yaml", marker), encoding="utf-8")

    outcome = run_workflow(recipe)

    assert outcome.result is not None and outcome.result.success
    assert outcome.outputs and all(path.exists() for path in outcome.outputs)
    if marker == "yaml-linked-global":
        source, target = outcome.project.curves
        source_path = outcome.project.models[source.id].parameter_path(source.id, "peak", "center")
        target_path = outcome.project.models[target.id].parameter_path(target.id, "peak", "center")
        target_parameter = outcome.project.models[target.id].component("peak").parameters["center"]
        assert target_parameter.link == "${" + source_path + "}"
        assert target_path not in outcome.result.free_parameter_paths
        assert np.isclose(
            outcome.result.parameters[source_path].value,
            outcome.result.parameters[target_path].value,
        )
    _check_saved_fit_and_bundle(tmp_path)


@pytest.mark.parametrize("document", ["ai-python-audit.md", "ai-yaml-audit.md"])
@pytest.mark.parametrize("contract", [FitSettings, ImportConfig, ColumnMapping])
def test_ai_audits_cover_current_configuration_fields(document: str, contract: type) -> None:
    text = (DOCS / document).read_text(encoding="utf-8")
    missing = [field.name for field in fields(contract) if not re.search(rf"\b{field.name}\b", text)]
    assert not missing, f"{document} omits {contract.__name__} fields: {missing}"


def _as_appendix(text: str, title: str) -> str:
    lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
        elif not in_fence:
            if line.startswith("# "):
                line = title
            elif re.match(r"^#{2,6}\s", line):
                line = "#" + line
        lines.append(line)
    return "\n".join(lines).strip()


@pytest.mark.parametrize(
    ("document", "marker", "title"),
    [
        ("python-api.md", "PYTHON SCRIPTING REFERENCE", "## Appendix F. Python scripting reference"),
        ("workflows.md", "YAML WORKFLOW REFERENCE", "## Appendix G. YAML workflow reference"),
    ],
)
def test_manual_contains_complete_current_reference(document: str, marker: str, title: str) -> None:
    manual = (DOCS / "manual.md").read_text(encoding="utf-8")
    start = f"<!-- BEGIN {marker} (docs/{document}) -->"
    end = f"<!-- END {marker} -->"
    assert manual.count(start) == manual.count(end) == 1
    embedded = manual.split(start, 1)[1].split(end, 1)[0].strip()
    expected = _as_appendix((DOCS / document).read_text(encoding="utf-8"), title)
    assert embedded == expected, f"Regenerate Appendix {title.split('.')[0]} from {document}"
