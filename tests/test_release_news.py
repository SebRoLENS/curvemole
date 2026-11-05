from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def scripts(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / '.github/scripts'))
    modules = []
    for name in ('release_news', 'website_release', 'website_news'):
        spec = importlib.util.spec_from_file_location(name, ROOT / '.github/scripts' / f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def changelog():
    return '\n\n'.join(f'## [{version}] - 2026-11-01\n### Fixed\n- Notes for {version}.'
                       for version in ('2.0.0', '1.10.0', '1.9.0', '1.3.0', '1.2.2', '1.2.1', '1.2.0', '1.1.0'))


def pages(scripts, version, betas=()):
    news, website, _ = scripts
    return news.render_pages(
        (ROOT / 'website/dist/news.html').read_text(encoding='utf-8'),
        {'version': version, 'date': '2026-11-01', 'beta_releases': betas}, changelog(),
        lambda version: f'<p>Notes for {version}.</p>', website.changelog_html)


@pytest.mark.parametrize('version,present,absent', [
    ('1.2.2', ('1.2.1', '1.2.0'), ('1.1.0',)),
    ('1.3.0', (), ('1.2.2', '1.2.1', '1.2.0')),
    ('2.0.0', (), ('1.3.0', '1.2.0')),
])
def test_only_current_minor_is_expanded_and_older_notes_remain_linked(scripts, version, present, absent):
    rendered = pages(scripts, version)
    current = rendered['news.html']
    for old in present:
        assert f'Notes for {old}.' in current
    for old in absent:
        assert f'Notes for {old}.' not in current
        series = '.'.join(old.split('.')[:2]).replace('.', '-')
        name = f'news-archive-stable-{series}.html'
        assert f'href="{name}"' in current
        assert f'Notes for {old}.' in rendered[name]
    assert 'Notes for 1.10.0.' not in current
    assert 'news-archive.html' in current


def test_stable_and_beta_series_roll_independently_without_repeating_builds(scripts, monkeypatch):
    news, _, _ = scripts
    monkeypatch.setattr(news, 'beta_notes', lambda record: ('v1.2.2', '### Fixed\n\n- Cumulative correction.'))
    betas = [{'tag': tag, 'date': '2026-11-02'} for tag in
             ('v1.3.0-beta.10', 'v1.3.0-beta.9', 'v1.2.3-beta.8')]
    rendered = pages(scripts, '1.2.2', betas)
    current = rendered['news.html']
    assert 'Stable 1.2.x' in current and 'Beta 1.3.x' in current
    assert current.count('Cumulative correction.') == 1
    assert '1.3.0 Beta 10' in current and '1.3.0 Beta 9' not in current
    assert '<h3>Bug fixes</h3>' in current
    assert 'news-archive-beta-1-2.html' in current
    archive = rendered['news-archive-beta-1-3.html']
    assert archive.count('<details ') == 2
    assert archive.index('1.3.0 Beta 10') < archive.index('1.3.0 Beta 9')
    assert 'href="https://sebrolens.github.io/curvemole/news-archive-beta-1-3.html"' in archive
    stable = pages(scripts, '1.3.0', betas)
    assert 'No published beta is ahead' in stable['news.html']
    assert 'Cumulative correction.' not in stable['news.html']
    assert 'Cumulative correction.' in stable['news-archive-beta-1-3.html']


def test_catalog_uses_published_beta_identity_and_numeric_versions(scripts):
    news, _, _ = scripts
    def release(tag, **changes):
        return dict(tag_name=tag, draft=False, prerelease=True, published_at='2026-11-02T12:00:00Z', **changes)
    catalog = [release(tag) for tag in ('v1.9.0-beta.99', 'v1.10.0-beta.9', 'v1.10.0-beta.10',
                                      'community-plugins-latest', 'v1.10.0')]
    catalog += [{**release('v2.0.0-beta.1'), 'draft': True},
                {**release('v2.0.0-beta.2'), 'published_at': None},
                {**release('v2.0.0-beta.3'), 'prerelease': False}]
    records = news.published_betas(catalog)
    assert [record['tag'] for record in records] == [
        'v1.10.0-beta.10', 'v1.10.0-beta.9', 'v1.9.0-beta.99']
    assert news.minor_series('1.10.3') == '1.10'


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, text=True).strip()


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, 'init', '-q', '-b', 'testing')
    git(tmp_path, 'config', 'user.name', 'Test')
    git(tmp_path, 'config', 'user.email', 'test@example.org')
    (tmp_path / 'example').write_text('base', encoding='utf-8')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'Base')
    return tmp_path


def commit(root, message, path='example'):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(message, encoding='utf-8')
    git(root, 'add', path)
    git(root, 'commit', '-qm', message)
    return git(root, 'rev-parse', 'HEAD')


