from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/sync_zenodo_doi.py"


def _module(script=SCRIPT):
    spec = importlib.util.spec_from_file_location(script.stem, script)
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


def test_release_and_doi_sync_preserve_official_links_and_citation_details(tmp_path, monkeypatch) -> None:
    prepare = _module(ROOT / ".github/scripts/prepare_release.py")
    zenodo = _module()
    citation = tmp_path / "CITATION.cff"
    original = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    citation.write_text((ROOT / "CITATION.cff").read_text(encoding="utf-8"), encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(
        zenodo.VERSION_BADGE + "\n\n## How to cite\n\nPending.\n\n## License\n\nGPL-3.0.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prepare, "CITATION", citation)
    monkeypatch.setattr(zenodo, "CITATION", citation)
    monkeypatch.setattr(zenodo, "README", readme)

    prepare.update_citation("1.0.1")
    pending = yaml.safe_load(citation.read_text(encoding="utf-8"))
    assert pending["version"] == "1.0.1"
    assert "doi" not in pending
    assert pending["url"] == "https://sebrolens.github.io/curvemole/"
    assert pending["abstract"].startswith("Official website: https://sebrolens.github.io/curvemole/")
    assert "Download the latest version: https://github.com/SebRoLENS/curvemole/releases/latest" in pending["abstract"]

    zenodo.apply_metadata("1.0.1", "10.5281/zenodo.99999999")
    archived = yaml.safe_load(citation.read_text(encoding="utf-8"))
    assert archived["doi"] == "10.5281/zenodo.99999999"
    for field in ("url", "abstract", "keywords", "title", "authors", "license", "repository-code"):
        assert archived[field] == original[field]
    assert "(Version 1.0.1)" in readme.read_text(encoding="utf-8")
    assert "https://doi.org/10.5281/zenodo.99999999" in readme.read_text(encoding="utf-8")
    first_sync = citation.read_text(encoding="utf-8")
    zenodo.apply_metadata("1.0.1", "10.5281/zenodo.99999999")
    assert citation.read_text(encoding="utf-8") == first_sync
