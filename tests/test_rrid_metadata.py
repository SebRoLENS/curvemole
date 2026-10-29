"""Verify that CurveMole's version-independent identifier remains discoverable."""

from pathlib import Path

from curvemole.identifiers import RRID, RRID_URL

ROOT = Path(__file__).resolve().parents[1]


def test_rrid_documentation():
    assert RRID == "SCR_029214"
    assert RRID_URL == "https://scicrunch.org/resolver/RRID:SCR_029214"
    for name in ("README.md", "CITATION.cff", "docs/manual.md",
                 "docs/plugins.md", "custom_plugins/README.md",
                 "website/dist/index.html"):
        assert f"RRID:{RRID}" in (ROOT / name).read_text(encoding="utf-8"), name


def test_release_template_retains_rrid():
    for name in (".github/scripts/prepare_release.py",
                 ".github/scripts/sync_zenodo_doi.py"):
        assert "RRID:SCR_029214" in (ROOT / name).read_text(encoding="utf-8")
