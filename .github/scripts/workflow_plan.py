"""Choose work once for a push/PR, before starting expensive reusable jobs."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

RELEASE_PATHS = (
    "src/", "packaging/", "scripts/build_desktop.py", "scripts/build_manual.py",
    "docs/manual-preamble.tex", ".github/workflows/build-desktop.yml",
    ".github/workflows/automatic-release.yml", ".github/scripts/prepare_release.py",
    ".github/scripts/release_state.py", ".github/scripts/release_assets.py",
    "pyproject.toml", "uv.lock", ".release-trigger",
)
DOCUMENT_PATHS = (
    "docs/manual.md", "docs/manual-preamble.tex", "docs/screenshots/",
    "src/curvemole/resources/curvemole.png", "scripts/build_manual.py",
    "src/curvemole/version.py", ".github/workflows/documentation.yml",
)
SCREENSHOT_PATHS = (
    "src/curvemole/gui/", "src/curvemole/resources/", "scripts/generate_screenshots.py",
    ".github/workflows/screenshots.yml",
)
PLUGIN_PATHS = (
    "custom_plugins/", "src/curvemole/core/", "src/curvemole/__init__.py",
    "pyproject.toml", "uv.lock", "scripts/validate_community_plugins.py",
    ".github/workflows/community-plugins.yml",
)


def touches(paths: list[str], patterns: tuple[str, ...]) -> bool:
    return any(path.startswith(pattern) if pattern.endswith("/") else path == pattern
               for path in paths for pattern in patterns)


def plan(paths: list[str], event: str, message: str, actor: str) -> dict[str, bool]:
    push = event == "push" and actor != "github-actions[bot]"
    release = push and "[skip release]" not in message and touches(paths, RELEASE_PATHS)
    screenshots = push and not release and touches(paths, SCREENSHOT_PATHS)
    return {
        "release": release,
        "documentation": not release and (screenshots or touches(paths, DOCUMENT_PATHS)),
        "screenshots": screenshots,
        "plugins": touches(paths, PLUGIN_PATHS),
        "candidate": push and "[skip release]" in message and touches(paths, RELEASE_PATHS),
    }


def main() -> None:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    name = os.environ["GITHUB_EVENT_NAME"]
    before = event.get("before") if name == "push" else event["pull_request"]["base"]["sha"]
    after = os.environ["GITHUB_SHA"]
    if not before or set(before) == {"0"}:
        command = ["git", "ls-files"]
    else:
        subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", before], check=True)
        command = ["git", "diff", "--name-only", before, after]
    paths = subprocess.check_output(command, text=True).splitlines()
    result = plan(paths, name, (event.get("head_commit") or {}).get("message", ""),
                  os.environ["GITHUB_ACTOR"])
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        for key, value in result.items():
            output.write(f"{key}={str(value).lower()}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
