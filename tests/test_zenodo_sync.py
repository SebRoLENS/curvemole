from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/sync_zenodo_doi.py"


def _module():
    spec = importlib.util.spec_from_file_location("zenodo_sync", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_find_doi_uses_version_filter_for_published_older_release(monkeypatch) -> None:
    zenodo = _module()
    queries = []

    def records(query):
        queries.append(query)
        if query != "metadata.version:v0.28.9":
            return []
        return [
            {"id": "1", "metadata": {"title": "Another project", "version": "v0.28.9"}, "doi": "10.5281/zenodo.1"},
            {"id": "22959234", "metadata": {"title": "CurveMole: Modular Scientific Curve Fitting", "version": "v0.28.9"}, "pids": {"doi": {"identifier": "10.5281/zenodo.22959234"}}},
        ]

    monkeypatch.setattr(zenodo, "zenodo_records", records)
    assert zenodo.find_doi("0.28.9") == "10.5281/zenodo.22959234"
    assert queries[0] == "metadata.version:v0.28.9"


def test_previously_resolved_doi_does_not_query_zenodo() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--version", "0.28.10", "--doi", "10.5281/zenodo.22959234"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "10.5281/zenodo.22959234"


def test_historical_release_cannot_replace_current_citation() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--version", "0.28.9", "--doi", "10.5281/zenodo.22959234", "--apply"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "historical release DOI" in result.stderr
