from __future__ import annotations

import importlib.util
import json
import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / ".github/scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = load("workflow_plan")
state = load("release_state")
assets = load("release_assets")
lint = load("lint_workflows")


@pytest.mark.parametrize("paths,event,message,expected", [
    (["src/curvemole/gui/panels.py", "docs/manual.md"], "push", "Fix UI", {"release"}),
    (["src/curvemole/core/fitting.py"], "push", "Fix fit [skip release]", {"candidate", "plugins", "documentation"}),
    (["docs/manual.md"], "push", "Explain fitting [skip release]", {"documentation"}),
    (["src/curvemole/gui/panels.py"], "push", "Fix UI [skip release]",
     {"documentation", "screenshots", "candidate"}),
    (["src/curvemole/core/fitting.py"], "pull_request", "Fix fit", {"plugins"}),
    (["README.md"], "push", "Correct spelling", {"documentation"}),
    (["custom_plugins/by_community/example/main.py"], "push", "New plugin", {"plugins", "documentation"}),
    (["docs/screenshots/import-file-preview.png"], "pull_request", "Preview", {"documentation"}),
])
def test_one_plan_avoids_duplicate_and_unrelated_jobs(paths, event, message, expected):
    result = policy.plan(paths, event, message, "maintainer")
    assert {key for key, enabled in result.items() if enabled} == expected


@pytest.mark.parametrize("signing,title,macos_instructions", [
    (None, "Windows and macOS downloads are unsigned.", True),
    ({"arm64": False, "x86_64": False}, "Windows and macOS downloads are unsigned.", True),
    ({"arm64": True, "x86_64": False}, "Windows and the macOS Intel download are unsigned.", True),
    ({"arm64": True, "x86_64": True}, "Windows downloads are unsigned.", False),
])
def test_release_notes_lead_with_signing_alert_and_first_launch_steps(
    tmp_path, monkeypatch, signing, title, macos_instructions,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/example")
    (tmp_path / "CHANGELOG.md").write_text("## [0.47.1] - 2026-10-22\n\nUseful changes.\n")

    body = assets.notes("0.47.1", True, signing)

    assert body.startswith("**Official website:** [CurveMole](https://sebrolens.github.io/curvemole/)")
    assert "[Windows, macOS and Linux](https://github.com/owner/example/releases/latest)" in body
    assert body.index("Download the latest version") < body.index("> [!CAUTION]")
    assert "> [!CAUTION]\n> **" + title + "**\n" in body
    assert "nonprofit project" in body and "developer-paid signing/certification costs" in body
    assert (body.index("> [!CAUTION]") < body.index("**First launch after an official download**")
            < body.index("More info → Run anyway") < body.index("## CurveMole v0.47.1")
            < body.index("| Platform | Recommended download |"))
    assert "official release page that you trust" in body and "`SHA256SUMS.txt`" in body
    assert ("System Settings → Privacy & Security" in body) == macos_instructions
    if macos_instructions:
        assert "**Open Anyway**, then **Open**, and authenticate if asked" in body
    else:
        assert "Both macOS downloads are signed with Apple Developer ID and notarized." in body
    assert "Useful changes." in body
    assert "**Zenodo DOI:** pending archival or repository integration." in body


def test_doi_update_preserves_release_installation_notice(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / ".github/scripts"))
    doi_workflow = load("doi_workflow")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/example")
    (tmp_path / "CHANGELOG.md").write_text("## [0.47.1] - 2026-10-22\n\nUseful changes.\n")
    body = assets.notes("0.47.1", True, {"arm64": False, "x86_64": False})

    updated = doi_workflow.updated_body(body, "10.5281/zenodo.1234567")

    assert updated.startswith("**Official website:** [CurveMole](https://sebrolens.github.io/curvemole/)")
    assert assets.installation_notice({"arm64": False, "x86_64": False}) in updated
    assert updated == body.replace("**Zenodo DOI:** pending archival or repository integration.",
                                   "**Zenodo DOI:** https://doi.org/10.5281/zenodo.1234567")


def git(cwd, *args):
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


