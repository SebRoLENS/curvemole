"""Gate Pages on completed CI and release metadata; assemble one website snapshot."""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from runpy import run_path
from xml.etree import ElementTree

from release_assets import expected_assets
from release_news import published_betas, render_pages

citations = run_path(str(Path(__file__).with_name("citation_metadata.py")))
ROOT = Path(__file__).resolve().parents[2]
# Stable preparation promotes the complete documentation set, not only citation
# files. Share its canonical manifest so valid bot-generated release commits do
# not look like unvalidated application changes to the Pages gate.
release_files = run_path(str(Path(__file__).with_name("release_state.py")))["FILES"]
GENERATED = {
    *release_files,
    *citations['GENERATED'],
}


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def api(path):
    return json.loads(subprocess.check_output(
        ['gh', 'api', f'repos/{os.environ["GITHUB_REPOSITORY"]}/{path}'], text=True))


def field(text, name):
    match = re.search(rf'^{re.escape(name)}:\s*(.+)$', text, re.M)
    return match[1].strip().strip('\"\'') if match else ''


def release_ready(release, version, citation, readme):
    doi = field(citation, 'doi')
    return (
        release.get('tag_name') == f'v{version}'
        and not release.get('draft') and not release.get('prerelease')
        and bool(release.get('published_at'))
        and expected_assets(version) <= {a['name'] for a in release.get('assets', [])
                                         if a.get('state') == 'uploaded' and a.get('size', 0) > 0}
        and field(citation, 'version') == version
        and bool(re.fullmatch(r'10\.5281/zenodo\.\d+', doi))
        and f'**Zenodo DOI:** https://doi.org/{doi}' in (release.get('body') or '')
        and f'https://doi.org/{doi}' in readme
    )


def generated_since(source):
    if subprocess.run(['git', 'merge-base', '--is-ancestor', source, 'HEAD']).returncode:
        return False
    for commit in git('rev-list', f'{source}..HEAD').splitlines():
        if git('show', '-s', '--format=%ae', commit) != '41898282+github-actions[bot]@users.noreply.github.com':
            return False
        paths = git('diff-tree', '--no-commit-id', '--name-only', '-r', commit).splitlines()
        if any(p not in GENERATED and not p.startswith(('docs/screenshots/', 'website/dist/assets/'))
               for p in paths):
            return False
    return True


def ready(*, require_ci=True):
    ci_run_id = None
    if require_ci:
        # Automatic publication must not fall back to an older successful source.
        runs = api('actions/workflows/ci.yml/runs?branch=main&event=push&per_page=1')['workflow_runs']
        if not runs or runs[0]['conclusion'] != 'success' or not generated_since(runs[0]['head_sha']):
            # A manual testing promotion validates and releases that exact snapshot
            # itself; its GITHUB_TOKEN push deliberately does not start main CI.
            runs = api('actions/workflows/automatic-release.yml/runs?branch=testing&event=workflow_dispatch&per_page=1')['workflow_runs']
            if (not runs or runs[0].get('status') != 'completed' or runs[0]['conclusion'] != 'success'
                    or not generated_since(runs[0]['head_sha'])):
                return None, 'Waiting for successful CI or a completed testing promotion for the current source.'
        ci_run_id = runs[0]['id']
    manual_releases = api('actions/workflows/automatic-release.yml/runs?branch=main&event=workflow_dispatch&per_page=1')['workflow_runs']
    if manual_releases and manual_releases[0]['status'] != 'completed':
        return None, 'A manually requested release is still running.'
    version = re.search(r'^__version__ = "([\d.]+)"',
                        (ROOT / 'src/curvemole/version.py').read_text(encoding="utf-8"), re.M)[1]
    # Listing also handles an absent or draft release without treating DOI delay as an error.
    release, page, catalog = {}, 1, []
    while True:
        releases = api(f'releases?per_page=100&page={page}')
        catalog.extend(releases)
        release = release or next((r for r in releases if r['tag_name'] == f'v{version}'), {})
        if len(releases) < 100:
            break
        page += 1
    citation = (ROOT / 'CITATION.cff').read_text(encoding="utf-8")
    if not release_ready(release, version, citation, (ROOT / 'README.md').read_text(encoding="utf-8")):
        return None, f'Waiting for v{version}: published packages/manual and matching Zenodo DOI.'
    tag = git('rev-parse', f'refs/tags/v{version}^{{commit}}')
    if subprocess.run(['git', 'merge-base', '--is-ancestor', tag, 'HEAD']).returncode:
        return None, 'Release tag is not part of the current source history.'
    return {'version': version, 'doi': field(citation, 'doi'), 'tag': f'v{version}',
            'source_sha': git('rev-parse', 'HEAD'), 'tag_sha': tag, 'ci_run_id': ci_run_id,
            'beta_releases': published_betas(catalog),
            'mode': 'integrated' if require_ci else 'standalone'}, ''


