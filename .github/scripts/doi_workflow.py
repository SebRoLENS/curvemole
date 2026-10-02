"""Discover only missing DOI metadata; write it separately under the main lock."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

import sync_zenodo_doi as zenodo


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True).strip()


def body_doi(body: str) -> str | None:
    match = re.search(r"(?m)^\*\*Zenodo DOI:\*\* https://doi.org/(10\.5281/zenodo\.\d+)\s*$", body)
    return match.group(1) if match else None


def updated_body(body: str, doi: str) -> str:
    line = f"**Zenodo DOI:** https://doi.org/{doi}"
    updated, count = re.subn(r"(?m)^\*\*Zenodo DOI:\*\*.*$", line, body, count=1)
    return updated if count else body.rstrip() + "\n\n" + line + "\n"


def metadata_complete(version: str, doi: str) -> bool:
    return (version != zenodo.current_version() or
            (f'doi: "{doi}"' in zenodo.CITATION.read_text()
             and f"https://doi.org/{doi}" in zenodo.README.read_text()
             and f"DOI: [**{doi}**]" in zenodo.README.read_text()))


def discover(version: str) -> list[dict]:
    repository = os.environ["GITHUB_REPOSITORY"]
    if version:
        version = version.removeprefix("v")
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError("Invalid requested DOI version")
        releases = [json.loads(gh("api", f"repos/{repository}/releases/tags/v{version}"))]
    else:
        releases = json.loads(gh("api", f"repos/{repository}/releases?per_page=20"))
    results = []
    regular = [r for r in releases if not r["draft"] and not r["prerelease"]
               and re.fullmatch(r"v\d+\.\d+\.\d+", r["tag_name"])][:10]
    for item in regular:
        target = item["tag_name"][1:]
        doi = body_doi(item["body"] or "")
        if doi and metadata_complete(target, doi):
            continue
        attempts = 3 if version and not doi else 1
        for attempt in range(attempts):
            if doi:
                break
            try:
                doi = zenodo.find_doi(target)
            except RuntimeError as exc:
                print(f"::warning::DOI lookup for v{target}: {exc}")
            if not doi and attempt + 1 < attempts:
                time.sleep((5, 15)[attempt])
        if doi:
            if not re.fullmatch(r"10\.5281/zenodo\.\d+", doi):
                raise ValueError("Zenodo returned an invalid DOI")
            results.append({"version": target, "doi": doi})
        else:
            print(f"DOI for v{target} pending; the hourly schedule will retry.")
    return results


def apply(path: Path) -> None:
    findings = json.loads(path.read_text())
    for item in findings:
        version, doi = item["version"], item["doi"]
        if not re.fullmatch(r"\d+\.\d+\.\d+", version) or not re.fullmatch(r"10\.5281/zenodo\.\d+", doi):
            raise ValueError("Invalid discovered DOI metadata")
        if version == zenodo.current_version() and not metadata_complete(version, doi):
            zenodo.apply_metadata(version, doi)
    if subprocess.run(["git", "diff", "--quiet", "--", "README.md", "CITATION.cff"]).returncode:
        subprocess.run(["git", "fetch", "origin", "main"], check=True)
        if gh_git("rev-parse", "HEAD") != gh_git("rev-parse", "origin/main"):
            raise ValueError("main advanced while applying DOI; refusing a stale write")
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "user.email",
                        "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "add", "README.md", "CITATION.cff"], check=True)
        subprocess.run(["git", "commit", "-m", "Update missing Zenodo metadata [skip release]"], check=True)
        subprocess.run(["git", "push", "origin", "HEAD:main"], check=True)
    for item in findings:
        tag, doi = "v" + item["version"], item["doi"]
        body = gh("release", "view", tag, "--json", "body", "--jq", ".body")
        updated = updated_body(body, doi)
        if updated == body:
            continue
        Path("doi-release-notes.md").write_text(updated)
        subprocess.run(["gh", "release", "edit", tag, "--notes-file", "doi-release-notes.md"], check=True)


def gh_git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["discover", "apply"])
    parser.add_argument("--version", default="")
    parser.add_argument("--file", type=Path, default=Path("discovered-dois.json"))
    args = parser.parse_args()
    if args.command == "apply":
        apply(args.file)
        return
    findings = discover(args.version)
    args.file.write_text(json.dumps(findings))
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.write(f"found={str(bool(findings)).lower()}\n")


if __name__ == "__main__":
    main()
