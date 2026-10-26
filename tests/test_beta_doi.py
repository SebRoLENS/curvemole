from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def beta(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / ".github/scripts"))
    spec = importlib.util.spec_from_file_location("beta_doi", ROOT / ".github/scripts/beta_doi.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/example")
    return module


def release(tag="v1.0.2-beta.8", **kwargs):
    return {"tag_name": tag, "body": "Beta notes\n", "draft": False, "prerelease": True, **kwargs}


def archive(version="v1.0.2-beta.8", tag="v1.0.2-beta.8", repo="owner/example"):
    return {"id": 123, "doi": "10.5281/zenodo.123", "metadata": {
        "title": "CurveMole: Modular Scientific Curve Fitting", "version": version,
        "related_identifiers": [{"identifier": f"https://github.com/{repo}/tree/{tag}",
                                 "relation": "isSupplementTo"}],
    }}


@pytest.mark.parametrize("version", ["v1.0.2-beta.8", "1.0.2-beta.8", "1.0.2b8"])
def test_beta_version_aliases_resolve_to_the_same_release(beta, version):
    assert beta.beta_tag(version) == "v1.0.2-beta.8"


@pytest.mark.parametrize("version", ["1.0.1", "1.0.2-beta.0", "1.0.2rc1", "../main", "1.0.2b8\n"])
def test_non_beta_inputs_are_rejected(beta, version):
    with pytest.raises(ValueError):
        beta.beta_tag(version)


def test_lookup_requires_the_exact_version_and_repository_tag(beta, monkeypatch):
    forged = archive()
    forged["metadata"]["related_identifiers"] = []
    candidates = [archive("v1.0.1"), archive(repo="attacker/fork"),
                  archive(tag="v1.0.2-beta.6"), forged, archive("1.0.2b8")]
    calls = []
    def records(query, *, all_versions):
        assert all_versions is True
        calls.append(query)
        return candidates

    monkeypatch.setattr(beta.zenodo, "zenodo_records", records)
    assert beta.find_beta_doi("1.0.2b8", "owner/example") == "10.5281/zenodo.123"
    assert calls == ["metadata.version:v1.0.2-beta.8"]
    monkeypatch.setattr(beta.zenodo, "zenodo_records", lambda q, **kwargs: candidates[:-1])
    assert beta.find_beta_doi("1.0.2b8", "owner/example") is None