@pytest.fixture
def repository(tmp_path, monkeypatch):
    checkout = tmp_path / "source"
    checkout.mkdir()
    git(checkout, "init", "-b", "main")
    git(checkout, "config", "user.name", "Test")
    git(checkout, "config", "user.email", "test@example.invalid")
    for name in state.FILES:
        path = checkout / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('__version__ = "0.35.4"\n' if name.endswith("version.py") else "original\n")
    (checkout / "docs/screenshots").mkdir()
    (checkout / "docs/screenshots/example.png").write_bytes(b"original image")
    git(checkout, "add", ".")
    git(checkout, "commit", "-m", "Source")
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", str(remote))
    git(checkout, "remote", "add", "origin", str(remote))
    git(checkout, "push", "origin", "main")
    monkeypatch.chdir(checkout)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/example")
    return checkout


def archive_changes(checkout):
    path = checkout / "src/curvemole/version.py"
    path.write_text('__version__ = "0.35.5"\n')
    with tarfile.open("prepared-release.tar.gz", "w:gz") as archive:
        for name in state.FILES:
            archive.add(name, arcname=name)
    git(checkout, "checkout", "--", "src/curvemole/version.py")


def test_release_retry_reuses_its_commit_and_version_after_tag_exists(repository):
    source = git(repository, "rev-parse", "HEAD")
    archive_changes(repository)
    args = type("Args", (), {"run_id": "123", "version": "0.35.5"})()
    state.commit(args)
    prepared = git(repository, "rev-parse", "HEAD")
    git(repository, "tag", "v0.35.5")
    git(repository, "checkout", source)
    assert state.previous_release("123", source) == (prepared, "0.35.5")
    state.commit(args)
    assert git(repository, "rev-parse", "origin/main") == prepared
    assert git(repository, "rev-parse", "HEAD") == source
    assert state.previous_release("12", source) is None


def test_preparation_records_identity_when_generated_files_are_unchanged(repository):
    source = git(repository, "rev-parse", "HEAD")
    with tarfile.open("prepared-release.tar.gz", "w:gz") as archive:
        for name in state.FILES:
            archive.add(name, arcname=name)
    args = type("Args", (), {"run_id": "456", "version": "0.35.4"})()
    state.commit(args)
    prepared = git(repository, "rev-parse", "HEAD")
    assert prepared != source
    assert git(repository, "rev-parse", "HEAD^{tree}") == git(repository, "rev-parse", source + "^{tree}")
    assert state.previous_release("456", source) == (prepared, "0.35.4")
    git(repository, "checkout", source)
    state.commit(args)
    assert git(repository, "rev-parse", "origin/main") == prepared


def test_stale_preparation_cannot_push_over_a_new_source(repository):
    source = git(repository, "rev-parse", "HEAD")
    archive_changes(repository)
    (repository / "new-source.py").write_text("new source")
    git(repository, "add", "new-source.py")
    git(repository, "commit", "-m", "New source")
    git(repository, "push", "origin", "main")
    newer = git(repository, "rev-parse", "HEAD")
    git(repository, "checkout", source)
    with pytest.raises(ValueError, match="advanced"):
        state.commit(type("Args", (), {"run_id": "123", "version": "0.35.5"})())
    assert git(repository, "rev-parse", "origin/main") == newer
    assert git(repository, "rev-parse", "HEAD") == source


def fixture_release(version, checks, draft=True):
    return {"draft": draft, "body": "", "assets": [
        {"name": name, "state": "uploaded", "size": 10, "digest": "sha256:" + value}
        for name, value in checks.items()
    ]}


def test_incomplete_and_corrupt_releases_cannot_be_verified():
    checks = {name: "a" * 64 for name in assets.expected_assets("0.35.5") | {"SHA256SUMS.txt"}}
    current = fixture_release("0.35.5", checks)
    assets.verify(current, "0.35.5", checks)
    current["assets"][0]["digest"] = "sha256:" + "b" * 64
    with pytest.raises(ValueError, match="mismatch"):
        assets.verify(current, "0.35.5", checks)
    current["assets"].pop()
    with pytest.raises(ValueError, match="missing"):
        assets.verify(current, "0.35.5", checks)


def test_tag_collision_cannot_be_reassigned(repository):
    git(repository, "tag", "v0.35.4")
    source = git(repository, "rev-parse", "HEAD")
    assets.ensure_tag("v0.35.4", source)
    (repository / "new.py").write_text("new")
    git(repository, "add", "new.py")
    git(repository, "commit", "-m", "Another commit")
    with pytest.raises(ValueError, match="different commit"):
        assets.ensure_tag("v0.35.4", git(repository, "rev-parse", "HEAD"))
    assert git(repository, "rev-parse", "v0.35.4") == source