def test_cumulative_notes_compare_published_tag_and_exclude_unpublished_work(scripts, repository, monkeypatch):
    news, _, _ = scripts
    news.HISTORY['git'].__globals__['ROOT'] = repository
    git(repository, 'tag', 'v1.2.0')
    commit(repository, 'Add reusable formula saving')
    git(repository, 'tag', 'v1.2.1-beta.1')
    commit(repository, 'Fix result column duplication')
    # Same subject in a later beta must not duplicate the feature.
    commit(repository, 'Add reusable formula saving')
    git(repository, 'tag', 'v1.2.1-beta.2')
    commit(repository, 'Add unpublished experimental feature')
    base, body = news.beta_notes({'tag': 'v1.2.1-beta.2'})
    assert base == 'v1.2.0'
    assert body.count('Add reusable formula saving.') == 1
    assert 'Fix result column duplication.' in body
    assert 'unpublished experimental' not in body
    assert '### Added' in body and '### Fixed' in body


@pytest.mark.parametrize('newer', ['none', 'ledger', 'human-ledger', 'source', 'stable'])
def test_news_snapshot_rejects_new_sources_but_allows_generated_ledgers(scripts, repository, monkeypatch, newer):
    _, _, publisher = scripts
    monkeypatch.setattr(publisher, 'ROOT', repository)
    stable = git(repository, 'rev-parse', 'HEAD')
    git(repository, 'update-ref', 'refs/remotes/origin/main', stable)
    source = commit(repository, 'Update release news')
    if newer in {'ledger', 'source'}:
        git(repository, 'config', 'user.email', publisher.BOT)
    if newer != 'none':
        head = commit(repository, 'Newer change',
                      'CHANGELOG.md' if newer in {'ledger', 'human-ledger'} else 'example')
        if newer == 'stable':
            git(repository, 'update-ref', 'refs/remotes/origin/main', head)
    git(repository, 'update-ref', 'refs/remotes/origin/testing', 'HEAD')
    metadata = {'source_sha': stable, 'news_source_sha': source}
    if newer in {'none', 'ledger'}:
        publisher.check_current(metadata)
    else:
        with pytest.raises(ValueError, match='advanced'):
            publisher.check_current(metadata)


def test_news_pipeline_requires_validation_and_keeps_stable_release_separate():
    def load(name):
        return yaml.load((ROOT / '.github/workflows' / name).read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    testing, website = load('testing.yml'), load('website.yml')
    caller = testing['jobs']['website-news']
    assert set(caller['needs']) == {'validate', 'publish'}
    assert "needs.validate.result == 'success'" in caller['if']
    assert "needs.publish.result == 'success'" in caller['if']
    assert '[website only]' in caller['if']
    assert caller['with'] == {'source_ref': '${{ github.sha }}', 'news_only': 'true'}
    job = website['jobs']['release-news']
    assert "github.ref == 'refs/heads/testing'" in job['if']
    assert 'inputs.source_ref == github.sha' in job['if']
    assert job['permissions']['contents'] == 'read'
    commands = '\n'.join(step.get('run', '') for step in job['steps'])
    assert 'website_news.py --output' in commands
    assert 'website_news.py --check-current' in commands
    assert 'promote_testing' not in commands and 'git push' not in commands
    assert website['concurrency']['group'] == 'github-pages'


def test_sitemap_is_generated_from_the_complete_snapshot_including_archives(scripts, tmp_path):
    from xml.etree import ElementTree

    _, website, _ = scripts
    base = 'https://sebrolens.github.io/curvemole/'
    for name in ('index.html', 'news.html', 'news-archive.html', 'news-archive-beta-1-2.html'):
        canonical = base + ('' if name == 'index.html' else name)
        (tmp_path / name).write_text(f'<link rel="canonical" href="{canonical}">', encoding='utf-8')
    (tmp_path / 'google123abc.html').write_text('google-site-verification: google123abc.html', encoding='utf-8')
    (tmp_path / 'sitemap.xml').write_text('obsolete sitemap', encoding='utf-8')
    website.write_sitemap(tmp_path)
    root = ElementTree.parse(tmp_path / 'sitemap.xml')
    urls = [item.text for item in root.findall('.//{*}loc')]
    assert urls == [base, base + 'news-archive-beta-1-2.html', base + 'news-archive.html', base + 'news.html']
    assert (tmp_path / 'sitemap.txt').read_text(encoding='utf-8').splitlines() == urls
    assert f'Sitemap: {base}sitemap.xml' in (tmp_path / 'robots.txt').read_text(encoding='utf-8')
    (tmp_path / 'news.html').write_text('<link rel="canonical" href="https://sebrolens.github.io/news.html">', encoding='utf-8')
    with pytest.raises(ValueError, match='Incorrect canonical'):
        website.write_sitemap(tmp_path)
