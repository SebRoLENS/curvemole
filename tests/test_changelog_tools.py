"""Release changelog history is complete across beta builds and stable promotion."""

from __future__ import annotations

import datetime as dt
import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / ".github" / "scripts" / "changelog_tools.py"


def command(directory: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=directory, text=True).strip()


def commit(directory: Path, name: str, message: str) -> str:
    target = directory / name
    target.write_text(message, encoding="utf-8")
    command(directory, "add", name)
    command(directory, "commit", "-m", message)
    return command(directory, "rev-parse", "HEAD")


@pytest.fixture
def changelog_repo(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("curvemole_changelog", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    command(tmp_path, "init", "-b", "testing")
    command(tmp_path, "config", "user.name", "CurveMole test")
    command(tmp_path, "config", "user.email", "test@example.com")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n"
        "- Curated explanation of a tricky bug.\n\n"
        "## [1.1.0] - 2026-10-28\n\n### Added\n\n- Previous stable feature.\n",
        encoding="utf-8",
    )
    command(tmp_path, "add", "CHANGELOG.md")
    command(tmp_path, "commit", "-m", "Previous stable release")
    command(tmp_path, "tag", "v1.1.0")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module, tmp_path, changelog


def test_beta_history_and_cumulative_notes(changelog_repo):
    tool, repo, changelog = changelog_repo
    added = commit(repo, "feature.txt", "Add automatic spectrum preview")
    command(repo, "tag", "v1.1.1-beta.2")
    fixed = commit(repo, "bug.txt", "Fix failure during save")
    command(repo, "tag", "v1.1.1-beta.5")
    commit(repo, "fix2.txt", "Prevent data loss during recovery")

    base = tool.sync_changelog(path=changelog)
    assert base == "v1.1.0"
    text = changelog.read_text(encoding="utf-8")
    assert text.count(tool.BEGIN) == 1
    assert "Add automatic spectrum preview" in text
    assert "Fix failure during save" in text
    assert "Prevent data loss during recovery" in text
    assert "Curated explanation" in text
    assert added[:8] in text and fixed[:8] in text

    tool.sync_changelog(path=changelog)
    assert changelog.read_text(encoding="utf-8") == text

    previous, notes = tool.beta_changes(version="1.1.1b6")
    assert previous == "v1.1.1-beta.5"
    assert "Prevent data loss during recovery" in notes
    assert "automatic spectrum preview" not in notes

    history = repo / "docs" / "beta-history.md"
    tool.sync_beta_history(path=history)
    historical = history.read_text(encoding="utf-8")
    assert "1.1.1-beta.2" in historical
    assert "1.1.1-beta.5" in historical
    assert "Fix failure during save" in historical
    assert "automatic spectrum preview" in historical
    tool.sync_beta_history(path=history)
    assert history.read_text(encoding="utf-8") == historical


def test_stable_freeze_collects_every_beta_and_resets_unreleased(changelog_repo):
    tool, repo, changelog = changelog_repo
    commit(repo, "feature.txt", "Add new model control")
    command(repo, "tag", "v1.1.1-beta.1")
    commit(repo, "fix.txt", "Fix old numerical problem")
    command(repo, "tag", "v1.1.1-beta.2")
    commit(repo, "last.txt", "Prevent regression after final beta")
    tool.freeze_stable("1.1.1", path=changelog, date=dt.date(2026, 10, 30))
    result = changelog.read_text(encoding="utf-8")
    assert "## [1.1.1] - 2026-10-30" in result
    assert result.index("## [1.1.1]") > result.index("## [Unreleased]")
    assert result.index("## [1.1.1]") < result.index("## [1.1.0]")
    assert all(message in result for message in (
        "Add new model control", "Fix old numerical problem",
        "Prevent regression after final beta", "Curated explanation",
    ))
    assert "## [Unreleased]\n\n## [1.1.1]" in result
    assert tool.BEGIN not in result and tool.END not in result
    tool.freeze_stable("1.1.1", path=changelog, date=dt.date(2026, 10, 31))
    assert changelog.read_text(encoding="utf-8") == result


def test_malformed_markers_are_rejected_before_replacement(changelog_repo):
    tool, repo, changelog = changelog_repo
    commit(repo, "fix.txt", "Fix legitimate user bug")
    contents = changelog.read_text(encoding="utf-8")
    changelog.write_text(contents.replace("## [Unreleased]", "## [Unreleased]\n\n" + tool.BEGIN),
                         encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed"):
        tool.sync_changelog(path=changelog)
