from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_apps_bundle_the_complete_resource_directory() -> None:
    spec = (ROOT / "packaging" / "curvemole.spec").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "build-desktop.yml").read_text(
        encoding="utf-8"
    )

    assert '"resources"), "curvemole/resources")' in spec
    assert '"--add-data", "src/curvemole/resources;curvemole/resources"' in workflow

def test_linux_release_includes_a_detached_sigstore_signature() -> None:
    workflow = (ROOT / ".github" / "workflows" / "build-desktop.yml").read_text(
        encoding="utf-8"
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "actions/attest@v4" in workflow
    assert "steps.attest.outputs.bundle-path" in workflow
    assert ".sigstore.json" in workflow
    assert "gh attestation verify" in readme
    assert readme.index("## Download") < readme.index("## Why CurveMole?")


def test_actions_appimage_artifact_is_limited_to_skip_release() -> None:
    desktop = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "build-desktop.yml").read_text(encoding="utf-8")
    )
    candidate = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "test-linux-candidate.yml").read_text(
            encoding="utf-8"
        )
    )
    linux_steps = desktop["jobs"]["linux"]["steps"]
    assert not any(
        step.get("uses", "").startswith("actions/upload-artifact") for step in linux_steps
    )
    direct_upload = next(
        step for step in linux_steps if step.get("name") == "Attach Linux files directly to tagged release"
    )
    assert "startsWith(inputs.source_ref, 'v')" in direct_upload["if"]
    assert "gh release upload" in direct_upload["run"]
    publish_steps = desktop["jobs"]["publish-release-assets"]["steps"]
    assert any("gh release download" in step.get("run", "") for step in publish_steps)
    assert "[skip release]" in candidate["jobs"]["appimage"]["if"]
