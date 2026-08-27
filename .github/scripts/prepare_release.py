#!/usr/bin/env python3
"""Synchronise CurveMole version and citation metadata for a release."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = ROOT / "src" / "curvemole" / "version.py"
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"
MANUAL = ROOT / "docs" / "manual.md"
CITATION = ROOT / "CITATION.cff"

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
VERSION_RE = re.compile(r'^__version__\s*=\s*"(\d+\.\d+\.\d+)"', re.M)
PYPROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"\d+\.\d+\.\d+"', re.M)
MANUAL_VERSION_RE = re.compile(
    r"^\*\*Current manual version:\s*\d+\.\d+\.\d+\*\*$", re.M
)
MANUAL_TITLE_RE = re.compile(
    r"^# CurveMole User Manual (?:-|–|—) Preview (\d+\.\d+\.\d+)$", re.M
)
STATUS_RE = re.compile(
    r"> \*\*Status:\*\* Version \*\*\d+\.\d+\.\d+ Preview\*\*\."
)
PUBLIC_VERSION_RE = re.compile(
    r"^Current public version: \*\*\d+\.\d+\.\d+\*\*$", re.M
)
VERSION_BADGE_RE = re.compile(
    r"^\[!\[(?:Latest release|Version)\]\([^)]+\)\]\([^)]+\)[ \t]*$", re.M
)
DOI_BADGE_RE = re.compile(r"^\[!\[DOI\]\([^)]+\)\]\([^)]+\)[ \t]*$", re.M)

VERSION_BADGE = (
    "[![Version](https://img.shields.io/github/v/release/SebRoLENS/curvemole)]"
    "(https://github.com/SebRoLENS/curvemole/releases/latest)"
)
DOI_PENDING_BADGE = (
    "[![DOI](https://img.shields.io/badge/DOI-pending-lightgrey)]"
    "(https://github.com/SebRoLENS/curvemole/releases/latest)"
)


def version_tuple(version: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(version)
    if not match:
        raise SystemExit(f"Unsupported version format: {version}")
    return tuple(map(int, match.groups()))


def read_current_version() -> str:
    match = VERSION_RE.search(VERSION_FILE.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("Could not find __version__ in src/curvemole/version.py")
    return match.group(1)


def released_versions() -> list[str]:
    process = subprocess.run(
        ["git", "tag", "--list", "v*"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode:
        return []
    return [tag[1:] for tag in process.stdout.splitlines() if SEMVER_RE.fullmatch(tag[1:])]


def last_commit_message() -> str:
    process = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return process.stdout if process.returncode == 0 else ""


def requested_bump(explicit: str | None) -> str:
    if explicit in {"patch", "minor", "major"}:
        return explicit
    message = last_commit_message().lower()
    if "[major]" in message:
        return "major"
    if "[minor]" in message:
        return "minor"
    return "patch"


def bump_version(version: str, part: str) -> str:
    major, minor, patch = version_tuple(version)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def choose_version(explicit_bump: str | None = None) -> str:
    current = read_current_version()
    releases = released_versions()
    if not releases:
        return current
    latest = max(releases, key=version_tuple)
    current_tuple = version_tuple(current)
    latest_tuple = version_tuple(latest)
    if current_tuple > latest_tuple:
        return current
    if current_tuple < latest_tuple:
        raise SystemExit(
            f"Source version {current} is older than latest release v{latest}."
        )
    return bump_version(current, requested_bump(explicit_bump))


def replace_section(text: str, heading: str, next_heading: str, body: str) -> str:
    pattern = re.compile(
        rf"(?ms)^{re.escape(heading)}\n.*?(?=^{re.escape(next_heading)}\n)"
    )
    if not pattern.search(text):
        raise SystemExit(f"Could not find README section {heading!r}")
    return pattern.sub(body.rstrip() + "\n\n", text, count=1)


def pending_badges(text: str) -> str:
    if not VERSION_BADGE_RE.search(text):
        raise SystemExit("Could not find the README version badge")
    text = VERSION_BADGE_RE.sub(VERSION_BADGE, text, count=1)
    if DOI_BADGE_RE.search(text):
        return DOI_BADGE_RE.sub(DOI_PENDING_BADGE, text, count=1)
    return text.replace(VERSION_BADGE, VERSION_BADGE + "\n" + DOI_PENDING_BADGE, 1)


def update_readme(version: str) -> None:
    text = README.read_text(encoding="utf-8")
    text = pending_badges(text)
    text, status_count = STATUS_RE.subn(
        f"> **Status:** Version **{version} Preview**.", text, count=1
    )
    text, public_count = PUBLIC_VERSION_RE.subn(
        f"Current public version: **{version}**", text, count=1
    )
    if status_count != 1 or public_count != 1:
        raise SystemExit("Could not update README version fields")
    citation = f"""## How to cite

