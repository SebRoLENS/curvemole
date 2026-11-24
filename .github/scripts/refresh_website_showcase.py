"""Render website screenshots and examples using the verified stable application."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from quick_start_publication import PNG_SIGNATURE, check_checkout, metadata_for

ROOT = Path(__file__).resolve().parents[2]
CAPTURES = {
    "render_demo_screenshots.py": (
        "demo/fit-dark.png", "demo/fit-light.png", "demo/overlay-dark.png", "demo/waterfall-dark.png",
    ),
    "render_project_screenshots.py": ("experimental/fit-dark.png",),
    "render_customization_screenshots.py": (
        "customization/composite-model.jpg", "customization/function-builder.jpg", "customization/plugin-manager.jpg",
    ),
}
ALIASES = {"fit.png": "demo/fit-dark.png", "overlay.png": "demo/overlay-dark.png",
           "waterfall.png": "demo/waterfall-dark.png"}
EXAMPLES = ("spectrum", "oscillation", "kinetics")
GENERATOR = Path("website/dist/examples/generate_scientific_examples.py")


def refresh(snapshot: Path, checkout: Path) -> None:
    metadata = metadata_for(snapshot)
    check_checkout(checkout, metadata)
    version = metadata["version"]
    stable_assets = checkout / "website/dist/assets"
    target_assets = snapshot / "assets"
    sha256 = {}
    with tempfile.TemporaryDirectory(prefix="curvemole-website-showcase-") as scratch:
        environment = os.environ.copy()
        environment.update(
            PYTHONPATH=str(checkout / "src"), QT_QPA_PLATFORM="offscreen",
            CURVEMOLE_DISABLE_UPDATE_CHECK="1", XDG_DATA_HOME=scratch,
            XDG_CONFIG_HOME=scratch, XDG_CACHE_HOME=scratch, MPLCONFIGDIR=scratch,
        )
        for script, names in CAPTURES.items():
            files = [stable_assets / name for name in names]
            previous = [path.stat().st_mtime_ns if path.exists() else None for path in files]
            subprocess.run([sys.executable, str(checkout / "website/scripts" / script)],
                           cwd=checkout, env=environment, check=True)
            for source, name, timestamp in zip(files, names, previous, strict=True):
                signature = PNG_SIGNATURE if source.suffix == ".png" else b"\xff\xd8\xff"
                if (not source.is_file() or source.stat().st_mtime_ns == timestamp
                        or not source.read_bytes().startswith(signature)):
                    raise ValueError(f"Missing fresh screenshot: {name}")
                target = target_assets / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if source != target:
                    shutil.copyfile(source, target)
                sha256[name] = hashlib.sha256(target.read_bytes()).hexdigest()

        for alias, current in ALIASES.items():
            shutil.copyfile(target_assets / current, target_assets / alias)
            sha256[alias] = sha256[current]

        generated = Path(scratch) / "examples"
        generator = ROOT / GENERATOR
        subprocess.run([sys.executable, str(generator), "--output", str(generated)],
                       cwd=checkout, env=environment, check=True)
        summaries = json.loads((generated / "results.json").read_text(encoding="utf-8"))
        if ({item["key"] for item in summaries} != set(EXAMPLES)
                or any(item["engine"] != f"CurveMole {version}" for item in summaries)):
            raise ValueError("Scientific examples do not match the verified stable version")
        examples = snapshot / "examples"
        examples.mkdir(exist_ok=True)
        for name in ("data.js", "results.json", *(
            key + suffix for key in EXAMPLES for suffix in (".svg", ".csv", ".fitproj", "-fit.json")
        )):
            shutil.copyfile(generated / name, examples / name)
        if generator != examples / generator.name:
            shutil.copyfile(generator, examples / generator.name)

    index = snapshot / "index.html"
    updated, count = re.subn(
        r'(<p class="example-provenance">Fitting engine: CurveMole )\d+\.\d+\.\d+',
        rf"\g<1>{version}", index.read_text(encoding="utf-8"),
    )
    if count != 1:
        raise ValueError("Expected one fitting engine version label on the homepage")
    index.write_text(updated, encoding="utf-8")
    manifest = {"version": version, "source_sha": metadata["source_sha"],
                "screenshots_sha256": sha256, "scientific_examples": list(EXAMPLES)}
    (target_assets / "showcase-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    args = parser.parse_args()
    refresh(args.snapshot.resolve(), args.checkout.resolve())
