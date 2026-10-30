"""Deterministic changelogs from Git history; no external service or AI dependency.

`CHANGELOG.md` contains the cumulative changes since the latest stable tag.
`docs/beta-history.md` records each published, reachable beta tag. Regeneration
is idempotent; stable preparation refreshes the ledger before freezing it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHANGELOG = ROOT / "CHANGELOG.md"
HISTORY = ROOT / "docs" / "beta-history.md"
BEGIN = "<!-- BEGIN AUTOMATED CHANGES: do not edit inside this block -->"
END = "<!-- END AUTOMATED CHANGES -->"
STABLE_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)$")
BETA_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)-beta\.(\d+)$")
MARKER_RE = re.compile(r"\s*\[(?:skip release|skip ci|beta artifacts only|minor|major)\]", re.I)
SKIP_RE = re.compile(
    r"^(?:prepare v\d|start next beta cycle|sync (?:released|stable) |"
    r"update missing zenodo metadata|update development documentation|"
    r"fix (?:ruff|lint|website publication script lint)|"
    r"(?:style|test|tests|ci|build|chore):|"
    r"document synchronized project handoff and conflict policy|"
    r"exercise automatic owner release|"
    r"cover crash recovery|"
    r"remove unused handoff import|"
    r"keep project coordination imports sorted|"
    r"publish corrected shared-project locking beta validation|"
    r"refresh cumulative beta changelog|"
    r"(?:add deterministic beta|generate each beta release|freeze full beta-cycle changelog|"
    r"automatically commit cumulative changes|fetch full tag history for complete stable changelog|"
    r"include first-time beta history file))",
    re.I,
)
ORDER = ("Added", "Changed", "Fixed", "Documentation")


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def is_ancestor(tag: str, commit: str) -> bool:
    status = subprocess.run(
        ["git", "merge-base", "--is-ancestor", tag, commit], cwd=ROOT,
        capture_output=True, check=False,
    )
    if status.returncode not in (0, 1):
        raise RuntimeError("Unable to check Git ancestry")
    return status.returncode == 0


def tags() -> list[str]:
    return git("tag", "--list", "v*").splitlines()


def latest_stable(head: str = "HEAD", *, before: str | None = None) -> str:
    possibilities = [
        tag for tag in tags()
        if (match := STABLE_RE.fullmatch(tag))
        and (before is None or tuple(map(int, match.groups())) < tuple(map(int, before.split("."))))
        and is_ancestor(tag, head)
    ]
    if not possibilities:
        raise ValueError("No reachable prior stable tag: refusing to invent release history")
    return max(possibilities, key=lambda tag: tuple(map(int, STABLE_RE.fullmatch(tag).groups())))


def commits(base: str, head: str) -> list[tuple[str, str]]:
    if not is_ancestor(base, head):
        raise ValueError(f"Cannot compare unrelated Git revisions: {base} and {head}")
    history = git("log", "--reverse", "--no-merges", "--format=%H%x1f%s", f"{base}..{head}")
    return [
        (sha, subject)
        for row in history.splitlines()
        if "\x1f" in row
        for sha, subject in [row.split("\x1f", 1)]
    ]


def classify(subject: str) -> str:
    lower = subject.lower()
    if lower.startswith(("docs:", "document ", "explain ", "clarify ", "unify software citations")):
        return "Documentation"
    if "website" in lower or "citation" in lower or "doi" in lower or "rrid" in lower:
        return "Documentation"
    if lower.startswith(("fix ", "correct ", "resolve ", "repair ", "prevent ", "avoid ",
                         "guard ", "restore ", "harden ", "handle ", "retain ", "preserve ",
                         "stop ", "reject ")):
        return "Fixed"
    if lower.startswith(("add ", "introduce ", "implement ", "enable ", "support ",
                         "include ", "expose ", "create ", "integrate ")):
        return "Added"
    return "Changed"


def change_groups(base: str, head: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    for sha, original in commits(base, head):
        subject = MARKER_RE.sub("", original).strip().rstrip(".")
        # Build plumbing, CI tests, and generated changelog commits are not
        # user-facing fixes/features. Preserve the underlying Git history.
        if (not subject or SKIP_RE.match(subject)
                or subject.lower().startswith(("test ", "tests "))
                or "changelog" in subject.lower()):
            continue
        key = subject.casefold()
        if key in seen:
            continue
        seen.add(key)
        group = classify(subject)
        groups[group].append(
            f"- {subject}. ([`{sha[:8]}`](https://github.com/SebRoLENS/curvemole/commit/{sha}))"
        )
    return groups


def render_groups(groups: dict[str, list[str]]) -> str:
    parts = [f"### {group}\n\n" + "\n".join(groups[group])
             for group in ORDER if groups.get(group)]
    return "\n\n".join(parts) if parts else "_No user-visible changes recorded in this range._"


def _unreleased_bounds(text: str) -> tuple[int, int]:
    header = re.search(r"(?m)^## \[Unreleased\][^\n]*\n", text)
    if not header:
        raise ValueError("CHANGELOG.md requires an Unreleased header")
    following = re.search(r"(?m)^## \[", text[header.end():])
    if following is None:
        raise ValueError("CHANGELOG.md requires at least one existing release")
    return header.end(), header.end() + following.start()


def update_unreleased(text: str, base: str, head: str) -> str:
    start, end = _unreleased_bounds(text)
    existing = text[start:end].strip()
    if BEGIN in existing or END in existing:
        if existing.count(BEGIN) != 1 or existing.count(END) != 1:
            raise ValueError("Malformed auto-generated changelog markers")
        existing = (existing[:existing.index(BEGIN)] + existing[existing.index(END) + len(END):]).strip()
    generated = render_groups(change_groups(base, head))
    auto = f"{BEGIN}\n{generated}\n{END}"
    body = "\n\n".join(section for section in (auto, existing) if section)
    return text[:start] + "\n" + body + "\n\n" + text[end:]


def sync_changelog(head: str = "HEAD", path: Path = CHANGELOG) -> str:
    base = latest_stable(head)
    updated = update_unreleased(path.read_text(encoding="utf-8"), base, head)
    path.write_text(updated, encoding="utf-8")
    return base


def freeze_stable(version: str, path: Path = CHANGELOG, head: str = "HEAD",
                  date: dt.date | None = None) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Expected a final semantic version")
    text = path.read_text(encoding="utf-8")
    if re.search(rf"(?m)^## \[{re.escape(version)}\]", text):
        return  # Exact-release retry: never duplicate or rewrite published history.
    base = latest_stable(head, before=version)
    text = update_unreleased(text, base, head)
    start, end = _unreleased_bounds(text)
    body = text[start:end].strip()
    # Remove comments, retain the generated entries and any curated manual notes.
    body = body.replace(BEGIN + "\n", "").replace("\n" + END, "").strip()
    stamp = (date or dt.date.today()).isoformat()
    path.write_text(
        text[:start] + f"\n## [{version}] - {stamp}\n\n{body}\n\n" + text[end:],
        encoding="utf-8",
    )


def published_beta_tags(head: str = "HEAD") -> list[str]:
    candidates = [tag for tag in tags() if BETA_RE.fullmatch(tag) and is_ancestor(tag, head)]
    return sorted(candidates, key=lambda tag: (int(git("rev-list", "--count", tag)),
                                               tuple(map(int, BETA_RE.fullmatch(tag).groups()))))


def preceding_beta_or_stable(tag: str, previous_beta: str | None) -> str:
    if previous_beta is not None and is_ancestor(previous_beta, tag):
        return previous_beta
    return latest_stable(tag)


def beta_changes(head: str = "HEAD", *, version: str | None = None) -> tuple[str, str]:
    prior = None
    if version:
        match = re.fullmatch(r"(\d+\.\d+\.\d+)b[1-9]\d*", version)
        if not match:
            raise ValueError("Expected a beta version such as 1.1.1b51")
        prefix = f"v{match.group(1)}-beta."
        candidates = [t for t in published_beta_tags(head) if t.startswith(prefix)]
        prior = candidates[-1] if candidates else None
    base = prior or latest_stable(head)
    return base, render_groups(change_groups(base, head))


def _published_beta_dates() -> dict[str, str] | None:
    """Prefer verified publication dates; offline mode uses Git commit dates."""
    if not os.environ.get("GH_TOKEN") or not os.environ.get("GITHUB_REPOSITORY"):
        return None
    try:
        raw = subprocess.check_output(
            ["gh", "api", f"repos/{os.environ['GITHUB_REPOSITORY']}/releases?per_page=100"],
            cwd=ROOT, text=True, timeout=30,
        )
        releases = json.loads(raw)
        if not isinstance(releases, list):
            return None
        return {
            entry["tag_name"]: entry["published_at"][:10]
            for entry in releases
            if isinstance(entry, dict)
            and entry.get("prerelease") is True
            and entry.get("draft") is False
            and BETA_RE.fullmatch(str(entry.get("tag_name", "")))
            and isinstance(entry.get("published_at"), str)
        }
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def sync_beta_history(head: str = "HEAD", path: Path = HISTORY) -> None:
    dates = _published_beta_dates()
    previous = None
    entries = []
    reachable = published_beta_tags(head)
    if dates is not None:
        reachable = [tag for tag in reachable if tag in dates]
    for tag in reachable:
        base = preceding_beta_or_stable(tag, previous)
        dated = dates[tag] if dates is not None else git("show", "-s", "--format=%cs", tag)
        date_kind = "published" if dates is not None else "source"
        changes = render_groups(change_groups(base, tag))
        entries.append(
            f"## [{tag[1:]}](https://github.com/SebRoLENS/curvemole/releases/tag/{tag}) — {date_kind} {dated}\n\n"
            f"Changes since `{base}` ([compare](https://github.com/SebRoLENS/curvemole/compare/{base}...{tag})).\n\n"
            + changes
        )
        previous = tag
    intro = (
        "# Published beta history\n\n"
        "Generated from beta tags and the GitHub release catalog (when available). "
        "Beta run numbers may have gaps. Each section describes changes between "
        "consecutive published betas, or since the previous stable release. "
        "The cumulative stable-cycle history is in `CHANGELOG.md`.\n\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(intro + "\n\n".join(reversed(entries)) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("sync", "freeze", "beta-notes"))
    parser.add_argument("--version", default="")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()
    if args.command == "sync":
        base = sync_changelog(args.head)
        sync_beta_history(args.head)
        print(f"Updated cumulative changelog since {base} and published beta history")
    elif args.command == "freeze":
        freeze_stable(args.version, head=args.head)
    else:
        base, changes = beta_changes(args.head, version=args.version)
        print(f"Changes since {base}:\n\n{changes}")


if __name__ == "__main__":
    main()
