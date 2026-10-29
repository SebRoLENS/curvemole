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


@pytest.mark.parametrize("status", ["1.0.0 Preview", "1.0.0 Stable", "1.0.0"])
def test_release_preparation_writes_stable_readme_from_legacy_or_stable_status(
    tmp_path, monkeypatch, status,
):
    prepare = _load_script("prepare_release_stable_readme", ".github/scripts/prepare_release.py")
    readme = tmp_path / "README.md"
    readme.write_text(
        prepare.VERSION_BADGE + "\n\n"
        + f"> **Status:** Version **{status}**.\n\n"
        + "Current public version: **1.0.0**\n\n"
        + "## How to cite\n\nOld citation.\n\n## License\n\nGPL-3.0.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prepare, "README", readme)

    prepare.update_readme("1.0.1")

    updated = readme.read_text(encoding="utf-8")
    assert "> **Status:** Version **1.0.1 Stable**." in updated
    assert "Current public version: **1.0.1**" in updated
    assert "/releases/tag/v1.0.1" in updated
    assert "RRID:SCR_029214" in updated
    assert "10.5281/zenodo.22113854" in updated
    assert "Preview" not in updated


@pytest.mark.parametrize("title", [
    "# CurveMole User Manual - Preview 1.0.0",
    "# CurveMole User Manual – 1.0.0",
    "# CurveMole User Manual — Stable 1.0.0",
])
def test_release_preparation_keeps_manual_stable_for_future_releases(
    tmp_path, monkeypatch, title,
):
    prepare = _load_script("prepare_release_stable_manual", ".github/scripts/prepare_release.py")
    manual = tmp_path / "manual.md"
    manual.write_text(
        title + "\n\n**Current manual version: 1.0.0**\n\n"
        + "### 20.3 Citation\n\nVersion 1.0.0.\n\n"
        + "### 20.4 Author and contact\n\nMaintainer.\n\n"
        + "## Appendix D. Version 1.0.0 limitations\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prepare, "MANUAL", manual)

    prepare.update_manual("1.0.1")

    updated = manual.read_text(encoding="utf-8")
    assert updated.startswith("# CurveMole User Manual - 1.0.1\n")
    assert "**Current manual version: 1.0.1**" in updated
    assert "## Appendix D. Version 1.0.1 limitations" in updated
    assert "/releases/tag/v1.0.1" in updated
    assert "RRID:SCR_029214" in updated
    assert "10.5281/zenodo.22113854" in updated
    assert "Preview" not in updated and "1.0.0" not in updated


def test_manual_release_bump_preserves_historical_requirements_and_semver_examples(
    tmp_path, monkeypatch,
):
    prepare = _load_script("prepare_release_manual_history", ".github/scripts/prepare_release.py")
    manual = tmp_path / "manual.md"
    manual.write_text(
        "# CurveMole User Manual - 1.0.0\n\n"
        "**Current manual version: 1.0.0**\n\n"
        "This manual describes the behavior of CurveMole 1.0.0 Stable.\n"
        "For example, a manual marked 1.0.0 describes CurveMole 1.0.0.\n"
        "./CurveMole-1.0.0-linux-x86_64.AppImage\n"
        "shasum -a 256 CurveMole-1.0.0-macos-arm64.dmg\n"
        "Get-FileHash CurveMole-1.0.0-windows-x86_64-setup.exe\n"
        "python -m pip install curvemole-1.0.0-py3-none-any.whl\n"
        "sigma_x is not used by the version 1.0.0 optimizer.\n"
        "This plugin version requires CurveMole 1.0.0 or later.\n"
        "| Patch (third) | Bugfix | `1.0.0` to `1.0.1` |\n\n"
        "### 20.3 Citation\n\nVersion 1.0.0.\n\n"
        "### 20.4 Author and contact\n\nMaintainer.\n\n"
        "## Appendix D. Version 1.0.0 limitations\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prepare, "MANUAL", manual)

    prepare.update_manual("1.1.0")

    updated = manual.read_text(encoding="utf-8")
    assert updated.startswith("# CurveMole User Manual - 1.1.0\n")
    assert "**Current manual version: 1.1.0**" in updated
    assert "describes the behavior of CurveMole 1.1.0 Stable." in updated
    assert "a manual marked 1.1.0 describes CurveMole 1.1.0." in updated
    for package in ("CurveMole-1.1.0-linux-x86_64.AppImage", "CurveMole-1.1.0-macos-arm64.dmg",
                    "CurveMole-1.1.0-windows-x86_64-setup.exe", "curvemole-1.1.0-py3-none-any.whl"):
        assert package in updated
    assert "not used by the version 1.1.0 optimizer." in updated
    assert "This plugin version requires CurveMole 1.0.0 or later." in updated
    assert "| Patch (third) | Bugfix | `1.0.0` to `1.0.1` |" in updated
    assert "## Appendix D. Version 1.1.0 limitations" in updated
    assert "/releases/tag/v1.1.0" in updated


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
