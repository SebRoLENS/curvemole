"""Gate Pages on completed CI and release metadata; assemble one website snapshot."""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from release_assets import expected_assets

ROOT = Path(__file__).resolve().parents[2]
GENERATED = {
    'src/curvemole/version.py', 'pyproject.toml', 'uv.lock', 'README.md',
    'CITATION.cff', 'CHANGELOG.md', 'docs/manual.md',
    'docs/CurveMole_User_Manual.tex', 'docs/CurveMole_User_Manual.pdf',
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
            return None, 'Waiting for successful CI, including the manual, for the current source.'
        ci_run_id = runs[0]['id']
    manual_releases = api('actions/workflows/automatic-release.yml/runs?branch=main&event=workflow_dispatch&per_page=1')['workflow_runs']
    if manual_releases and manual_releases[0]['status'] != 'completed':
        return None, 'A manually requested release is still running.'
    version = re.search(r'^__version__ = "([\d.]+)"',
                        (ROOT / 'src/curvemole/version.py').read_text(encoding="utf-8"), re.M)[1]
    # Listing also handles an absent or draft release without treating DOI delay as an error.
    releases = api('releases?per_page=100')
    release = next((r for r in releases if r['tag_name'] == f'v{version}'), {})
    citation = (ROOT / 'CITATION.cff').read_text(encoding="utf-8")
    if not release_ready(release, version, citation, (ROOT / 'README.md').read_text(encoding="utf-8")):
        return None, f'Waiting for v{version}: published packages/manual and matching Zenodo DOI.'
    tag = git('rev-parse', f'refs/tags/v{version}^{{commit}}')
    if subprocess.run(['git', 'merge-base', '--is-ancestor', tag, 'HEAD']).returncode:
        return None, 'Release tag is not part of the current source history.'
    return {'version': version, 'doi': field(citation, 'doi'), 'tag': f'v{version}',
            'source_sha': git('rev-parse', 'HEAD'), 'tag_sha': tag, 'ci_run_id': ci_run_id,
            'mode': 'integrated' if require_ci else 'standalone'}, ''


def assemble(metadata):
    dist = ROOT / 'website/dist'
    citation = (ROOT / 'CITATION.cff').read_text(encoding="utf-8")
    shutil.copyfile(ROOT / 'CITATION.cff', dist / 'CITATION.cff')
    index = (dist / 'index.html').read_text(encoding="utf-8")
    text = f'Romi, S. ({field(citation, "date-released")[:4]}). {field(citation, "title")} (v{metadata["version"]}) [Software]. Zenodo.'
    index, count = re.subn(r'(<[^>]+id="citationText"[^>]*>).*?(</[^>]+>)',
                          lambda m: m[1] + html.escape(text) + m[2], index, flags=re.S)
    if count != 1:
        raise ValueError('Missing or ambiguous citation text')
    doi = metadata['doi']
    index, count = re.subn(r'<a\b[^>]*id="citationDoi"[^>]*>.*?</a>',
                          f'<a id="citationDoi" href="https://doi.org/{doi}" target="_blank" rel="noopener">doi:{doi} ↗</a>',
                          index, flags=re.S)
    if count != 1:
        raise ValueError('Missing or ambiguous citation link')
    index = index.replace('/releases/latest', '/releases/tag/' + metadata['tag'])
    index = re.sub(r'(?<=href=")style\.css(?:\?[^\"]*)?(?=")',
                   'style.css?v=' + metadata['source_sha'], index)
    repository = os.environ.get('GITHUB_REPOSITORY', 'SebRoLENS/curvemole')
    index = index.replace(f'https://github.com/{repository}/blob/main/CITATION.cff', 'CITATION.cff')
    index = index.replace(f'https://github.com/{repository}/blob/main/',
                          f'https://github.com/{repository}/blob/{metadata["source_sha"]}/')
    (dist / 'index.html').write_text(index, encoding="utf-8")
    (dist / 'publication.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding="utf-8")


def main():
    metadata, reason = ready(require_ci=os.environ.get('WEBSITE_PUBLICATION_MODE') != 'standalone')
    if metadata:
        assemble(metadata)
    else:
        print(reason)
    with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding="utf-8") as output:
        output.write(f'ready={str(metadata is not None).lower()}\n')
    with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding="utf-8") as summary:
        summary.write((f'Website snapshot ready: {metadata["tag"]}, DOI {metadata["doi"]}.'
                       if metadata else reason) + '\n')


if __name__ == '__main__':
    main()
