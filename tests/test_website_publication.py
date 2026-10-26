from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def website(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / '.github/scripts'))
    spec = importlib.util.spec_from_file_location('website_release', ROOT / '.github/scripts/website_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def release(website):
    return {'tag_name': 'v1.2.3', 'draft': False, 'prerelease': False, 'published_at': '2026-10-22',
            'body': '**Zenodo DOI:** https://doi.org/10.5281/zenodo.123',
            'assets': [{'name': name, 'size': 10, 'state': 'uploaded'}
                       for name in website.expected_assets('1.2.3')]}


@pytest.mark.parametrize('problem', ['draft', 'prerelease', 'missing_manual', 'missing_doi', 'wrong_tag', 'empty_asset'])
def test_incomplete_release_cannot_publish(website, release, problem):
    citation = 'version: "1.2.3"\ndoi: "10.5281/zenodo.123"\n'
    readme = 'https://doi.org/10.5281/zenodo.123'
    assert website.release_ready(release, '1.2.3', citation, readme)
    broken = copy.deepcopy(release)
    if problem in ('draft', 'prerelease'):
        broken[problem] = True
    elif problem == 'missing_manual':
        broken['assets'] = [a for a in broken['assets'] if not a['name'].endswith('Manual.pdf')]
    elif problem == 'missing_doi':
        broken['body'] = ''
    elif problem == 'wrong_tag':
        broken['tag_name'] = 'v1.2.2'
    else:
        broken['assets'][0]['size'] = 0
    assert not website.release_ready(broken, '1.2.3', citation, readme)
    assert not website.release_ready(release, '1.2.3', citation.replace('1.2.3', '1.2.2'), readme)


@pytest.mark.parametrize('conclusion', [None, 'failure', 'cancelled'])
def test_pending_or_failed_latest_ci_blocks_publication(website, monkeypatch, conclusion):
    monkeypatch.setattr(website, 'api', lambda path: {'workflow_runs': [{'conclusion': conclusion}]})
    metadata, reason = website.ready()
    assert metadata is None and 'CI' in reason


def test_unvalidated_source_blocks_publication(website, monkeypatch):
    monkeypatch.setattr(website, 'api', lambda path: {'workflow_runs': [{'conclusion': 'success', 'head_sha': 'old'}]})
    monkeypatch.setattr(website, 'generated_since', lambda sha: False)
    assert website.ready()[0] is None


@pytest.mark.parametrize('conclusion', ['success', 'failure', None])
def test_manual_promotion_is_a_validated_website_source_only_after_success(
        website, release, monkeypatch, tmp_path, conclusion):
    from types import SimpleNamespace

    monkeypatch.setattr(website, 'ROOT', tmp_path)
    (tmp_path / 'src/curvemole').mkdir(parents=True)
    (tmp_path / 'src/curvemole/version.py').write_text('__version__ = "1.2.3"', encoding='utf-8')
    (tmp_path / 'CITATION.cff').write_text('version: "1.2.3"\ndoi: "10.5281/zenodo.123"', encoding='utf-8')
    (tmp_path / 'README.md').write_text('https://doi.org/10.5281/zenodo.123', encoding='utf-8')

    def api(path):
        if 'ci.yml/runs?' in path:
            return {'workflow_runs': [{'id': 1, 'conclusion': 'success', 'head_sha': 'old'}]}
        if 'branch=testing' in path:
            return {'workflow_runs': [{'id': 2, 'status': 'completed' if conclusion else 'in_progress',
                                       'conclusion': conclusion, 'head_sha': 'tested'}]}
        return [release] if path.startswith('releases?') else {'workflow_runs': []}

    monkeypatch.setattr(website, 'api', api)
    monkeypatch.setattr(website, 'generated_since', lambda source: source == 'tested')
    monkeypatch.setattr(website, 'git', lambda *args: 'abc123')
    monkeypatch.setattr(website.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    metadata, reason = website.ready()
    if conclusion == 'success':
        assert metadata['ci_run_id'] == 2 and not reason
    else:
        assert metadata is None and 'promotion' in reason


def test_snapshot_bundles_matching_citation_and_pins_downloads(website, monkeypatch, tmp_path):
    # Emulate the Windows legacy locale even when this regression runs on Linux.
    original_open = Path.open

    def windows_open(path, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        if 'b' not in mode and encoding in (None, 'locale'):
            encoding = 'cp1252'
        return original_open(path, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, 'open', windows_open)
    monkeypatch.setattr(website, 'ROOT', tmp_path)
    (tmp_path / 'website/dist').mkdir(parents=True)
    citation = 'version: "1.2.3"\ndoi: "10.5281/zenodo.123"\ndate-released: 2026-10-22\ntitle: "CurveMole"\n'
    (tmp_path / 'CITATION.cff').write_text(citation, encoding="utf-8")
    index = ROOT / 'website/dist/index.html'
    target = tmp_path / 'website/dist/index.html'
    target.write_text(index.read_text(encoding="utf-8"), encoding="utf-8")
    website.assemble({'version': '1.2.3', 'tag': 'v1.2.3', 'doi': '10.5281/zenodo.123', 'source_sha': 'abc123'})
    assert '/releases/latest' not in target.read_text(encoding="utf-8")
    assert 'href="https://github.com/SebRoLENS/curvemole/releases/download/v1.2.3/CurveMole-1.2.3-User-Manual.pdf"' in target.read_text(encoding="utf-8")
    assert '/releases/download/v1.0.0/' not in target.read_text(encoding="utf-8")
    assert '/blob/main/' not in target.read_text(encoding="utf-8")
    assert '(v1.2.3)' in target.read_text(encoding="utf-8")
    assert 'href="style.css?v=abc123"' in target.read_text(encoding="utf-8")
    assert 'https://doi.org/10.5281/zenodo.123' in target.read_text(encoding="utf-8")
    assert (tmp_path / 'website/dist/CITATION.cff').read_text(encoding="utf-8") == citation
    assert json.loads((tmp_path / 'website/dist/publication.json').read_text(encoding="utf-8"))['tag'] == 'v1.2.3'


def test_deploy_cannot_race_screenshots_or_bypass_readiness():
    workflow = yaml.load((ROOT / '.github/workflows/website.yml').read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert 'push' not in workflow['on']
    assert set(workflow['on']['workflow_run']['workflows']) == {'CI', 'Automatic release'}
    steps = workflow['jobs']['deploy']['steps']
    render = next(i for i, s in enumerate(steps) if 'render_demo_screenshots.py' in s.get('run', ''))
    deploy = next(i for i, s in enumerate(steps) if s.get('id') == 'deployment')
    assert render < deploy
    for step in steps[render:]:
        assert step.get('if') == "steps.readiness.outputs.ready == 'true'"
    legacy = yaml.load((ROOT / '.github/workflows/website-screenshots.yml').read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert 'push' not in legacy['on']
    assert 'raw.githubusercontent.com' not in (ROOT / 'website/dist/citation.js').read_text(encoding="utf-8")


def test_doi_publication_waits_for_metadata_and_preserves_ci_gate():
    workflow = yaml.load((ROOT / '.github/workflows/sync-zenodo-doi.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    publish = workflow['jobs']['website']
    assert set(publish['needs']) == {'discover', 'apply'}
    condition = publish['if']
    assert "needs.discover.result == 'success'" in condition
    assert "needs.apply.result == 'success'" in condition
    assert "needs.apply.result == 'skipped'" in condition
    assert publish['permissions']['actions'] == 'write'
    assert '-f mode=integrated' in publish['steps'][0]['run']
    metadata_sync = workflow['jobs']['apply']['steps'][-1]
    assert 'isDraft == false and .isPrerelease == false' in metadata_sync['run']
    assert 'promote_testing.py sync' in metadata_sync['run']
    website = yaml.load((ROOT / '.github/workflows/website.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    assert website['on']['workflow_dispatch']['inputs']['mode']['default'] == 'standalone'
    check = next(s for s in website['jobs']['deploy']['steps'] if s.get('id') == 'readiness')
    assert check['env']['WEBSITE_PUBLICATION_MODE'] == "${{ github.event_name == 'workflow_dispatch' && inputs.mode || 'integrated' }}"


@pytest.mark.parametrize('doi_ready', [True, False])
def test_standalone_does_not_require_ci_but_still_requires_release_metadata(
        website, release, monkeypatch, tmp_path, doi_ready):
    from types import SimpleNamespace

    monkeypatch.setattr(website, 'ROOT', tmp_path)
    (tmp_path / 'src/curvemole').mkdir(parents=True)
    (tmp_path / 'src/curvemole/version.py').write_text('__version__ = "1.2.3"', encoding='utf-8')
    (tmp_path / 'CITATION.cff').write_text('version: "1.2.3"\ndoi: "10.5281/zenodo.123"', encoding='utf-8')
    (tmp_path / 'README.md').write_text('https://doi.org/10.5281/zenodo.123', encoding='utf-8')
    if not doi_ready:
        release['body'] = ''

    def api(path):
        assert 'ci.yml' not in path, 'Standalone publication must not query the full CI'
        return [release] if path.startswith('releases?') else {'workflow_runs': []}

    monkeypatch.setattr(website, 'api', api)
    monkeypatch.setattr(website, 'git', lambda *args: 'abc123')
    monkeypatch.setattr(website.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    metadata, reason = website.ready(require_ci=False)
    if doi_ready:
        assert metadata['mode'] == 'standalone'
        assert metadata['ci_run_id'] is None
        assert reason == ''
    else:
        assert metadata is None and 'DOI' in reason
