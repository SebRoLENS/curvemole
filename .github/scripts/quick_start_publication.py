"""Regenerate tutorial assets from the same verified stable app as the website.

News-only publication starts from tracked stable website files. Those files may
contain older generated captures, so it must render the tutorial again from a
detached stable checkout rather than use the testing app or stale PNGs.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENDERER = Path("website/scripts/render_quick_start_screenshots.py")
GENERATED = (Path("assets/quick-start"), Path("quick-start-data"))
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class GuideMarker(HTMLParser):
    enabled = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name") == "curvemole-quick-start":
            if attrs.get("content") != "raman":
                raise ValueError("Unsupported CurveMole quick-start guide")
            self.enabled = True


def guide_enabled(snapshot):
    page = snapshot / "quick-start.html"
    if not page.exists():
        return False
    content = page.read_text(encoding="utf-8")
    marker = GuideMarker()
    marker.feed(content)
    if not marker.enabled and any(str(path) + "/" in content for path in GENERATED):
        raise ValueError("Quick-start assets require the curvemole-quick-start page marker")
    return marker.enabled


def metadata_for(snapshot):
    metadata = json.loads((snapshot / "publication.json").read_text(encoding="utf-8"))
    if not re.fullmatch(r"[a-f0-9]{40}", metadata.get("source_sha", "")):
        raise ValueError("Tutorial publication needs a verified full stable source SHA")
    if not re.fullmatch(r"\d+\.\d+\.\d+", metadata.get("version", "")):
        raise ValueError("Tutorial publication needs a final stable version")
    return metadata


def check_checkout(checkout, metadata):
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout, text=True,
    ).strip()
    if source != metadata["source_sha"]:
        raise ValueError("Tutorial renderer checkout differs from the verified stable source")
    version = None
    tree = ast.parse((checkout / "src/curvemole/version.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        ):
            version = ast.literal_eval(node.value)
    if version != metadata["version"]:
        raise ValueError("Tutorial app version differs from the verified stable release")
    if not (checkout / RENDERER).is_file():
        raise ValueError("The stable quick-start guide has no matching screenshot renderer")


def prepare(snapshot, checkout):
    """Make a read-only detached app checkout only when stable has the guide."""
    if not guide_enabled(snapshot):
        return False
    metadata = metadata_for(snapshot)
    if checkout.exists():
        raise FileExistsError(f"Stable tutorial checkout already exists: {checkout}")
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(checkout), metadata["source_sha"]],
        cwd=ROOT, check=True,
    )
    check_checkout(checkout, metadata)
    return True


def verify(snapshot):
    """Reject missing, stale, or wrong-version assets before Pages upload."""
    metadata = metadata_for(snapshot)
    directory = snapshot / GENERATED[0]
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != metadata["version"]:
        raise ValueError("Tutorial captures do not match the stable app version")
    if manifest.get("source_sha") != metadata["source_sha"]:
        raise ValueError("Tutorial captures do not match the verified stable source")
    images = manifest.get("screenshots")
    if isinstance(images, dict):
        images = list(images.values())
    if not isinstance(images, list) or not images:
        raise ValueError("Tutorial manifest contains no screenshot files")
    for name in images:
        if not isinstance(name, str):
            raise ValueError("Tutorial screenshot names must be relative PNG paths")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".png":
            raise ValueError("Tutorial screenshot names must be relative PNG paths")
        path = snapshot / relative if relative.parts[:2] == ("assets", "quick-start") else directory / relative
        if not path.is_file() or path.read_bytes()[:8] != PNG_SIGNATURE:
            raise ValueError(f"Missing or invalid tutorial screenshot: {name}")
    data = snapshot / GENERATED[1]
    if not data.is_dir() or not any(path.is_file() for path in data.rglob("*")):
        raise ValueError("Missing tutorial downloadable data")
    return manifest


def refresh(snapshot, checkout):
    if not guide_enabled(snapshot):
        return False
    metadata = metadata_for(snapshot)
    check_checkout(checkout, metadata)
    # Never let an incomplete capture reuse a PNG from a previous stable release.
    for relative in GENERATED:
        target = snapshot / relative
        if target.is_symlink():
            raise ValueError("Generated tutorial directories must not be symlinks")
        if target.exists():
            shutil.rmtree(target)
    env = os.environ.copy()
    env.update(
        QT_QPA_PLATFORM="offscreen", CURVEMOLE_DISABLE_UPDATE_CHECK="1",
        PYTHONPATH=str(checkout / "src"),
        CURVEMOLE_SCREENSHOT_SOURCE_SHA=metadata["source_sha"],
    )
    subprocess.run(
        [sys.executable, str(checkout / RENDERER), "--output", str(snapshot)],
        cwd=checkout, env=env, check=True,
    )
    verify(snapshot)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "refresh", "verify"))
    parser.add_argument("--snapshot", type=Path, required=True, help="Assembled website/dist")
    parser.add_argument("--checkout", type=Path, help="Verified stable app checkout")
    args = parser.parse_args()
    snapshot = args.snapshot.resolve()
    if args.command == "verify":
        verify(snapshot)
        return
    if args.checkout is None:
        parser.error("--checkout is required for prepare and refresh")
    checkout = args.checkout.resolve()
    if args.command == "prepare":
        required = prepare(snapshot, checkout)
        if output := os.environ.get("GITHUB_OUTPUT"):
            with Path(output).open("a", encoding="utf-8") as stream:
                stream.write(f"required={str(required).lower()}\ncheckout={checkout}\n")
    else:
        refresh(snapshot, checkout)


if __name__ == "__main__":
    main()
