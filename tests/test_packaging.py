from __future__ import annotations

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_apps_bundle_the_complete_resource_directory() -> None:
    spec = (ROOT / "packaging" / "curvemole.spec").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "build-desktop.yml").read_text(
        encoding="utf-8"
    )

    assert '"resources"), "curvemole/resources")' in spec
    assert "packaging/curvemole.spec" in workflow
    assert '$env:CURVEMOLE_ONEFILE = "1"' in workflow

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


def test_all_desktop_builds_explicitly_collect_dynamic_svg_renderer() -> None:
    # savefig resolves backend_svg by name at runtime. PyInstaller's automatic
    # backend choice may select Agg, QtAgg or MacOSX and omit SVG entirely.
    spec = ast.parse((ROOT / "packaging" / "curvemole.spec").read_text(encoding="utf-8"))
    analysis = next(node for node in ast.walk(spec)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "Analysis")
    imports = ast.literal_eval(next(keyword.value for keyword in analysis.keywords
                                    if keyword.arg == "hiddenimports"))
    assert "matplotlib.backends.backend_svg" in imports

    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "build-desktop.yml").read_text(encoding="utf-8")
    )
    windows = workflow["jobs"]["windows"]["steps"]
    build = next(step["run"] for step in windows if step.get("name") == "Build standalone executable")
    assert "packaging/curvemole.spec" in build


def test_stable_appimage_is_direct_and_beta_artifact_requires_beta_version() -> None:
    desktop = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "build-desktop.yml").read_text(encoding="utf-8")
    )
    candidate = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "test-linux-candidate.yml").read_text(
            encoding="utf-8"
        )
    )
    linux_steps = desktop["jobs"]["linux"]["steps"]
    artifacts = [step for step in linux_steps
                 if step.get("uses", "").startswith("actions/upload-artifact")]
    assert len(artifacts) == 1
    assert artifacts[0]["if"] == "inputs.beta_version != ''"
    direct_upload = next(
        step for step in linux_steps if step.get("name") == "Attach Linux files directly to tagged release"
    )
    assert "startsWith(inputs.source_ref, 'v')" in direct_upload["if"]
    assert "gh release upload" in direct_upload["run"]
    publish_steps = desktop["jobs"]["publish-release-assets"]["steps"]
    assert any("gh release download" in step.get("run", "") for step in publish_steps)
    policy = (ROOT / ".github/scripts/workflow_plan.py").read_text(encoding="utf-8")
    assert '"[skip release]" in message' in policy
    assert "source_ref" in candidate["jobs"]["appimage"]["steps"][0]["with"]["ref"]


def test_packaging_smoke_creates_valid_png_svg_and_pdf(tmp_path) -> None:
    import xml.etree.ElementTree as ET

    from PIL import Image

    from curvemole import Component, Curve, Project
    from curvemole.core.functions import formula_definition
    from curvemole.core.packaging_smoke import _smoke_graphic_exports
    from curvemole.core.registry import default_registry

    project = Project("Renderer packaging smoke")
    curve = Curve("sample", [0., 1., 2.], [1., 2., 1.])
    project.add_curve(curve)
    registry = default_registry()
    registry.register(formula_definition("packaging_export", "Packaging export", "a * exp(-x*x)",
                                         defaults={"a": 1.}))
    project.model_for(curve.id).add(Component.create("packaging_export", registry=registry))
    _smoke_graphic_exports(project, tmp_path, registry=registry)

    with Image.open(tmp_path / "packaging-plot.png") as image:
        assert image.format == "PNG"
        assert image.size == (120, 80)
        image.verify()
    assert ET.parse(tmp_path / "packaging-plot.svg").getroot().tag.endswith("}svg")
    assert (tmp_path / "packaging-report.pdf").read_bytes().startswith(b"%PDF-")
