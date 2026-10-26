from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def commit(path, text, message):
    Path(path).write_text(text, encoding="utf-8")
    git("add", path)
    git("commit", "-m", message)
    return git("rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.chdir(checkout)
    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (checkout / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    (checkout / ".github/scripts").mkdir(parents=True)
    for name in ("promote_testing.py", "release_state.py", "prepare_release.py", "readme_sections.py"):
        shutil.copy2(ROOT / ".github/scripts" / name, checkout / ".github/scripts" / name)
    (checkout / "src/curvemole").mkdir(parents=True)
    (checkout / "src/curvemole/version.py").write_text('__version__ = "1.0.1"\n', encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Stable baseline")
    baseline = git("rev-parse", "HEAD")
    git("tag", "v1.0.1")
    remote = tmp_path / "remote.git"
    git("init", "--bare", str(remote))
    git("remote", "add", "origin", str(remote))
    git("push", "origin", "main", "--tags")
    git("switch", "-c", "testing")
    source = commit("feature.txt", "tested beta\n", "Feature on testing")
    git("push", "origin", "testing")
    output = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    spec = importlib.util.spec_from_file_location("promotion_test", checkout / ".github/scripts/promote_testing.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, source, baseline, output


def prepared_release(source):
    git("switch", "-C", "main", "origin/main")
    prepared = commit("src/curvemole/version.py", '__version__ = "1.0.2"\n',
                      f"Prepare stable\n\nRelease-Run: 123\nRelease-Source: {source}")
    git("push", "origin", "main")
    return prepared


def test_snapshot_is_read_only_and_promotion_uses_exact_validated_sha(repo):
    module, source, baseline, output = repo
    module.snapshot(source, "123", "patch", "")
    assert git("ls-remote", "origin", "refs/heads/main").split()[0] == baseline
    assert f"main_sha={baseline}" in output.read_text()
    assert f"source_sha={source}" in output.read_text()
    module.promote(source, baseline, "123")
    assert git("ls-remote", "origin", "refs/heads/main").split()[0] == source
    assert git("ls-remote", "origin", "refs/heads/testing").split()[0] == source


def test_testing_change_during_validation_prevents_promotion(repo):
    module, source, baseline, _ = repo
    newer = commit("later.txt", "not yet validated\n", "Later beta")
    git("push", "origin", "testing")
    with pytest.raises(ValueError, match="testing changed"):
        module.promote(source, baseline, "123")
    assert git("ls-remote", "origin", "refs/heads/main").split()[0] == baseline
    assert git("ls-remote", "origin", "refs/heads/testing").split()[0] == newer


def test_main_change_during_validation_is_never_overwritten(repo):
    module, source, baseline, _ = repo
    git("switch", "main")
    newer = commit("metadata.txt", "new metadata\n", "Concurrent main change")
    git("push", "origin", "main")
    git("switch", "testing")
    with pytest.raises(ValueError, match="main changed"):
        module.promote(source, baseline, "123")
    with pytest.raises(ValueError, match="Merge main into testing"):
        module.snapshot(source, "123", "patch", "")
    assert git("ls-remote", "origin", "refs/heads/main").split()[0] == newer


def test_invalid_requested_version_fails_before_modifying_main(repo):
    module, source, baseline, _ = repo
    with pytest.raises(SystemExit, match="newer than"):
        module.snapshot(source, "123", "patch", "1.0.1")
    assert git("ls-remote", "origin", "refs/heads/main").split()[0] == baseline


def test_retry_reuses_own_preparation_and_does_not_promote_new_testing_commits(repo):
    module, source, baseline, _ = repo
    module.promote(source, baseline, "123")
    prepared = prepared_release(source)
    git("switch", "testing")
    newer = commit("later.txt", "new beta work\n", "Later beta")
    git("push", "origin", "testing")
    module.snapshot(source, "123", "patch", "")
    module.promote(source, baseline, "123")
    assert git("ls-remote", "origin", "refs/heads/main").split()[0] == prepared
    assert git("ls-remote", "origin", "refs/heads/testing").split()[0] == newer


def test_sync_keeps_new_testing_work_and_imports_released_version(repo):
    module, source, baseline, _ = repo
    module.promote(source, baseline, "123")
    prepared = prepared_release(source)
    git("switch", "testing")
    newer = commit("later.txt", "keep this work\n", "Later beta")
    git("push", "origin", "testing")
    module.sync_testing(prepared)
    updated = git("rev-parse", "origin/testing")
    assert module.ancestor(newer, updated)
    assert module.ancestor(prepared, updated)
    assert git("show", f"{updated}:later.txt") == "keep this work"
    assert git("show", f"{updated}:src/curvemole/version.py") == '__version__ = "1.0.2"'
    assert git("ls-remote", "origin", "refs/heads/main").split()[0] == prepared
    module.sync_testing(prepared)
    assert git("rev-parse", "origin/testing") == updated


def test_sync_conflicts_preserve_testing_and_the_already_published_main(repo):
    module, source, baseline, _ = repo
    module.promote(source, baseline, "123")
    prepared = prepared_release(source)
    git("switch", "testing")
    newer = commit("src/curvemole/version.py", '__version__ = "9.0.0"\n', "Conflicting testing work")
    git("push", "origin", "testing")
    with pytest.raises(ValueError, match="merge conflicts"):
        module.sync_testing(prepared)
    assert git("ls-remote", "origin", "refs/heads/testing").split()[0] == newer
    assert git("ls-remote", "origin", "refs/heads/main").split()[0] == prepared
    assert git("status", "--porcelain") == ""


def test_promotion_cannot_be_triggered_by_a_push_and_validation_gates_main_write():
    workflow = yaml.load((ROOT / ".github/workflows/promote-testing.yml").read_text(), Loader=yaml.BaseLoader)
    gateway = yaml.load((ROOT / ".github/workflows/automatic-release.yml").read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_call"}
    assert gateway["jobs"]["promotion"]["if"] == "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/testing'"
    assert set(workflow["jobs"]["promote"]["needs"]) == {"snapshot", "validate"}
    assert workflow["jobs"]["promote"]["concurrency"]["group"] == "curvemole-main-write"
    assert gateway["jobs"]["plan"]["needs"] == "promotion"
    assert "needs.promotion.result == 'success'" in gateway["jobs"]["plan"]["if"]
    assert set(gateway["jobs"]["sync-testing"]["needs"]) == {"commit", "packages"}
    assert "promote_testing.py" not in (ROOT / ".github/workflows/testing.yml").read_text()


@pytest.mark.parametrize("reference", ["testing", "HEAD", "a" * 39, "a" * 40 + "; echo unsafe"])
def test_only_exact_commit_identifiers_are_accepted(repo, reference):
    module, _, _, _ = repo
    with pytest.raises(ValueError, match="exact commit"):
        module.sha(reference)
