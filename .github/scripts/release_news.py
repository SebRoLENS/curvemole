"""Static, minor-scoped release news derived from published release history."""
from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path
from runpy import run_path

HISTORY = run_path(str(Path(__file__).with_name('changelog_tools.py')))
BASE_URL = 'https://sebrolens.github.io/curvemole/'
REPOSITORY = 'https://github.com/SebRoLENS/curvemole'
STABLE = re.compile(r'(\d+)\.(\d+)\.(\d+)$')
BETA = re.compile(r'v(\d+)\.(\d+)\.(\d+)-beta\.([1-9]\d*)$')


def version_key(version):
    match = STABLE.fullmatch(version)
    if not match:
        raise ValueError(f'Invalid stable version: {version}')
    return tuple(map(int, match.groups()))


def minor_series(version):
    return '.'.join(map(str, version_key(version)[:2]))


def beta_key(record):
    match = BETA.fullmatch(record['tag'])
    if not match:
        raise ValueError('Invalid beta release tag')
    return tuple(map(int, match.groups()))


def published_betas(releases):
    """Never treat a draft, stable release or unversioned tag as a beta."""
    found = {}
    for release in releases:
        tag = str(release.get('tag_name', ''))
        if (release.get('draft') is not False or release.get('prerelease') is not True
                or not BETA.fullmatch(tag) or not release.get('published_at')):
            continue
        stamp = str(release['published_at'])[:10]
        date.fromisoformat(stamp)
        found[tag] = {'tag': tag, 'date': stamp}
    return sorted(found.values(), key=beta_key, reverse=True)


def stable_records(changelog, current_version, current_date):
    records = {}
    for version, stamp in re.findall(
            r'(?m)^## \[(\d+\.\d+\.\d+)\](?: - (\d{4}-\d{2}-\d{2}))?[^\n]*$', changelog):
        if (1, 0, 0) <= version_key(version) <= version_key(current_version):
            if version == current_version and not stamp:
                stamp = current_date
            date.fromisoformat(stamp)
            records[version] = {'version': version, 'date': stamp}
    return sorted(records.values(), key=lambda record: version_key(record['version']), reverse=True)


def pretty_date(stamp):
    parsed = date.fromisoformat(stamp)
    return f'{parsed.day} {parsed.strftime("%B %Y")}'


def archive_path(channel, series):
    if channel not in {'stable', 'beta'} or not re.fullmatch(r'\d+\.\d+', series):
        raise ValueError('Invalid release archive series')
    return f'news-archive-{channel}-{series.replace(".", "-")}.html'


def stable_card(record, render):
    version, stamp = record['version'], record['date']
    return (
        f'<article class="release-entry release-entry--archive" id="release-{version.replace(".", "-")}">'
        '<div class="release-meta"><span class="release-pill">STABLE</span>'
        f'<time datetime="{stamp}">{pretty_date(stamp)}</time></div>'
        f'<h2>CurveMole <span>{version}</span></h2>'
        f'<div class="release-changes">{render(version)}</div>'
        f'<div class="resource-links"><a href="{REPOSITORY}/releases/tag/v{version}">'
        'Official release notes ↗</a></div></article>'
    )


def beta_notes(record):
    """Compare immutable published tags, not the moving Unreleased section.

    Using the stable ancestor of the published tag naturally accumulates all its
    earlier beta commits once, and excludes work done after publication.
    """
    tag = record['tag']
    beta_key(record)
    base = HISTORY['latest_stable'](tag)
    groups = HISTORY['change_groups'](base, tag)
    return base, HISTORY['render_groups'](groups)


def beta_card(record, render, *, folded=False):
    tag, stamp = record['tag'], record['date']
    major, minor, patch, sequence = beta_key(record)
    label = f'{major}.{minor}.{patch} Beta {sequence}'
    baseline, notes = beta_notes(record)
    changes = render(notes)
    for original, replacement in [('Added', 'New features'), ('Changed', 'Improvements'),
                                   ('Fixed', 'Bug fixes')]:
        changes = changes.replace(f'<h3>{original}</h3>', f'<h3>{replacement}</h3>')
    contents = (
        f'<p class="beta-baseline">Cumulative changes since Stable {html.escape(baseline[1:])}. '
        'Includes the earlier beta builds in this cycle, without repeating their changes.</p>'
        f'<div class="release-changes">{changes}</div>'
        f'<div class="resource-links"><a href="{REPOSITORY}/releases/tag/{tag}">'
        'Beta release notes &amp; downloads ↗</a>'
        f'<a href="{REPOSITORY}/compare/{baseline}...{tag}">Compare with Stable ↗</a></div>'
    )
    meta = (f'<span class="release-pill release-pill--beta">BETA</span>'
            f'<time datetime="{stamp}">{pretty_date(stamp)}</time>')
    if folded:
        return ('<article class="release-entry release-entry--archive release-entry--beta">'
                '<details class="beta-release-details">'
                f'<summary><span>{label}</span><time datetime="{stamp}">{pretty_date(stamp)}</time>'
                '</summary>' + contents + '</details></article>')
    return ('<article class="release-entry release-entry--beta">'
            f'<div class="release-meta">{meta}</div><h2>CurveMole <span>{label}</span></h2>'
            + contents + '</article>')


def series_links(channel, series, *, exclude=None):
    ordered = sorted(set(series), key=lambda value: tuple(map(int, value.split('.'))), reverse=True)
    return ''.join(f'<a href="{archive_path(channel, value)}">{value}.x ↗</a>'
                   for value in ordered if value != exclude)