def test_published_release_refuses_rebuild_before_any_upload(repository, monkeypatch):
    monkeypatch.setattr(assets, "release", lambda tag: {"draft": False})
    with pytest.raises(ValueError, match="already published"):
        assets.finalize("v0.35.4", repository / "absent")


def test_draft_lookup_paginates_when_tag_endpoint_returns_404(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/example")
    monkeypatch.setattr(assets.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 1, "", "gh: Not Found (HTTP 404)"))
    draft = {"id": 42, "tag_name": "v0.36.0", "draft": True, "assets": []}
    pages = []

    def lookup(path):
        pages.append(path)
        return ([{"tag_name": f"v0.1.{i}"} for i in range(100)]
                if path.endswith("page=1") else [draft])

    monkeypatch.setattr(assets, "api", lookup)
    assert assets.release("v0.36.0") == draft
    assert pages == ["releases?per_page=100&page=1", "releases?per_page=100&page=2"]


def test_missing_draft_finishes_lookup_on_last_page(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/example")
    monkeypatch.setattr(assets.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 1, "", "gh: Not Found (HTTP 404)"))
    monkeypatch.setattr(assets, "api", lambda path: [])
    assert assets.release("v0.36.0") is None


def test_release_lookup_does_not_hide_permission_errors(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/example")
    monkeypatch.setattr(assets.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 1, "", "gh: Forbidden (HTTP 403)"))
    monkeypatch.setattr(assets, "api", lambda path: pytest.fail("Must not list on a permission failure"))
    with pytest.raises(RuntimeError, match="HTTP 403"):
        assets.release("v0.36.0")


def test_finalization_uses_current_tools_with_original_tagged_source():
    workflow = yaml.safe_load((ROOT / ".github/workflows/build-desktop.yml").read_text())
    steps = workflow["jobs"]["publish-release-assets"]["steps"]
    assert steps[0]["with"]["ref"] == "${{ github.sha }}"
    assert '"$RUNNER_TEMP/release_assets.py"' in steps[1]["run"]
    assert steps[2]["with"]["ref"] == "${{ inputs.source_ref }}"
    assert steps[-1]["run"].startswith('python "$RUNNER_TEMP/release_assets.py" finalize')


