"""Keep a release's version and source stable across full workflow reruns."""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import tarfile
from pathlib import Path

FILES = (
    "src/curvemole/version.py", "pyproject.toml", "uv.lock", "README.md", "CITATION.cff", "CHANGELOG.md",
    "docs/manual.md", "docs/CurveMole_User_Manual.tex", "docs/CurveMole_User_Manual.pdf",
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def output(**values: str) -> None:
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        for key, value in values.items():
            if "\n" in value:
                raise ValueError("Invalid workflow output")
            stream.write(f"{key}={value}\n")


def previous_release(run_id: str, source: str) -> tuple[str, str] | None:
    if not run_id.isdecimal():
        raise ValueError("Invalid release run identity")
    commits = git("log", "--all", "--format=%H", "--fixed-strings",
                  f"--grep=Release-Run: {run_id}").splitlines()
    matches = []
    for commit in commits:
        body = git("show", "-s", "--format=%B", commit)
        if f"Release-Run: {run_id}" not in body.splitlines():
            continue
        if f"Release-Source: {source}" not in body.splitlines():
            raise ValueError("Release run belongs to a different source commit")
        if git("rev-parse", f"{commit}^") != source:
            raise ValueError("Release metadata has an unexpected parent")
        version = re.search(r'^__version__ = "(\d+\.\d+\.\d+)"',
                            git("show", f"{commit}:src/curvemole/version.py"), re.M)
        if not version:
            raise ValueError("Release metadata has no valid version")
        matches.append((commit, version.group(1)))
    if len(matches) > 1:
        raise ValueError("Multiple commits claim the same release run")
    return matches[0] if matches else None


def plan(args: argparse.Namespace) -> None:
    source = git("rev-parse", "HEAD")
    previous = previous_release(args.run_id, source)
    if previous:
        output(active="true", source_sha=source, commit_sha=previous[0], version=previous[1])
        return
    if source != git("rev-parse", "origin/main"):
        print("Source was superseded before preparation; leave work to the newer main run.")
        output(active="false", source_sha=source, commit_sha="", version="")
        return
    spec = importlib.util.spec_from_file_location("prepare_release", ".github/scripts/prepare_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    exact = args.version or None
    requested = re.search(r"\[release\s+(\d+\.\d+\.\d+)\]", args.message)
    if not exact and requested:
        exact = requested.group(1)
    bump = args.bump or ("major" if "[major]" in args.message else
                         "minor" if "[minor]" in args.message else "patch")
    version = module.choose_version(bump, exact)
    output(active="true", source_sha=source, commit_sha="", version=version)


def commit(args: argparse.Namespace) -> None:
    source = git("rev-parse", "HEAD")
    previous = previous_release(args.run_id, source)
    if previous:
        if previous[1] != args.version:
            raise ValueError("Saved release version differs from the requested version")
        output(commit_sha=previous[0])
        return
    subprocess.run(["git", "fetch", "origin", "main"], check=True)
    if source != git("rev-parse", "origin/main"):
        raise ValueError("main advanced during preparation; refusing to publish stale metadata")
    with tarfile.open("prepared-release.tar.gz") as archive:
        for item in archive.getmembers():
            allowed = item.name in FILES or (
                item.name.startswith("docs/screenshots/") and item.name.endswith(".png")
                and ".." not in Path(item.name).parts)
            if not item.isfile() or not allowed:
                raise ValueError(f"Unexpected prepared release file: {item.name}")
        archive.extractall(filter="data")
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "config", "user.email",
                    "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
    subprocess.run(["git", "add", *FILES, "docs/screenshots"], check=True)
    message = (f"Prepare v{args.version} release [skip release]\n\n"
               f"Release-Run: {args.run_id}\nRelease-Source: {source}")
    # A corrected source may already carry this unpublished version's generated
    # files. Still record the new run identity so retries select this source.
    subprocess.run(["git", "commit", "--allow-empty", "-m", message], check=True)
    subprocess.run(["git", "push", "origin", "HEAD:main"], check=True)
    output(commit_sha=git("rev-parse", "HEAD"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["plan", "pack", "commit"])
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--version", default="")
    parser.add_argument("--bump", default="")
    parser.add_argument("--message", default="")
    args = parser.parse_args()
    if args.command == "plan":
        plan(args)
    elif args.command == "commit":
        commit(args)
    else:
        with tarfile.open("prepared-release.tar.gz", "w:gz") as archive:
            for name in [*FILES, *map(str, sorted(Path("docs/screenshots").glob("*.png")))]:
                archive.add(name, arcname=name)


if __name__ == "__main__":
    main()
