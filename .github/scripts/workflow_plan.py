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
    ".github/scripts/install_document_toolchain.sh",
)
SCREENSHOT_PATHS = (
    "src/curvemole/gui/", "src/curvemole/resources/", "scripts/generate_screenshots.py",
    ".github/workflows/screenshots.yml",
)
PLUGIN_PATHS = (
    "custom_plugins/", "src/curvemole/core/", "src/curvemole/__init__.py",
    "pyproject.toml", "uv.lock", "scripts/validate_community_plugins.py",
    "src/curvemole/plugin_fingerprint.py",
    ".github/workflows/community-plugins.yml",
)
# Plugin folders that the application's own test suite does not read. The TSV
# exporter is excluded: tests/test_startup_imports.py benchmarks it.
PLUGIN_ONLY_PATHS = ("custom_plugins/by_community/", "custom_plugins/by_main_developer/")


def touches(paths: list[str], patterns: tuple[str, ...]) -> bool:
    return any(path.startswith(pattern) if pattern.endswith("/") else path == pattern
               for path in paths for pattern in patterns)


def plugins_only(paths: list[str]) -> bool:
    """True when a change touches only plugin folders, so source tests cannot change."""
    return bool(paths) and all(touches([path], PLUGIN_ONLY_PATHS) for path in paths)


def plan(paths: list[str], event: str, message: str, actor: str) -> dict[str, bool]:
    push = event == "push" and actor != "github-actions[bot]"
    release = push and "[skip release]" not in message and touches(paths, RELEASE_PATHS)
    screenshots = not release and touches(paths, SCREENSHOT_PATHS)
    return {
        "release": release,
        "documentation": not release and (screenshots or touches(paths, DOCUMENT_PATHS)),
        "screenshots": screenshots,
        "plugins": touches(paths, PLUGIN_PATHS),
        "candidate": push and "[skip release]" in message and touches(paths, RELEASE_PATHS),
        "plugins_only": plugins_only(paths),
    }


def community_plugin_authors(revision: str) -> dict[str, str]:
    filenames = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", "-z", revision, "--", "custom_plugins/by_community/"],
        text=True,
    ).split("\0")
    authors = {}
    for filename in filenames:
        if len(filename.split("/")) == 4 and filename.endswith(".curvemole-plugin.json"):
            manifest = json.loads(subprocess.check_output(["git", "show", f"{revision}:{filename}"], text=True))
            authors[manifest["identifier"]] = manifest["author"]
    return authors


def check_plugin_submission(paths: list[str], event: dict, before: str, after: str) -> None:
    if not touches(paths, ("custom_plugins/",)):
        return
    submitter = event["pull_request"]["user"]
    if submitter["id"] == event["repository"]["owner"]["id"]:
        return

    if touches(paths, ("custom_plugins/by_main_developer/",)):
        raise SystemExit(
            "Only the repository owner can change plugins in custom_plugins/by_main_developer/. "
            "Submit community plugins under custom_plugins/by_community/<plugin_name>/."
        )

    if not any(path.startswith("custom_plugins/by_community/") and path.endswith(".curvemole-plugin.json")
               for path in paths):
        return

    existing = community_plugin_authors(before)
    login = submitter["login"]
    for identifier, author in community_plugin_authors(after).items():
        if identifier in existing:
            if author != existing[identifier]:
                raise SystemExit(f"{identifier}: preserve the existing plugin author ({existing[identifier]}).")
        elif not isinstance(author, str) or author.strip().removeprefix("@").casefold() != login.casefold():
            raise SystemExit(f"{identifier}: set the manifest author to your GitHub username ({login}).")


def merge_base_parent(merge_sha: str) -> str:
    """First parent of a pull request's test merge commit: the base tip it was built on.

    The event's ``pull_request.base.sha`` can predate later pushes to the base
    branch, so diffing against it would count those pushes as part of the PR.
    """
    subprocess.run(["git", "fetch", "--no-tags", "--depth=2", "origin", merge_sha], check=True)
    return subprocess.check_output(["git", "rev-parse", f"{merge_sha}^1"], text=True).strip()


def main() -> None:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    name = os.environ["GITHUB_EVENT_NAME"]
    after = os.environ["GITHUB_SHA"]
    before = merge_base_parent(after) if name == "pull_request" else event.get("before")
    if not before or set(before) == {"0"}:
        command = ["git", "ls-files", "-z"]
    else:
        if name != "pull_request":
            subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", before], check=True)
        command = ["git", "diff", "--name-only", "--no-renames", "-z", before, after]
    paths = [path for path in subprocess.check_output(command, text=True).split("\0") if path]
    if name == "pull_request":
        check_plugin_submission(paths, event, before, after)
    result = plan(paths, name, (event.get("head_commit") or {}).get("message", ""),
                  os.environ["GITHUB_ACTOR"])
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        for key, value in result.items():
            output.write(f"{key}={str(value).lower()}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
