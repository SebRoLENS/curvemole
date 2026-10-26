"""Link published beta releases to their exact Zenodo archives; never write a branch."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import sync_zenodo_doi as zenodo

BETA_RE = re.compile(r"(\d+\.\d+\.\d+)(?:-beta\.|b)([1-9]\d*)")


def beta_tag(value: str) -> str:
    match = BETA_RE.fullmatch(value.removeprefix("v"))
    if not match:
        raise ValueError("Expected a beta version, such as 1.0.2-beta.8 or 1.0.2b8")
    return f"v{match[1]}-beta.{match[2]}"


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True).strip()


def published_beta(release: dict) -> bool:
    try:
        canonical = beta_tag(release["tag_name"])
    except (KeyError, ValueError):
        return False
    return (release["tag_name"] == canonical and release.get("prerelease") is True
            and release.get("draft") is False)


def find_beta_doi(tag: str, repository: str) -> str | None:
    tag = beta_tag(tag)
    version = tag[1:]
    pep440 = version.replace("-beta.", "b")
    allowed_urls = {
        f"https://github.com/{repository}/tree/{tag}".lower(),
        f"https://github.com/{repository}/releases/tag/{tag}".lower(),
    }
    candidates = []
    # Exact version queries also find older archives hidden by Zenodo's default
    # latest-version grouping. Never reuse a stable DOI or a similarly named fork.
    for query in (f"metadata.version:{tag}", f"metadata.version:{version}",
                  f"metadata.version:{pep440}"):
        for record in zenodo.zenodo_records(query, all_versions=True):
            metadata = record.get("metadata") or {}
            if str(metadata.get("title", "")).strip().lower() not in zenodo.VALID_TITLES:
                continue
            try:
                if beta_tag(str(metadata.get("version", ""))) != tag:
                    continue
            except ValueError:
                continue
            related = metadata.get("related_identifiers") or []
            if not any(str(link.get("identifier", "")).rstrip("/").lower() in allowed_urls
                       and link.get("relation") == "isSupplementTo" for link in related):
                continue
            doi = zenodo.extract_doi(record)
            if doi and re.fullmatch(r"10\.5281/zenodo\.\d+", doi):
                candidates.append((str(record.get("updated") or record.get("created") or ""), doi))
        if candidates:
            return max(candidates)[1]
    return None


def updated_body(body: str, doi: str) -> str:
    line = f"**Zenodo DOI:** https://doi.org/{doi}"
    updated, count = re.subn(r"(?m)^\*\*Zenodo DOI:\*\*.*$", line, body, count=1)
    return updated if count else body.rstrip() + "\n\n" + line + "\n"


def sync(version: str = "", *, attempts: int = 10, delay: float = 30) -> list[str]:
    repository = os.environ["GITHUB_REPOSITORY"]
    if version:
        tag = beta_tag(version)
        releases = [json.loads(gh("api", f"repos/{repository}/releases/tags/{tag}"))]
        if not published_beta(releases[0]):
            raise ValueError("The requested release is not a published beta")
    else:
        # Paginate so old pending beta archives are not hidden by recent builds.
        pages = json.loads(gh("api", "--paginate", "--slurp",
                              f"repos/{repository}/releases?per_page=100"))
        releases = [item for page in pages for item in page if published_beta(item)]
    pending = list(releases)
    for attempt in range(attempts):
        remaining = []
        for release in pending:
            tag = release["tag_name"]
            try:
                doi = find_beta_doi(tag, repository)
            except RuntimeError as exc:
                print(f"::warning::Zenodo lookup for {tag}: {exc}")
                doi = None
            if not doi:
                remaining.append(release)
                continue
            # Re-read immediately before writing: retain edits made while Zenodo
            # was processing, and verify the release is still a published beta.
            current = json.loads(gh("api", f"repos/{repository}/releases/tags/{tag}"))
            if not published_beta(current) or current["tag_name"] != tag:
                raise ValueError("Release changed while synchronising its beta DOI")
            body = current.get("body") or ""
            updated = updated_body(body, doi)
            if updated != body:
                with tempfile.TemporaryDirectory(prefix="beta-doi-") as directory:
                    path = Path(directory) / "notes.md"
                    path.write_text(updated, encoding="utf-8")
                    subprocess.run(["gh", "release", "edit", tag, "--repo", repository,
                                    "--notes-file", str(path)], check=True)
            print(f"{tag}: https://doi.org/{doi}")
        pending = remaining
        if not pending:
            break
        if attempt + 1 < attempts:
            time.sleep(delay)
    tags = [release["tag_name"] for release in pending]
    if tags:
        print("::warning::Zenodo archival still pending for " + ", ".join(tags)
              + ". Retry Sync Zenodo DOI with channel=beta and the testing branch.")
    return tags


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="")
    parser.add_argument("--attempts", type=int, default=10)
    parser.add_argument("--delay", type=float, default=30)
    args = parser.parse_args()
    if args.attempts < 1 or args.attempts > 10 or args.delay < 0 or args.delay > 30:
        parser.error("Expected 1–10 attempts and a delay of 0–30 seconds")
    pending = sync(args.version, attempts=args.attempts, delay=args.delay)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write("## Beta Zenodo DOI\n\n")
            stream.write("Awaiting Zenodo: " + ", ".join(pending) + "\n" if pending else
                         "All requested published betas have their verified version DOI.\n")


if __name__ == "__main__":
    main()