def stable_changelog(version):
    """Render only the selected final release, excluding unreleased/beta entries."""
    path = ROOT / 'CHANGELOG.md'
    source = path.read_text(encoding="utf-8") if path.exists() else ''
    match = re.search(rf'^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)',
                      source, re.M | re.S)
    body = match[1].strip() if match else ''
    if not body:
        return ('<p>No detailed changelog entries were recorded for this stable release. '
                'The official release notes and downloads are available on GitHub.</p>')
    return changelog_html(body)


def changelog_html(body):
    """Render our limited changelog Markdown without accepting arbitrary HTML."""
    blocks, paragraph, items = [], [], []

    def inline(value):
        value = html.escape(value)
        # Only link back to known CurveMole commit URLs, never arbitrary HTML.
        value = re.sub(
            r'\[([^\]]+)\]\((https://github\.com/SebRoLENS/curvemole/commit/[a-f0-9]{8,40})\)',
            r'<a href="\2">\1</a>', value,
        )
        value = re.sub(r'`([^`]+)`', r'<code>\1</code>', value)
        return re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', value)

    def flush():
        if paragraph:
            blocks.append('<p>' + inline(' '.join(paragraph)) + '</p>')
            paragraph.clear()
        if items:
            blocks.append('<ul>' + ''.join('<li>' + inline(item) + '</li>' for item in items) + '</ul>')
            items.clear()

    for line in body.splitlines():
        if line.startswith('### '):
            flush()
            blocks.append('<h3>' + html.escape(line[4:]) + '</h3>')
        elif line.startswith('- '):
            if paragraph:
                flush()
            items.append(line[2:])
        elif not line.strip():
            flush()
        elif items and line.startswith('  '):
            items[-1] += ' ' + line.strip()
        else:
            paragraph.append(line.strip())
    flush()
    return ''.join(blocks)


def historical_stable_releases(current_version):
    """Show only final stable releases after 1.0.0 and before current."""
    if not re.fullmatch(r'\d+\.\d+\.\d+', current_version):
        raise ValueError('Expected a stable version')
    text = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
    found = re.findall(
        r'(?m)^## \[(\d+\.\d+\.\d+)\](?: - (\d{4}-\d{2}-\d{2}))?[^\n]*$',
        text,
    )
    current_key = tuple(map(int, current_version.split('.')))
    versions = {
        version: stamp
        for version, stamp in found
        if (1, 0, 0) <= tuple(map(int, version.split('.'))) < current_key
    }
    ordered = sorted(versions, key=lambda v: tuple(map(int, v.split('.'))))
    blocks = []
    for index, version in reversed(list(enumerate(ordered))):
        stamp = versions[version]
        if not stamp:
            raise ValueError(f'Missing stable release date: {version}')
        parsed = date.fromisoformat(stamp)
        pretty = f'{parsed.day} {parsed.strftime("%B %Y")}'
        tag = f'v{version}'
        previous = ordered[index - 1] if index else None
        compare = (
            f'<a href="https://github.com/SebRoLENS/curvemole/compare/v{previous}...{tag}">'
            'Compare with previous stable ↗</a>'
        ) if previous else ''
        milestone = 'FIRST STABLE' if version == '1.0.0' else 'STABLE'
        blocks.append(
            f'<article class="release-entry release-entry--archive" id="release-{version.replace(".", "-")}">'
            '<div class="release-meta">'
            f'<span class="release-pill">{milestone}</span>'
            f'<time datetime="{stamp}">{pretty}</time></div>'
            f'<h2>CurveMole <span>{version}</span></h2>'
            f'<div class="release-changes">{stable_changelog(version)}</div>'
            '<div class="resource-links">'
            f'<a href="https://github.com/SebRoLENS/curvemole/releases/tag/{tag}">Official release ↗</a>'
            + compare + '</div></article>'
        )
    return '\n'.join(blocks)


