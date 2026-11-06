"""Verify that both Pages paths render the tutorial using stable source only."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def publisher():
    spec = importlib.util.spec_from_file_location(
        "quick_start_publication", ROOT / ".github/scripts/quick_start_publication.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(directory, *args):
    return subprocess.check_output(["git", *args], cwd=directory, text=True).strip()


def snapshot(directory, source, *, version="1.2.2", guide=True):
    directory.mkdir()
    marker = '<meta name="curvemole-quick-start" content="raman">' if guide else ""
    (directory / "quick-start.html").write_text(marker, encoding="utf-8")
    (directory / "publication.json").write_text(json.dumps({
        "source_sha": source, "version": version,
    }), encoding="utf-8")
    return directory


@pytest.fixture
def repository(tmp_path):
    path = tmp_path / "repository"
    path.mkdir()
    git(path, "init", "-q", "-b", "testing")
    git(path, "config", "user.name", "Tutorial Test")
    git(path, "config", "user.email", "tutorial@example.test")
    (path / "src/curvemole").mkdir(parents=True)
    (path / "src/curvemole/version.py").write_text('__version__ = "1.2.2"\n', encoding="utf-8")
    (path / "website/scripts").mkdir(parents=True)
    renderer = path / "website/scripts/render_quick_start_screenshots.py"
    # This subprocess fixture tests dispatch/freshness, not GUI capture itself.
    renderer.write_text('''import argparse, json, os
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--output', type=Path)
out = p.parse_args().output
d = out / 'assets/quick-start'
d.mkdir(parents=True)
(d / '01-import.png').write_bytes(b'\\x89PNG\\r\\n\\x1a\\nfresh')
(out / 'quick-start-data').mkdir()
(out / 'quick-start-data/raman.csv').write_text('x,y\\n100,1\\n')
(d / 'manifest.json').write_text(json.dumps({
 'version':'1.2.2','source_sha':os.environ['CURVEMOLE_SCREENSHOT_SOURCE_SHA'],
 'screenshots':['01-import.png']}))
''', encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-qm", "Stable tutorial fixture")
    return path


def test_news_preparation_uses_verified_stable_commit_not_testing(publisher, repository, tmp_path, monkeypatch):
    stable = git(repository, "rev-parse", "HEAD")
    (repository / "src/curvemole/version.py").write_text('__version__ = "1.2.3b1"\n', encoding="utf-8")
    git(repository, "add", ".")
    git(repository, "commit", "-qm", "Later testing app")
    dist = snapshot(tmp_path / "dist", stable)
    checkout = tmp_path / "stable-app"
    monkeypatch.setattr(publisher, "ROOT", repository)

    assert publisher.prepare(dist, checkout)
    assert git(checkout, "rev-parse", "HEAD") == stable
    assert '"1.2.2"' in (checkout / "src/curvemole/version.py").read_text()
    assert git(repository, "branch", "--show-current") == "testing"


def test_pre_feature_stable_site_needs_no_checkout_or_renderer(publisher, tmp_path):
    dist = snapshot(tmp_path / "dist", "a" * 40, guide=False)
    assert publisher.prepare(dist, tmp_path / "unused") is False
    assert not (tmp_path / "unused").exists()


def test_guide_cannot_silently_skip_when_page_marker_is_missing(publisher, tmp_path):
    dist = snapshot(tmp_path / "dist", "a" * 40, guide=False)
    (dist / "quick-start.html").write_text('<img src="assets/quick-start/import.png">')
    with pytest.raises(ValueError, match="page marker"):
        publisher.guide_enabled(dist)


@pytest.mark.parametrize("problem", ["source", "version", "renderer"])
def test_wrong_or_incomplete_stable_checkout_fails_before_render(publisher, repository, tmp_path, problem):
    stable = git(repository, "rev-parse", "HEAD")
    version = "1.2.3" if problem == "version" else "1.2.2"
    dist = snapshot(tmp_path / "dist", "a" * 40 if problem == "source" else stable, version=version)
    if problem == "renderer":
        (repository / publisher.RENDERER).unlink()
    old = dist / "assets/quick-start/old.png"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old capture")
    with pytest.raises(ValueError, match="stable"):
        publisher.refresh(dist, repository)
    assert old.read_bytes() == b"old capture"


def test_refresh_removes_old_artifacts_and_validates_new_manifest(publisher, repository, tmp_path):
    stable = git(repository, "rev-parse", "HEAD")
    dist = snapshot(tmp_path / "dist", stable)
    old = dist / "assets/quick-start/old.png"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old capture")
    old_data = dist / "quick-start-data/old.csv"
    old_data.parent.mkdir()
    old_data.write_text("old data")

    assert publisher.refresh(dist, repository)
    assert not old.exists() and not old_data.exists()
    assert (dist / "quick-start-data/raman.csv").is_file()
    assert publisher.verify(dist)["source_sha"] == stable


@pytest.mark.parametrize("problem", ["version", "source", "missing", "invalid", "empty", "path", "data"])
def test_mismatched_or_incomplete_capture_manifest_is_rejected(publisher, repository, tmp_path, problem):
    stable = git(repository, "rev-parse", "HEAD")
    dist = snapshot(tmp_path / "dist", stable)
    publisher.refresh(dist, repository)
    manifest_path = dist / "assets/quick-start/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if problem == "version":
        manifest["version"] = "1.2.1"
    elif problem == "source":
        manifest["source_sha"] = "b" * 40
    elif problem == "missing":
        (manifest_path.parent / "01-import.png").unlink()
    elif problem == "invalid":
        (manifest_path.parent / "01-import.png").write_bytes(b"not a PNG")
    elif problem == "empty":
        manifest["screenshots"] = []
    elif problem == "data":
        (dist / "quick-start-data/raman.csv").unlink()
    else:
        manifest["screenshots"] = ["../outside.png"]
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Tutorial|tutorial"):
        publisher.verify(dist)


def test_both_publication_paths_refresh_tutorial_before_upload():
    workflow = yaml.load(
        (ROOT / ".github/workflows/website.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader,
    )
    jobs = workflow["jobs"]
    for name in ("deploy", "release-news"):
        if name not in jobs:
            continue
        steps = workflow["jobs"][name]["steps"]
        refresh = next(i for i, step in enumerate(steps) if "quick_start_publication.py refresh" in step.get("run", ""))
        upload = next(i for i, step in enumerate(steps) if "upload-pages-artifact" in step.get("uses", ""))
        guard = next(i for i, step in enumerate(steps) if step.get("name", "").startswith("Reject a superseded"))
        assert refresh < guard < upload
    if "release-news" not in jobs:
        return
    steps = jobs["release-news"]["steps"]
    prepare = next(step for step in steps if step.get("id") == "quickstart")
    refresh = next(step for step in steps if "quick_start_publication.py refresh" in step.get("run", ""))
    assert "quick_start_publication.py prepare" in prepare["run"]
    assert refresh["if"] == "steps.quickstart.outputs.required == 'true'"
    assert 'uv sync --project "$STABLE_TUTORIAL" --locked' in refresh["run"]
    assert '--checkout "$STABLE_TUTORIAL"' in refresh["run"]
