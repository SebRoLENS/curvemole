"""Promote a validated testing snapshot without rewriting either branch's history."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path
from runpy import run_path


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def ancestor(older: str, newer: str) -> bool:
    result = subprocess.run(["git", "merge-base", "--is-ancestor", older, newer])
    if result.returncode not in (0, 1):
        raise RuntimeError("Could not check branch ancestry")
    return result.returncode == 0


def refresh() -> None:
    subprocess.run(["git", "fetch", "--no-tags", "origin", "main", "testing"], check=True)


def sha(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("An exact commit SHA is required")
    return git("rev-parse", f"{value}^{{commit}}")


def output(**values: str) -> None:
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
        for name, value in values.items():
            if "\n" in value:
                raise ValueError("Invalid workflow output")
            stream.write(f"{name}={value}\n")


def previous_preparation(run_id: str, source: str) -> str | None:
    previous = run_path(str(Path(__file__).with_name("release_state.py")))["previous_release"]
    result = previous(run_id, source)
    return result[0] if result else None


def snapshot(source: str, run_id: str, bump: str, version: str) -> None:
    source = sha(source)
    refresh()
    current_main = git("rev-parse", "origin/main")
    prepared = previous_preparation(run_id, source)
    if prepared and ancestor(prepared, current_main):
        # A rerun must resume this run's existing release, never promote newer work.
        output(main_sha=current_main, source_sha=source)
        return
    if current_main != source:
        if git("rev-parse", "origin/testing") != source:
            raise ValueError("testing advanced: start a new promotion to validate its current version")
        if not ancestor(current_main, source):
            raise ValueError("Merge main into testing and resolve conflicts before promoting; no branch was changed")
    # Reject invalid/existing versions before touching main.
    prepare = run_path(str(Path(__file__).with_name("prepare_release.py")))
    prepare["choose_version"](bump, version or None)
    output(main_sha=current_main, source_sha=source)


def promote(source: str, expected_main: str, run_id: str) -> None:
    source, expected_main = sha(source), sha(expected_main)
    refresh()
    current_main = git("rev-parse", "origin/main")
    prepared = previous_preparation(run_id, source)
    if current_main == source or (prepared and ancestor(prepared, current_main)):
        print("This snapshot was already promoted; continuing the same release run.")
        return
    if current_main != expected_main:
        raise ValueError("main changed during validation; restart promotion without overwriting it")
    if git("rev-parse", "origin/testing") != source:
        raise ValueError("testing changed during validation; restart promotion to validate the new snapshot")
    if not ancestor(current_main, source):
        raise ValueError("Promotion must be a fast-forward; merge main into testing first")
    # A normal fast-forward push is also rejected if main advances after this check.
    subprocess.run(["git", "push", "origin", f"{source}:refs/heads/main"], check=True)


def sync_testing(released: str) -> None:
    released = sha(released)
    refresh()
    if not ancestor(released, "origin/main"):
        raise ValueError("The release commit is no longer part of main")
    subprocess.run(["git", "checkout", "--detach", "origin/testing"], check=True)
    if ancestor(released, "HEAD"):
        print("testing already contains the released version metadata.")
        return
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "config", "user.email",
                    "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
    # Include any metadata-only DOI updates already on main, but no later app work.
    generated = run_path(str(Path(__file__).with_name("release_state.py")))["FILES"]
    target = released
    commits = git("rev-list", f"{released}..origin/main").splitlines()
    if all(
        git("show", "-s", "--format=%ae", commit) == "41898282+github-actions[bot]@users.noreply.github.com"
        and all(path in generated or path.startswith("docs/screenshots/")
                for path in git("diff-tree", "--no-commit-id", "--name-only", "-r", commit).splitlines())
        for commit in commits
    ):
        target = git("rev-parse", "origin/main")
    result = subprocess.run(["git", "merge", "--no-edit", target, "-m",
                             "Sync released stable metadata into testing [beta artifacts only]"])
    if result.returncode:
        subprocess.run(["git", "merge", "--abort"], check=True)
        raise ValueError("Stable was published, but testing has merge conflicts; resolve them on testing")
    subprocess.run(["git", "push", "origin", "HEAD:refs/heads/testing"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["snapshot", "promote", "sync"])
    parser.add_argument("--source", default=os.environ.get("PROMOTION_SOURCE", ""))
    parser.add_argument("--expected-main", default=os.environ.get("PROMOTION_MAIN", ""))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--bump", choices=["patch", "minor", "major"], default=os.environ.get("REQUESTED_BUMP", "patch"))
    parser.add_argument("--version", default=os.environ.get("REQUESTED_VERSION", ""))
    args = parser.parse_args()
    if args.command == "snapshot":
        snapshot(args.source, args.run_id, args.bump, args.version)
    elif args.command == "promote":
        promote(args.source, args.expected_main, args.run_id)
    else:
        sync_testing(args.source)


if __name__ == "__main__":
    main()
