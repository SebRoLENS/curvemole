from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from runpy import run_path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
citations = run_path(str(ROOT / ".github/scripts/citation_metadata.py"))


def test_metadata_changes_reach_every_citation_format():
    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    text = text.replace("family-names: Romi", "family-names: Example")
    text = text.replace("given-names: Sebastiano", "given-names: Ada Maria")
    text = text.replace('title: "CurveMole: Modular Scientific Curve Fitting"',
                        'title: "CurveMole & research"')
    data = citations["metadata"](text)
    assert "Example, A. M." in data["citation"]
    assert "CurveMole &amp; research" in citations["website_section"](data)
    assert "Example, Ada Maria" in citations["bibtex"](data)
    assert "Romi" not in citations["readme_section"](data)


def test_future_release_never_reuses_the_previous_version_doi():
    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    data = citations["metadata"](text, "9.8.7")
    assert not data["doi"]
    assert data["url"].endswith("/releases/tag/v9.8.7")
    assert "archival is pending" in citations["manual_section"](data)
    assert "23730744" not in citations["readme_section"](data)
    assert "version = {9.8.7}" in citations["bibtex"](data)
    project = citations["bibtex"](data, project=True)
    assert "version =" not in project
    assert f'doi = {{{data["concept_doi"]}}}' in project


def test_refresh_is_idempotent_and_updates_the_manual_after_archival(tmp_path):
    for name in ("README.md", "docs/manual.md", "website/dist/index.html", "CITATION.cff"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    cff = tmp_path / "CITATION.cff"
    text = cff.read_text(encoding="utf-8")
    text = re.sub(r"^version:.*$", 'version: "9.8.7"', text, flags=re.M)
    text = re.sub(r"^doi:.*\n", "", text, flags=re.M)
    cff.write_text(text, encoding="utf-8")
    citations["refresh"](tmp_path)
    assert "archival is pending" in (tmp_path / "docs/manual.md").read_text(encoding="utf-8")
    cff.write_text(text + 'doi: "10.5281/zenodo.987654"\n', encoding="utf-8")
    citations["refresh"](tmp_path)
    before = {name: (tmp_path / name).read_bytes() for name in citations["GENERATED"]}
    citations["refresh"](tmp_path)
    assert before == {name: (tmp_path / name).read_bytes() for name in before}
    for name in ("README.md", "docs/manual.md", "docs/citing.md", "website/dist/index.html"):
        content = (tmp_path / name).read_text(encoding="utf-8")
        assert "10.5281/zenodo.987654" in content
        assert "Zenodo archival is pending;" not in content
    assert (tmp_path / "docs/citation.bib").read_bytes() == (tmp_path / "website/dist/citation.bib").read_bytes()


def test_structured_cff_metadata_and_generated_sections_are_current():
    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    cff = yaml.safe_load(text)
    data = citations["metadata"](text)
    assert data["doi"] == cff["doi"]
    assert data["authors"] == cff["authors"]
    assert citations["readme_section"](data).strip() in (ROOT / "README.md").read_text(encoding="utf-8")
    assert citations["manual_section"](data).strip() in (ROOT / "docs/manual.md").read_text(encoding="utf-8")
    assert citations["website_section"](data) in (ROOT / "website/dist/index.html").read_text(encoding="utf-8")


def test_independent_website_copy_actions():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to exercise browser JavaScript")
    subprocess.run([node, "--test", str(ROOT / "tests/citation_actions.cjs")], check=True)