If CurveMole contributes to published research, please cite the exact version used.
GitHub also provides a **Cite this repository** entry from [`CITATION.cff`](CITATION.cff).

Version **{version}** will be archived on Zenodo after its GitHub integration is enabled.
The release DOI will then be inserted here automatically.

> Romi, S. (2026). *CurveMole: Modular Scientific Curve Fitting* (Version {version})
> [Computer software]. GitHub. https://github.com/SebRoLENS/curvemole/releases/tag/v{version}
"""
    text = replace_section(text, "## How to cite", "## License", citation)
    README.write_text(text, encoding="utf-8")


def update_manual(version: str) -> None:
    text = MANUAL.read_text(encoding="utf-8")
    title_match = MANUAL_TITLE_RE.search(text)
    if not title_match:
        raise SystemExit("Could not find the manual title version")
    previous_version = title_match.group(1)
    if previous_version != version:
        text = text.replace(previous_version, version)
        citation = f"""### 20.3 Citation

If CurveMole contributes to published work, cite the exact version used. The release
DOI is inserted into `CITATION.cff` and the repository README after Zenodo archival.
Until archival completes, the versioned GitHub release is the authoritative record:

> Romi, S. (2026). *CurveMole: Modular Scientific Curve Fitting* (Version {version})
> [Computer software]. GitHub.
> https://github.com/SebRoLENS/curvemole/releases/tag/v{version}

The repository provides **Cite this repository** from `CITATION.cff`.
"""
        text = replace_section(text, "### 20.3 Citation", "### 20.4 Author and contact", citation)
    text = MANUAL_TITLE_RE.sub(
        f"# CurveMole User Manual - Preview {version}",
        text,
        count=1,
    )
    replacement = f"**Current manual version: {version}**"
    if MANUAL_VERSION_RE.search(text):
        text = MANUAL_VERSION_RE.sub(replacement, text, count=1)
    else:
        text = text.replace("\n", "\n\n" + replacement + "\n", 1)
    MANUAL.write_text(text, encoding="utf-8")


def update_citation(version: str) -> None:
    text = CITATION.read_text(encoding="utf-8")
    text = re.sub(r"^doi:\s*.*\n", "", text, flags=re.M)
    text = re.sub(r'^version:\s*.*$', f'version: "{version}"', text, flags=re.M)
    text = re.sub(
        r"^date-released:\s*.*$",
        f"date-released: {dt.date.today().isoformat()}",
        text,
        flags=re.M,
    )
    text = re.sub(
        r'^url:\s*.*$',
        f'url: "https://github.com/SebRoLENS/curvemole/releases/tag/v{version}"',
        text,
        flags=re.M,
    )
    CITATION.write_text(text, encoding="utf-8")


def apply_version(version: str) -> None:
    source = VERSION_FILE.read_text(encoding="utf-8")
    source = VERSION_RE.sub(f'__version__ = "{version}"', source, count=1)
    VERSION_FILE.write_text(source, encoding="utf-8")

    project = PYPROJECT.read_text(encoding="utf-8")
    project, count = PYPROJECT_VERSION_RE.subn(f'version = "{version}"', project, count=1)
    if count != 1:
        raise SystemExit("Could not update pyproject.toml version")
    PYPROJECT.write_text(project, encoding="utf-8")

    update_readme(version)
    update_manual(version)
    update_citation(version)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bump", choices=["patch", "minor", "major"])
    parser.add_argument("--version-only", action="store_true")
    args = parser.parse_args()

    version = choose_version(args.bump)
    if not args.version_only:
        apply_version(version)
    print(version)


if __name__ == "__main__":
    main()
