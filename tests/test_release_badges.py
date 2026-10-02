from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str, relative_path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_scripts_accept_centered_html_badges() -> None:
    prepare = _load_script("prepare_release_test", ".github/scripts/prepare_release.py")
    zenodo = _load_script("sync_zenodo_test", ".github/scripts/sync_zenodo_doi.py")
    readme_header = """<p align=\"center\">
  <a href=\"https://github.com/SebRoLENS/curvemole/releases/latest\"><img src=\"https://img.shields.io/github/v/release/SebRoLENS/curvemole\" alt=\"Version\"></a>
  <a href=\"https://doi.org/10.5281/zenodo.22132337\"><img src=\"https://zenodo.org/badge/DOI/10.5281/zenodo.22132337.svg\" alt=\"DOI\"></a>
</p>"""

    pending = prepare.pending_badges(readme_header)
    assert "DOI-pending-lightgrey" in pending
    assert prepare.VERSION_BADGE_RE.search(pending)
    assert prepare.DOI_BADGE_RE.search(pending)
    assert zenodo.VERSION_BADGE_RE.search(pending)
    assert zenodo.DOI_BADGE_RE.search(pending)


@pytest.mark.parametrize("requested,allowed", [("0.36.1", True), ("0.36.2", True),
                                               ("0.36.0", False), ("0.35.9", False)])
def test_release_can_resume_prepared_version_only_before_it_has_a_tag(monkeypatch, requested, allowed):
    prepare = _load_script("prepare_release_resume", ".github/scripts/prepare_release.py")
    monkeypatch.setattr(prepare, "read_current_version", lambda: "0.36.1")
    monkeypatch.setattr(prepare, "released_versions", lambda: ["0.36.0"])
    if allowed:
        assert prepare.choose_version(explicit_version=requested) == requested
    else:
        with pytest.raises(SystemExit):
            prepare.choose_version(explicit_version=requested)
    monkeypatch.setattr(prepare, "released_versions", lambda: ["0.36.0", "0.36.1"])
    with pytest.raises(SystemExit):
        prepare.choose_version(explicit_version="0.36.1")
