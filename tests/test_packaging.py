from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_apps_bundle_the_complete_resource_directory() -> None:
    spec = (ROOT / "packaging" / "curvemole.spec").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "build-desktop.yml").read_text(
        encoding="utf-8"
    )

    assert '"resources"), "curvemole/resources")' in spec
    assert '"--add-data", "src/curvemole/resources;curvemole/resources"' in workflow
