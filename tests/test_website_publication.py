from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

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


@pytest.mark.parametrize('change', ['prepared_release', 'application_code', 'human_documentation'])
def test_generated_history_recognizes_release_documents_without_accepting_untested_code(
        website, tmp_path, monkeypatch, change):
    monkeypatch.chdir(tmp_path)

    def git(*args):
        return subprocess.check_output(['git', *args], text=True).strip()

    git('init', '-q', '-b', 'testing')
    git('config', 'user.name', 'Developer')
    git('config', 'user.email', 'developer@example.test')
    (tmp_path / 'baseline').write_text('validated source', encoding='utf-8')
    git('add', 'baseline')
    git('commit', '-qm', 'Validated source')
    source = git('rev-parse', 'HEAD')
    if change == 'prepared_release':
        paths = [*website.release_files, 'docs/screenshots/fit-overview.png']
    elif change == 'application_code':
        paths = ['src/curvemole/core/fitting.py']
    else:
        paths = ['docs/python-api.md']
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('prepared metadata', encoding='utf-8')
    git('add', '.')
    if change != 'human_documentation':
        git('config', 'user.name', 'github-actions[bot]')
        git('config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
    git('commit', '-qm', 'Prepare release')
    assert website.generated_since(source) is (change == 'prepared_release')


@pytest.mark.parametrize('conclusion, publication, expected', [
    ('success', None, True),
    ('failure', 'success', True),
    ('cancelled', 'success', True),
    ('failure', 'failure', False),
    ('cancelled', 'skipped', False),
    ('cancelled', None, False),
    (None, 'success', False),
])
def test_manual_promotion_requires_verified_publication(
        website, release, monkeypatch, tmp_path, conclusion, publication, expected):
    from types import SimpleNamespace

    monkeypatch.setattr(website, 'ROOT', tmp_path)
    (tmp_path / 'src/curvemole').mkdir(parents=True)
    (tmp_path / 'src/curvemole/version.py').write_text('__version__ = "1.2.3"', encoding='utf-8')
    (tmp_path / 'CITATION.cff').write_text('version: "1.2.3"\ndoi: "10.5281/zenodo.123"', encoding='utf-8')
    (tmp_path / 'README.md').write_text('https://doi.org/10.5281/zenodo.123', encoding='utf-8')

    def api(path):
        if 'ci.yml/runs?' in path:
            return {'workflow_runs': [{'id': 1, 'conclusion': 'success', 'head_sha': 'old'}]}
        if path == 'actions/runs/2/jobs?per_page=100':
            return {'jobs': [{'name': 'packages / Attach packages to tagged release',
                              'conclusion': publication}]} if publication else {'jobs': []}
        if 'branch=testing' in path:
            return {'workflow_runs': [{'id': 2, 'status': 'completed' if conclusion else 'in_progress',
                                       'conclusion': conclusion, 'head_sha': 'tested'}]}
        return [release] if path.startswith('releases?') else {'workflow_runs': []}

    monkeypatch.setattr(website, 'api', api)
    monkeypatch.setattr(website, 'generated_since', lambda source: source == 'tested')
    monkeypatch.setattr(website, 'git', lambda *args: 'abc123')
    monkeypatch.setattr(website.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    metadata, reason = website.ready()
    if expected:
        assert metadata['ci_run_id'] == 2 and not reason
    else:
        assert metadata is None and 'promotion' in reason


@pytest.mark.parametrize("existing_doi", [False, True])
def test_snapshot_bundles_matching_citation_and_pins_downloads(website, monkeypatch, tmp_path, existing_doi):
    # Emulate the Windows legacy locale even when this regression runs on Linux.
    original_open = Path.open

    def windows_open(path, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        if 'b' not in mode and encoding in (None, 'locale'):
            encoding = 'cp1252'
        return original_open(path, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, 'open', windows_open)
    monkeypatch.setattr(website, 'ROOT', tmp_path)
    (tmp_path / 'website/dist').mkdir(parents=True)
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    citation = re.sub(r'^doi:.*\n', '', citation, flags=re.M)
    if existing_doi:
        citation += '\ndoi: "10.5281/zenodo.456"\n'
    citation = re.sub(r'^version:.*$', 'version: "1.2.3"', citation, flags=re.M)
    citation = re.sub(r'^doi:.*\n', '', citation, flags=re.M)
    citation += '\ndoi: "10.5281/zenodo.123"\n'
    (tmp_path / 'CITATION.cff').write_text(citation, encoding="utf-8")
    for source_page in (ROOT / 'website/dist').glob('*.html'):
        (tmp_path / 'website/dist' / source_page.name).write_text(source_page.read_text(encoding='utf-8'), encoding='utf-8')
    (tmp_path / 'CHANGELOG.md').write_text('## [Unreleased]\n- Development only\n\n## [1.2.3]\n### Fixed\n- Stable correction.\n', encoding='utf-8')
    target = tmp_path / 'website/dist/index.html'
    manual = tmp_path / 'website/dist/documentation.html'
    contact = tmp_path / 'website/dist/contact.html'
    website.assemble({'version': '1.2.3', 'tag': 'v1.2.3', 'doi': '10.5281/zenodo.123', 'source_sha': 'abc123'})
    assert '/releases/latest' not in target.read_text(encoding="utf-8")
    assert 'href="https://raw.githubusercontent.com/SebRoLENS/curvemole/abc123/docs/CurveMole_User_Manual.pdf"' in manual.read_text(encoding="utf-8")
    assert '/releases/download/v1.0.0/' not in target.read_text(encoding="utf-8")
    assert '/blob/main/' not in target.read_text(encoding="utf-8")
    assert '(Version 1.2.3)' in contact.read_text(encoding="utf-8")
    assert 'href="style.css?v=abc123"' in target.read_text(encoding="utf-8")
    assert 'https://doi.org/10.5281/zenodo.123' in contact.read_text(encoding="utf-8")
    assert "10.5281/zenodo.22113854" in contact.read_text(encoding="utf-8")
    assert (tmp_path / 'website/dist/CITATION.cff').read_text(encoding="utf-8") == citation
    assert 'version = {1.2.3}' in (tmp_path / 'website/dist/citation.bib').read_text(encoding='utf-8')
    assert 'version =' not in (tmp_path / 'website/dist/concept-citation.bib').read_text(encoding='utf-8')
    news = (tmp_path / 'website/dist/news.html').read_text(encoding='utf-8')
    assert '<h3>Fixed</h3><ul><li>Stable correction.</li></ul>' in news
    assert 'Development only' not in news
    assert 'No detailed changelog entries' not in news
    assert json.loads((tmp_path / 'website/dist/publication.json').read_text(encoding="utf-8"))['tag'] == 'v1.2.3'


def test_deploy_cannot_race_screenshots_or_bypass_readiness():
    workflow = yaml.load((ROOT / '.github/workflows/website.yml').read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert 'push' not in workflow['on']
    assert set(workflow['on']['workflow_run']['workflows']) == {'CI', 'Automatic release'}
    condition = workflow['jobs']['deploy']['if']
    assert "github.event.workflow_run.event == 'push'" in condition
    assert "github.event.workflow_run.head_branch == 'main'" in condition
    assert "github.event.workflow_run.event == 'workflow_dispatch'" in condition
    assert "github.event.workflow_run.path == '.github/workflows/automatic-release.yml'" in condition
    assert 'workflow_run.name' not in condition
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
    metadata_sync = workflow['jobs']['sync-testing']['steps'][-1]
    assert 'isDraft == false and .isPrerelease == false' in metadata_sync['run']
    assert 'promote_testing.py sync' in metadata_sync['run']
    website = yaml.load((ROOT / '.github/workflows/website.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    assert website['on']['workflow_dispatch']['inputs']['mode']['default'] == 'standalone'
    check = next(s for s in website['jobs']['deploy']['steps'] if s.get('id') == 'readiness')
    assert check['env']['WEBSITE_PUBLICATION_MODE'] == "${{ github.event_name == 'workflow_dispatch' && inputs.mode || 'integrated' }}"


@pytest.mark.parametrize('name,path,event,branch,conclusion,repository,expected', [
    ('Promote testing to stable', 'automatic-release.yml', 'workflow_dispatch', 'testing', 'success', 'same', True),
    ('Stable release', 'automatic-release.yml', 'workflow_dispatch', 'main', 'success', 'same', True),
    ('CI', 'ci.yml', 'push', 'main', 'success', 'same', True),
    ('CI', 'ci.yml', 'push', 'testing', 'success', 'same', False),
    ('CI', 'ci.yml', 'workflow_dispatch', 'main', 'success', 'same', False),
    ('Automatic release', 'testing.yml', 'workflow_dispatch', 'testing', 'success', 'same', False),
    ('Promote testing to stable', 'automatic-release.yml', 'workflow_dispatch', 'testing', 'failure', 'same', True),
    ('Promote testing to stable', 'automatic-release.yml', 'workflow_dispatch', 'testing', 'cancelled', 'same', True),
    ('Stable release', 'automatic-release.yml', 'workflow_dispatch', 'main', 'failure', 'same', False),
    ('CI', 'ci.yml', 'push', 'main', 'failure', 'same', False),
    ('Promote testing to stable', 'automatic-release.yml', 'workflow_dispatch', 'testing', 'success', 'fork', False),
])
def test_website_event_gate_accepts_named_promotions_and_rejects_unrelated_runs(
        name, path, event, branch, conclusion, repository, expected):
    workflow = yaml.load((ROOT / '.github/workflows/website.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    run = SimpleNamespace(name=name, path='.github/workflows/' + path, event=event,
                          head_branch=branch, conclusion=conclusion,
                          head_repository=SimpleNamespace(full_name='owner/repo' if repository == 'same' else 'other/fork'))
    github = SimpleNamespace(ref='refs/heads/main', repository='owner/repo',
                             event_name='workflow_run', event=SimpleNamespace(workflow_run=run))
    # Evaluate the actual YAML boolean guard against realistic event fields.
    # A run's display name is dynamic; workflow path identifies its definition.
    condition = ' '.join(workflow['jobs']['deploy']['if'].split()).replace('&&', ' and ').replace('||', ' or ')
    assert eval(condition, {'__builtins__': {}}, {'github': github}) is expected


@pytest.mark.parametrize('ref,mode,expected', [
    ('main', 'integrated', True),
    ('testing', 'standalone', True),
    ('testing', 'integrated', False),
    ('other', 'standalone', False),
])
def test_manual_website_recovery_from_testing_uses_standalone_mode(ref, mode, expected):
    workflow = yaml.load((ROOT / '.github/workflows/website.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    condition = workflow['jobs']['deploy']['if'].replace('&&', ' and ').replace('||', ' or ')
    github = SimpleNamespace(ref=f'refs/heads/{ref}', event_name='workflow_dispatch',
                             event=SimpleNamespace(workflow_run=None))
    inputs = SimpleNamespace(mode=mode)
    assert eval(' '.join(condition.split()), {'__builtins__': {}}, {'github': github, 'inputs': inputs}) is expected
    checkout = workflow['jobs']['deploy']['steps'][0]
    assert checkout['with']['ref'] == 'main'


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
        if path.startswith('releases?'):
            if path.endswith('page=1'):
                return [{'tag_name': f'v1.2.4-beta.{i}'} for i in range(100)]
            return [release]
        return {'workflow_runs': []}

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


def test_stable_changelog_excludes_development_and_other_versions(website, monkeypatch, tmp_path):
    monkeypatch.setattr(website, 'ROOT', tmp_path)
    (tmp_path / 'CHANGELOG.md').write_text(
        '## [Unreleased]\n- Not stable\n\n## [2.0.0b1]\n- Beta only\n\n'
        '## [1.2.3] - 2026-10-22\n### Fixed\n- Keep `a < b` safe\n'
        '  across wrapped lines.\n\n## [1.2.2]\n- Older fix\n', encoding='utf-8')
    rendered = website.stable_changelog('1.2.3')
    assert '<h3>Fixed</h3>' in rendered
    assert '<code>a &lt; b</code> safe across wrapped lines.' in rendered
    assert 'Not stable' not in rendered and 'Beta only' not in rendered and 'Older fix' not in rendered
    assert 'No detailed changelog entries' in website.stable_changelog('1.2.4')


@pytest.mark.parametrize('generated', [False, True])
def test_sitemap_lists_the_public_pages_and_robots_advertises_it(website, tmp_path, generated):
    from xml.etree import ElementTree

    dist = ROOT / 'website/dist'
    if generated:
        import shutil

        dist = Path(shutil.copytree(dist, tmp_path / 'dist'))
        archive_url = 'https://sebrolens.github.io/curvemole/news-archive-beta-1-1.html'
        (dist / 'news-archive-beta-1-1.html').write_text(
            f'<link rel="canonical" href="{archive_url}">', encoding='utf-8')
        website.write_sitemap(dist)
    namespace = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    urls = [node.text for node in ElementTree.parse(dist / 'sitemap.xml').findall('s:url/s:loc', namespace)]
    base = 'https://sebrolens.github.io/curvemole/'
    expected = {
        '', 'download.html', 'documentation.html', 'quick-start.html', 'news.html',
        'news-archive.html', 'contact.html', 'privacy.html',
    }
    expected.update(path.name for path in dist.glob('news-archive-*.html'))
    assert set(urls) == {base + name for name in expected}
    assert len(urls) == len(set(urls))
    assert f'Sitemap: {base}sitemap.xml' in (dist / 'robots.txt').read_text(encoding='utf-8')
    for url in urls:
        page = dist / (url.removeprefix(base) or 'index.html')
        assert f'href="{url}"' in page.read_text(encoding='utf-8')


def test_historical_stable_release_archive_excludes_betas_and_current(website, monkeypatch, tmp_path):
    monkeypatch.setattr(website, 'ROOT', tmp_path)
    (tmp_path / 'CHANGELOG.md').write_text(
        '# Changelog\n\n'
        '## [Unreleased]\n- Never on stable website\n\n'
        '## [1.2.3] - 2026-10-30\n### Fixed\n- Current release.\n\n'
        '## [1.2.2] - 2026-10-29\n### Added\n- Earlier feature.\n\n'
        '## [1.2.2b7] - 2026-10-28\n### Fixed\n- Beta only.\n\n'
        '## [1.0.1] - 2026-10-25\n### Fixed\n- Old correction.\n\n'
        '## [1.0.0] - 2026-10-23\n### Changed\n- First stable release.\n',
        encoding='utf-8',
    )
    archive = website.historical_stable_releases('1.2.3')
    assert archive.index('CurveMole <span>1.2.2</span>') < archive.index('CurveMole <span>1.0.1</span>')
    assert archive.index('CurveMole <span>1.0.1</span>') < archive.index('CurveMole <span>1.0.0</span>')
    assert archive.count('class="release-entry release-entry--archive"') == 3
    assert 'Earlier feature.' in archive and 'Old correction.' in archive
    assert 'First stable release.' in archive
    assert 'FIRST STABLE' in archive
    assert '/compare/v1.0.1...v1.2.2' in archive
    assert '1.2.3</span>' not in archive and '1.2.2b7' not in archive
    assert 'Never on stable website' not in archive and 'Beta only' not in archive


def test_retroactive_stable_changelog_shows_clickable_audited_commits(website, monkeypatch, tmp_path):
    monkeypatch.setattr(website, 'ROOT', tmp_path)
    (tmp_path / 'CHANGELOG.md').write_text(
        '## [Unreleased]\n\n- Experimental fix.\n\n'
        '## [1.1.0] - 2026-10-28\n\n'
        '### Fixed\n\n'
        '- Restore stable release documentation. '
        '([`a1b2c3d4`](https://github.com/SebRoLENS/curvemole/commit/a1b2c3d4)).\n\n'
        '## [1.0.1] - 2026-10-25\n',
        encoding='utf-8',
    )
    rendered = website.stable_changelog('1.1.0')
    assert '<h3>Fixed</h3>' in rendered
    assert '<a href="https://github.com/SebRoLENS/curvemole/commit/a1b2c3d4">' in rendered
    assert '<code>a1b2c3d4</code>' in rendered
    assert 'Experimental fix' not in rendered