def test_finalization_uploads_complete_assets_before_publishing(repository, monkeypatch):
    # Exercise the Windows legacy locale on every platform. Release notes contain
    # Unicode installation arrows and may include non-ASCII changelog entries.
    original_open = Path.open

    def windows_open(path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if "b" not in mode and encoding in (None, "locale"):
            encoding = "cp1252"
        return original_open(path, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", windows_open)
    directory = repository / "release-assets"
    directory.mkdir()
    version = "0.35.4"
    for name in assets.expected_assets(version):
        if "User-Manual" not in name:
            (directory / name).write_bytes(name.encode())
    for arch in ("arm64", "x86_64"):
        (directory / f"macos-signing-{arch}.json").write_text(json.dumps({"signed": False}))
    (repository / "CHANGELOG.md").write_text(
        "## [0.35.4] - 2026-10-02\n\n### Fixed\n\n- Useful correction — α.\n",
        encoding="utf-8",
    )
    current = fixture_release(version, {p.name: assets.digest(p) for p in directory.iterdir()
                                       if "AppImage" in p.name})
    monkeypatch.setattr(assets, "release", lambda tag: current)
    commands = []
    real_run = subprocess.run

    def fake_run(command, **kwargs):
        if command[:3] == ["gh", "release", "upload"]:
            checks = {name: value for value, name in (
                line.split() for line in (directory / "SHA256SUMS.txt").read_text().splitlines())}
            checks["SHA256SUMS.txt"] = assets.digest(directory / "SHA256SUMS.txt")
            current["assets"] = fixture_release(version, checks)["assets"]
            assert all("AppImage" not in item for item in command[4:])
            commands.append("upload")
            return subprocess.CompletedProcess(command, 0)
        if command[:3] == ["gh", "release", "edit"]:
            assert commands == ["upload"]
            assert "--draft=false" in command
            assert "--prerelease=false" in command
            assert "--latest" in command
            note = Path("release-notes.md").read_text(encoding="utf-8")
            assert "Useful correction — α." in note
            assert "More info → Run anyway" in note
            assert "unsigned" in note and "checksums have been verified" in note
            assert note.startswith("**Official website:** [CurveMole](https://sebrolens.github.io/curvemole/)")
            assert "[Windows, macOS and Linux](https://github.com/owner/example/releases/latest)" in note
            assert note.index("Download the latest version") < note.index("> [!CAUTION]")
            assert "/releases/download/v0.35.4/CurveMole-0.35.4-windows-x86_64-setup.exe" in note
            commands.append("publish")
            return subprocess.CompletedProcess(command, 0)
        return real_run(command, **kwargs)

    monkeypatch.setattr(assets.subprocess, "run", fake_run)
    assets.finalize("v0.35.4", directory)
    assert commands == ["upload", "publish"]


def test_manual_restoration_preserves_binaries_and_is_idempotent(repository, monkeypatch):
    git(repository, "tag", "v0.35.4")
    checks = {name: "b" * 64 for name in assets.expected_assets("0.35.4") | {"SHA256SUMS.txt"}}
    current = fixture_release("0.35.4", checks, draft=False)
    monkeypatch.setattr(assets, "release", lambda tag: current)
    real_run = subprocess.run
    uploads = []

    def fake_run(command, **kwargs):
        if command[:3] != ["gh", "release", "upload"]:
            return real_run(command, **kwargs)
        paths = [Path(p) for p in command[4:-1]]
        assert {p.name for p in paths} == {
            "CurveMole-0.35.4-User-Manual.pdf", "CurveMole-0.35.4-User-Manual.tex", "SHA256SUMS.txt"}
        for p in paths:
            item = next(a for a in current["assets"] if a["name"] == p.name)
            item["digest"] = "sha256:" + assets.digest(p)
        uploads.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(assets.subprocess, "run", fake_run)
    assets.repair_manual("v0.35.4", repository / "restored")
    assets.repair_manual("v0.35.4", repository / "restored")
    assert len(uploads) == 1
    assert all(a["digest"] == "sha256:" + "b" * 64 for a in current["assets"]
               if "User-Manual" not in a["name"] and a["name"] != "SHA256SUMS.txt")


def test_reusable_workflows_have_no_cycles_and_development_docs_cannot_upload_releases():
    workflows = {p.name: yaml.load(p.read_text(), Loader=yaml.BaseLoader)
                 for p in (ROOT / ".github/workflows").glob("*.yml")}

    def visit(name, ancestors=()):
        assert name not in ancestors, f"Reusable workflow cycle: {ancestors + (name,)}"
        for job in workflows[name]["jobs"].values():
            target = job.get("uses", "")
            if target.startswith("./.github/workflows/"):
                visit(Path(target).name, ancestors + (name,))

    for name in workflows:
        visit(name)
    docs = (ROOT / ".github/workflows/documentation.yml").read_text()
    assert "gh release" not in docs and "contents: read" in docs
    assert "push" not in workflows["automatic-release.yml"]["on"]
    assert "push" not in workflows["community-plugins.yml"]["on"]
    assert "pull_request_target" not in workflows["ci.yml"]["on"]


def test_queued_writers_are_never_cancelled_and_invalid_queue_policies_are_rejected():
    for p in (ROOT / ".github/workflows").glob("*.yml"):
        lint.validate_queues(yaml.load(p.read_text(), Loader=yaml.BaseLoader))
    with pytest.raises(ValueError):
        lint.validate_queues({"concurrency": {"queue": "max", "cancel-in-progress": "true"}})
    with pytest.raises(ValueError):
        lint.validate_queues({"concurrency": {"queue": "invalid"}})


def test_doi_lookup_skips_completed_releases_and_body_updates_are_idempotent(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / ".github/scripts"))
    doi = load("doi_workflow")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/example")
    body = "Description\n\n**Zenodo DOI:** https://doi.org/10.5281/zenodo.1234"
    monkeypatch.setattr(doi, "gh", lambda *args: json.dumps([
        {"draft": False, "prerelease": False, "tag_name": "v0.35.4", "body": body},
        {"draft": True, "prerelease": False, "tag_name": "v0.35.5", "body": ""},
    ]))
    monkeypatch.setattr(doi, "metadata_complete", lambda *args: True)
    monkeypatch.setattr(doi.zenodo, "find_doi", lambda *args: pytest.fail("Unexpected Zenodo request"))
    assert doi.discover("") == []
    assert doi.updated_body(body, "10.5281/zenodo.1234") == body
    assert doi.body_doi(doi.updated_body("Description", "10.5281/zenodo.1234")) == "10.5281/zenodo.1234"