def write_sitemap(dist):
    """Generate the sitemap from canonical pages in the actual Pages artifact."""
    base = 'https://sebrolens.github.io/curvemole/'

    class Canonical(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'link' and 'canonical' in attrs.get('rel', '').split():
                self.links.append(attrs.get('href'))

    namespace = 'http://www.sitemaps.org/schemas/sitemap/0.9'
    ElementTree.register_namespace('', namespace)
    root = ElementTree.Element(f'{{{namespace}}}urlset')
    urls = []
    for path in sorted(dist.glob('*.html')):
        parser = Canonical()
        parser.feed(path.read_text(encoding='utf-8'))
        if not parser.links:
            # Search Console's verification file is not an indexable page.
            if re.fullmatch(r'google[0-9a-f]+\.html', path.name):
                continue
            raise ValueError(f'Missing canonical URL: {path.name}')
        expected = base + ('' if path.name == 'index.html' else path.name)
        if parser.links != [expected]:
            raise ValueError(f'Incorrect canonical URL: {path.name}')
        node = ElementTree.SubElement(root, f'{{{namespace}}}url')
        ElementTree.SubElement(node, f'{{{namespace}}}loc').text = expected
        urls.append(expected)
    ElementTree.indent(root)
    ElementTree.ElementTree(root).write(dist / 'sitemap.xml', encoding='utf-8', xml_declaration=True)
    # Google also accepts a UTF-8 file with one canonical URL per line. Keep the
    # two formats identical so a separate submission can diagnose fetch failures
    # without renaming the existing XML sitemap or losing its Console history.
    (dist / 'sitemap.txt').write_text('\n'.join(urls) + '\n', encoding='utf-8')
    (dist / 'robots.txt').write_text(f'User-agent: *\nAllow: /\n\nSitemap: {base}sitemap.xml\n', encoding='utf-8')


def assemble(metadata):
    dist = ROOT / 'website/dist'
    for path in dist.glob('news-archive-*.html'):
        if re.fullmatch(r'news-archive-(?:stable|beta)-\d+-\d+\.html', path.name):
            path.unlink()
    citation = (ROOT / 'CITATION.cff').read_text(encoding="utf-8")
    shutil.copyfile(ROOT / 'CITATION.cff', dist / 'CITATION.cff')
    data = citations["metadata"](citation)
    if data["version"] != metadata["version"] or data["doi"] != metadata["doi"]:
        raise ValueError("Website citation does not match the verified release")
    citations["write_website"](ROOT, data)
    repository = os.environ.get('GITHUB_REPOSITORY', 'SebRoLENS/curvemole')
    manual_url = (f'https://raw.githubusercontent.com/{repository}/{metadata["source_sha"]}/'
                  'docs/CurveMole_User_Manual.pdf')
    counts = {'manualPdf': 0}
    pages = {}
    for path in sorted(dist.glob('*.html')):
        page = path.read_text(encoding="utf-8")
        # Attribute order is not significant in HTML.
        page, count = re.subn(r'(<a\b(?=[^>]*\bid="manualPdf")[^>]*\bhref=")[^"]*(")',
                             lambda m: m[1] + manual_url + m[2], page)
        counts['manualPdf'] += count
        page = page.replace('/releases/latest', '/releases/tag/' + metadata['tag'])
        page = re.sub(r'(?<=href=")style\.css(?:\?[^\"]*)?(?=")',
                      'style.css?v=' + metadata.get('news_source_sha', metadata['source_sha']), page)
        page = page.replace(f'https://github.com/{repository}/blob/main/CITATION.cff', 'CITATION.cff')
        page = page.replace(f'https://github.com/{repository}/blob/main/',
                            f'https://github.com/{repository}/blob/{metadata["source_sha"]}/')
        for element_id, value in [('stableVersion', html.escape(metadata['version'])),
                                  ('stableDate', html.escape(field(citation, 'date-released'))),
                                  ('stableChangelog', stable_changelog(metadata['version']))]:
            page = re.sub(r'(<[^>]+id="' + element_id + r'"[^>]*>).*?(</(?:span|div)>)',
                          lambda m, replacement=value: m[1] + replacement + m[2], page, flags=re.S)
        if path.name == 'news.html':
            news = render_pages(page, {**metadata, 'date': field(citation, 'date-released')},
                                (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8'),
                                stable_changelog, changelog_html)
            pages.update({dist / name: content for name, content in news.items()})
            continue
        pages[path] = page
    for element_id, count in counts.items():
        if count != 1:
            raise ValueError(f'Missing or ambiguous {element_id}')
    for path, page in pages.items():
        # Generated archive pages supersede a source placeholder, regardless of
        # alphabetical iteration order above.
        if path.name.startswith('news-archive'):
            page = news[path.name]
        path.write_text(page, encoding="utf-8")
    write_sitemap(dist)
    (dist / 'publication.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding="utf-8")


def main():
    metadata, reason = ready(require_ci=os.environ.get('WEBSITE_PUBLICATION_MODE') != 'standalone')
    if metadata:
        assemble(metadata)
    else:
        print(f'::warning::Website deployment skipped: {reason}')
    with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding="utf-8") as output:
        output.write(f'ready={str(metadata is not None).lower()}\n')
    with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding="utf-8") as summary:
        summary.write((f'Website snapshot ready: {metadata["tag"]}, DOI {metadata["doi"]}.'
                       if metadata else reason) + '\n')


if __name__ == '__main__':
    main()