def archive_page(template, filename, title, description, contents):
    page = re.sub(r'<main\b[^>]*>.*?</main>',
                  lambda _: '<main id="main-content"><section class="page-intro">'
                  '<span class="eyebrow">RELEASE ARCHIVE</span>'
                  f'<h1>{html.escape(title)}</h1><p>{html.escape(description)}</p>'
                  '<div class="resource-links"><a href="news.html">← Current release news</a>'
                  '<a href="news-archive.html">All release series ↗</a></div></section>'
                  f'<section class="page-section release-history">{contents}</section></main>',
                  template, count=1, flags=re.S)
    page = re.sub(r'<title>.*?</title>', lambda _: f'<title>{html.escape(title)} — CurveMole</title>',
                  page, count=1, flags=re.S)
    page = re.sub(r'<link\b(?=[^>]*\brel="canonical")[^>]*>',
                  lambda _: f'<link rel="canonical" href="{BASE_URL}{filename}"/>', page, count=1)
    page = re.sub(r'<meta\b(?=[^>]*\bname="description")[^>]*>',
                  lambda _: f'<meta name="description" content="{html.escape(description, quote=True)}"/>',
                  page, count=1)
    return page


def render_pages(template, metadata, changelog, render_stable, render_markdown):
    """Render independent current Stable/Beta series and linked archive pages."""
    current = metadata['version']
    stable_series = minor_series(current)
    stable = stable_records(changelog, current, metadata['date'])
    betas = sorted(metadata.get('beta_releases', []), key=beta_key, reverse=True)
    active = next((record for record in betas if beta_key(record)[:3] > version_key(current)), None)
    beta_series = '.'.join(map(str, beta_key(active)[:2])) if active else None
    stable_groups = {minor_series(record['version']) for record in stable}
    beta_groups = {'.'.join(map(str, beta_key(record)[:2])) for record in betas}
    pages = {}
    for series in sorted(stable_groups):
        name = archive_path('stable', series)
        body = ''.join(stable_card(record, render_stable) for record in stable
                       if minor_series(record['version']) == series)
        pages[name] = archive_page(template, name, f'Stable {series}.x',
                                   f'All published stable CurveMole releases in the {series}.x series.', body)
    for series in sorted(beta_groups):
        name = archive_path('beta', series)
        body = ''.join(beta_card(record, render_markdown, folded=True) for record in betas
                       if '.'.join(map(str, beta_key(record)[:2])) == series)
        pages[name] = archive_page(template, name, f'Beta {series}.x',
                                   'Open a published beta to read its cumulative features and bug fixes.', body)
    index = (
        '<section class="archive-channel" id="stable"><h2>Stable release series</h2>'
        '<p>Each series contains its initial release and subsequent patches.</p>'
        f'<div class="archive-series-links">{series_links("stable", stable_groups)}</div></section>'
        '<section class="archive-channel" id="beta"><h2>Published beta series</h2>'
        '<p>Historical beta notes stay available separately from stable release notes.</p>'
        f'<div class="archive-series-links">{series_links("beta", beta_groups)}</div></section>'
    )
    pages['news-archive.html'] = archive_page(
        template, 'news-archive.html', 'Release archive',
        'Choose a minor series to browse earlier stable releases and published betas.', index)

    page = template.replace('<!-- CURRENT STABLE SERIES -->', html.escape(stable_series) + '.x')
    previous = ''.join(stable_card(record, render_stable) for record in stable
                       if record['version'] != current and minor_series(record['version']) == stable_series)
    if not previous:
        page = page.replace('<h2>Earlier releases in this series</h2>', '')
    for start, end, content in [
        ('<!-- BEGIN HISTORICAL STABLE RELEASES -->', '<!-- END HISTORICAL STABLE RELEASES -->', previous),
        ('<!-- BEGIN STABLE ARCHIVE LINKS -->', '<!-- END STABLE ARCHIVE LINKS -->',
         series_links('stable', stable_groups, exclude=stable_series)),
    ]:
        if page.count(start) != 1 or page.count(end) != 1:
            raise ValueError('Missing release news markers')
        page = re.sub(re.escape(start) + '.*?' + re.escape(end),
                      lambda _, body=content, a=start, b=end: a + body + b, page, count=1, flags=re.S)
    if active:
        beta = (f'<div class="section-heading"><div><span class="eyebrow">BETA PREVIEW</span>'
                f'<h2 id="beta-series-title">Beta {beta_series}.x</h2></div></div>'
                '<p class="channel-intro">Features, improvements and bug fixes in the latest published '
                'beta, accumulated since its stable baseline. These changes are not yet in Stable.</p>'
                + beta_card(active, render_markdown)
                + f'<div class="resource-links"><a href="{archive_path("beta", beta_series)}">'
                f'All published {beta_series}.x betas ↗</a></div>')
    else:
        beta = ('<h2 id="beta-series-title">Beta preview</h2><p class="channel-intro">'
                'No published beta is ahead of the current Stable release. '
                'Previous beta notes remain available in the archive.</p>')
    older = series_links('beta', beta_groups, exclude=beta_series)
    if older:
        beta += '<div class="release-archive-links"><h3>Earlier beta series</h3>' + older + '</div>'
    begin, end = '<!-- BEGIN BETA RELEASE NEWS -->', '<!-- END BETA RELEASE NEWS -->'
    if page.count(begin) != 1 or page.count(end) != 1:
        raise ValueError('Missing beta news markers')
    page = re.sub(re.escape(begin) + '.*?' + re.escape(end),
                  lambda _: begin + beta + end, page, count=1, flags=re.S)
    pages['news.html'] = page
    return pages
