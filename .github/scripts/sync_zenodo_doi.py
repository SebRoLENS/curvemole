#!/usr/bin/env python3
"""Find a CurveMole release DOI on Zenodo and synchronise repository metadata."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = ROOT / "src" / "curvemole" / "version.py"
README = ROOT / "README.md"
CITATION = ROOT / "CITATION.cff"

VERSION_RE = re.compile(r'^__version__\s*=\s*"(\d+\.\d+\.\d+)"', re.M)
VERSION_BADGE_RE = re.compile(
    r'^(?:\[!\[(?:Latest release|Version)\]\([^)]+\)\]\([^)]+\)|'
    r'[ \t]*<a href="https://github\.com/SebRoLENS/curvemole/releases/latest">'
    r'<img src="https://img\.shields\.io/github/v/release/SebRoLENS/curvemole" '
    r'alt="Version"></a>)[ \t]*$',
    re.M,
)
DOI_BADGE_RE = re.compile(
    r'^(?:\[!\[DOI\]\([^)]+\)\]\([^)]+\)|'
    r'[ \t]*<a href="[^"]+"><img src="[^"]+" alt="DOI"></a>)[ \t]*$',
    re.M,
)
VERSION_BADGE = (
    '  <a href="https://github.com/SebRoLENS/curvemole/releases/latest">'
    '<img src="https://img.shields.io/github/v/release/SebRoLENS/curvemole" '
    'alt="Version"></a>'
)
VALID_TITLES = {"curvemole", "curvemole: modular scientific curve fitting"}


def current_version() -> str:
    match = VERSION_RE.search(VERSION_FILE.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("Could not find __version__")
    return match.group(1)


def version_matches(value: object, wanted: str) -> bool:
    text = str(value or "").strip()
    return text in {wanted, f"v{wanted}"}


def extract_doi(record: dict) -> str | None:
    pids = record.get("pids") or {}
    doi = pids.get("doi") if isinstance(pids, dict) else None
    if isinstance(doi, dict) and doi.get("identifier"):
        return str(doi["identifier"])
    if isinstance(doi, str):
        return doi
    if record.get("doi"):
        return str(record["doi"])
    metadata = record.get("metadata") or {}
    return str(metadata["doi"]) if metadata.get("doi") else None


def zenodo_records(query: str) -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "size": 25})
    request = urllib.request.Request(
        f"https://zenodo.org/api/records?{params}",
        headers={"Accept": "application/json", "User-Agent": "curvemole-release-bot/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()
        raise RuntimeError(f"Zenodo API returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Zenodo API request failed: {exc}") from exc
    return ((payload.get("hits") or {}).get("hits") or [])


def find_doi(version: str) -> str | None:
    candidates: list[dict] = []
    seen: set[str] = set()
    last_error: RuntimeError | None = None
    for query in ('"CurveMole"', f'"CurveMole" AND "{version}"', version):
        try:
            records = zenodo_records(query)
        except RuntimeError as exc:
            last_error = exc
            continue
        for record in records:
            identifier = str(record.get("id") or "")
            if identifier and identifier in seen:
                continue
            seen.add(identifier)
            metadata = record.get("metadata") or {}
            if str(metadata.get("title", "")).strip().lower() not in VALID_TITLES:
                continue
            if version_matches(metadata.get("version"), version) and extract_doi(record):
                candidates.append(record)
    if not candidates:
        if last_error is not None:
            raise last_error
        return None
    candidates.sort(
        key=lambda record: str(record.get("updated") or record.get("created") or ""),
        reverse=True,
    )
    return extract_doi(candidates[0])


def replace_section(text: str, heading: str, next_heading: str, body: str) -> str:
    pattern = re.compile(
        rf"(?ms)^{re.escape(heading)}\n.*?(?=^{re.escape(next_heading)}\n)"
    )
    if not pattern.search(text):
        raise SystemExit(f"Could not find README section {heading!r}")
    return pattern.sub(body.rstrip() + "\n\n", text, count=1)


def apply_metadata(version: str, doi: str) -> None:
    doi_url = f"https://doi.org/{doi}"
    doi_badge = (
        f'  <a href="{doi_url}"><img src="https://zenodo.org/badge/DOI/{doi}.svg" '
        'alt="DOI"></a>'
    )

    readme = README.read_text(encoding="utf-8")
    if not VERSION_BADGE_RE.search(readme):
        raise SystemExit("Could not find README version badge")
    readme = VERSION_BADGE_RE.sub(VERSION_BADGE, readme, count=1)
    if DOI_BADGE_RE.search(readme):
        readme = DOI_BADGE_RE.sub(doi_badge, readme, count=1)
    else:
        readme = readme.replace(VERSION_BADGE, VERSION_BADGE + "\n" + doi_badge, 1)
    citation = f"""## How to cite

If CurveMole contributes to published research, please cite the exact version used.
GitHub also provides a **Cite this repository** entry from [`CITATION.cff`](CITATION.cff).

> Romi, S. (2026). *CurveMole: Modular Scientific Curve Fitting* (Version {version})
> [Computer software]. Zenodo. {doi_url}

DOI: [**{doi}**]({doi_url})
"""
    README.write_text(
        replace_section(readme, "## How to cite", "## License", citation),
        encoding="utf-8",
    )

    cff = CITATION.read_text(encoding="utf-8")
    cff = re.sub(r"^doi:\s*.*\n", "", cff, flags=re.M)
    cff = re.sub(r'^version:\s*.*$', f'version: "{version}"', cff, flags=re.M)
    cff = re.sub(r'^url:\s*.*$', f'url: "{doi_url}"', cff, flags=re.M)
    lines = cff.splitlines()
    repository_index = next(
        (index + 1 for index, line in enumerate(lines) if line.startswith("repository-code:")),
        None,
    )
    if repository_index is None:
        raise SystemExit("Could not find repository-code in CITATION.cff")
    lines.insert(repository_index, f'doi: "{doi}"')
    CITATION.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    version = args.version or current_version()
    try:
        doi = find_doi(version)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(3) from exc
    if not doi:
        print(f"Zenodo DOI for v{version} not found yet.", file=sys.stderr)
        raise SystemExit(2)
    if args.apply:
        apply_metadata(version, doi)
    print(doi)


if __name__ == "__main__":
    main()