def test_backfill_updates_only_beta_notes_and_preserves_recent_edits(beta, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    citation = tmp_path / "CITATION.cff"
    citation.write_text('version: "1.0.1"\ndoi: "10.5281/zenodo.999"\n')
    original = citation.read_bytes()
    calls, edits = [], []
    old = release("v1.0.2-beta.4")
    current = release(body="Edited installation instructions\n\n**Zenodo DOI:** pending archival.\n")

    def gh(*args):
        calls.append(args)
        if "--paginate" in args:
            return json.dumps([[old, release("v1.0.1", prerelease=False)],
                               [release(draft=True), release("community-plugins-latest"), release()]])
        return json.dumps(current if args[-1].endswith("beta.8") else old)

    def run(command, **kwargs):
        # The beta synchroniser may edit release descriptions only, never git,
        # tag refs, assets, README, stable metadata or release classification.
        assert command[:3] == ["gh", "release", "edit"]
        assert command[4:6] == ["--repo", "owner/example"]
        assert len(command) == 8 and command[6] == "--notes-file"
        edits.append((command[3], Path(command[-1]).read_text(encoding="utf-8")))

    monkeypatch.setattr(beta, "gh", gh)
    monkeypatch.setattr(beta.subprocess, "run", run)
    monkeypatch.setattr(beta, "find_beta_doi", lambda tag, repo: "10.5281/zenodo.123")
    assert beta.sync(attempts=1) == []
    assert [tag for tag, _ in edits] == ["v1.0.2-beta.4", "v1.0.2-beta.8"]
    assert "Edited installation instructions" in edits[1][1]
    assert "pending archival" not in edits[1][1]
    assert "https://doi.org/10.5281/zenodo.123" in edits[1][1]
    assert citation.read_bytes() == original
    assert "--slurp" in calls[0]


def test_completed_sync_is_idempotent_and_corrects_a_stale_doi(beta, monkeypatch):
    current = release(body="Notes\n\n**Zenodo DOI:** https://doi.org/10.5281/zenodo.123")
    monkeypatch.setattr(beta, "gh", lambda *args: json.dumps(current))
    monkeypatch.setattr(beta, "find_beta_doi", lambda *args: "10.5281/zenodo.123")
    monkeypatch.setattr(beta.subprocess, "run", lambda *a, **k: pytest.fail("Unnecessary write"))
    assert beta.sync("1.0.2b8", attempts=1) == []
    assert beta.updated_body(current["body"], "10.5281/zenodo.123") == current["body"]
    assert "zenodo.456" in beta.updated_body(current["body"], "10.5281/zenodo.456")


def test_delayed_archive_retries_then_reports_pending_without_inventing_a_doi(beta, monkeypatch):
    monkeypatch.setattr(beta, "gh", lambda *args: json.dumps(release()))
    monkeypatch.setattr(beta, "find_beta_doi", lambda *args: None)
    monkeypatch.setattr(beta.subprocess, "run", lambda *a, **k: pytest.fail("No DOI to write"))
    delays = []
    monkeypatch.setattr(beta.time, "sleep", delays.append)
    assert beta.sync("1.0.2b8", attempts=3, delay=2) == ["v1.0.2-beta.8"]
    assert delays == [2, 2]
    responses = iter([None, "10.5281/zenodo.123"])
    monkeypatch.setattr(beta, "find_beta_doi", lambda *args: next(responses))
    monkeypatch.setattr(beta, "gh", lambda *args: json.dumps(release(
        body="**Zenodo DOI:** https://doi.org/10.5281/zenodo.123")))
    assert beta.sync("1.0.2b8", attempts=3, delay=0) == []


@pytest.mark.parametrize("changed", [release(draft=True), release(prerelease=False),
                                      release("v1.0.1", prerelease=False)])
def test_changed_or_non_beta_release_cannot_be_edited(beta, monkeypatch, changed):
    responses = iter([release(), changed])
    monkeypatch.setattr(beta, "gh", lambda *args: json.dumps(next(responses)))
    monkeypatch.setattr(beta, "find_beta_doi", lambda *args: "10.5281/zenodo.123")
    monkeypatch.setattr(beta.subprocess, "run", lambda *a, **k: pytest.fail("Unsafe release edit"))
    with pytest.raises(ValueError, match="Release changed"):
        beta.sync("1.0.2b8", attempts=1)


def test_beta_workflow_separates_citation_writes_and_skips_duplicate_app_builds():
    testing = yaml.load((ROOT / ".github/workflows/testing.yml").read_text(), Loader=yaml.BaseLoader)
    jobs = testing["jobs"]
    assert "[skip release]" in jobs["packages"]["if"]
    assert jobs["validate"]["needs"] == "plan"
    assert set(jobs["doi"]["needs"]) == {"plan", "validate", "publish"}
    assert "needs.validate.result == 'success'" in jobs["doi"]["if"]
    assert "needs.publish.result == 'success'" in jobs["doi"]["if"]
    sync = yaml.load((ROOT / ".github/workflows/sync-zenodo-doi.yml").read_text(), Loader=yaml.BaseLoader)
    assert sync["on"]["workflow_dispatch"]["inputs"]["channel"]["default"] == "stable"
    assert sync["jobs"]["discover"]["if"] == "inputs.channel != 'beta'"
    beta = sync["jobs"]["beta"]
    assert beta["steps"][0]["with"]["ref"] == "testing"
    assert beta["concurrency"] == jobs["doi"]["concurrency"]
    assert "beta_doi.py" in beta["steps"][-1]["run"]
    assert "git push" not in beta["steps"][-1]["run"]
