from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "docs" / "manual.md"
GENERATED_TEX = ROOT / "docs" / "CurveMole_User_Manual.tex"
GENERATED_PDF = ROOT / "docs" / "CurveMole_User_Manual.pdf"
BUILD_MANUAL = ROOT / "scripts" / "build_manual.py"
PREPARE_RELEASE = ROOT / ".github" / "scripts" / "prepare_release.py"


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_manual = load_script("build_manual", BUILD_MANUAL)
prepare_pandoc_source = build_manual.prepare_pandoc_source
read_package_version = build_manual.read_package_version
validate_source = build_manual.validate_source


def test_manual_is_detailed_and_matches_package_version() -> None:
    version = read_package_version()
    text = validate_source(MANUAL, version)
    assert len(text.split()) >= 8_000
    for heading in (
        "## 6. Importing data",
        "## 8. Building models",
        "## 10. Fitting",
        "## 12. Explicit uncertainty analyses",
        "## 15. Command-line interface",
        "## 19. Troubleshooting",
        f"## Appendix D. Preview {version} limitations",
    ):
        assert heading in text


def test_pandoc_source_removes_github_header_and_promotes_headings() -> None:
    body = prepare_pandoc_source(MANUAL.read_text(encoding="utf-8"))
    assert not body.startswith("# CurveMole User Manual")
    assert body.startswith("CurveMole is a desktop-first")
    assert "\n# 1. About this manual\n" in body
    assert "\n## 1.1 Intended audience\n" in body


def test_generated_manual_editions_are_present_and_versioned() -> None:
    version = read_package_version()
    tex = GENERATED_TEX.read_text(encoding="utf-8")
    assert "CurveMole User Manual" in tex
    assert f"Version {version}" in tex
    pdf = GENERATED_PDF.read_bytes()
    assert pdf.startswith(b"%PDF-")
    assert GENERATED_PDF.stat().st_size >= 200_000
    canonical_tex = GENERATED_TEX.read_text(encoding="utf-8").encode("utf-8")
    document_id = hashlib.sha256(canonical_tex).hexdigest()[:32].encode()
    assert re.search(rb"/ID\[<([^>]+)><([^>]+)>\]", pdf).groups() == (
        document_id,
        document_id,
    )


def test_release_bump_updates_every_manual_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_script("prepare_release", PREPARE_RELEASE)

    old_version = read_package_version()
    new_version = "99.98.97"
    temporary_manual = tmp_path / "manual.md"
    temporary_manual.write_text(MANUAL.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(module, "MANUAL", temporary_manual)

    module.update_manual(new_version)

    updated = temporary_manual.read_text(encoding="utf-8")
    assert old_version not in updated
    assert f"# CurveMole User Manual - Preview {new_version}" in updated
    assert f"releases/tag/v{new_version}" in updated
    assert "[Computer software]. GitHub." in updated
