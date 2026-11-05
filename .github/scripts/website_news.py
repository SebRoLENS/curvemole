"""Publish tested release news over the stable website, without promoting the app."""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

import website_release as website

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ('news.html', 'news-archive.html', 'style.css')
LEDGER = {'CHANGELOG.md', 'docs/beta-history.md'}
BOT = '41898282+github-actions[bot]@users.noreply.github.com'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def check_current(metadata):
    """Allow only generated ledgers after the validated news source."""
    if git('rev-parse', 'origin/main') != metadata['source_sha']:
        raise ValueError('Stable source advanced; rebuild the website snapshot')
    source, current = metadata['news_source_sha'], git('rev-parse', 'origin/testing')
    subprocess.run(['git', 'merge-base', '--is-ancestor', source, current], cwd=ROOT, check=True)
    for commit in git('rev-list', f'{source}..{current}').splitlines():
        files = set(git('diff-tree', '--no-commit-id', '--name-only', '-r', commit).splitlines())
        if git('show', '-s', '--format=%ae', commit) != BOT or not files <= LEDGER:
            raise ValueError('News source advanced beyond the validated snapshot')


def assemble(destination):
    stable_sha, news_sha = git('rev-parse', 'origin/main'), git('rev-parse', 'HEAD')
    with tempfile.TemporaryDirectory(prefix='curvemole-stable-news-') as directory:
        snapshot = Path(directory)
        archive = subprocess.check_output([
            'git', 'archive', stable_sha, 'website/dist', 'CITATION.cff',
            'README.md', 'CHANGELOG.md', 'src/curvemole/version.py',
        ], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(snapshot, filter='data')
        for name in OVERLAY:
            shutil.copyfile(ROOT / 'website/dist' / name, snapshot / 'website/dist' / name)
        original = website.ROOT
        try:
            website.ROOT = snapshot
            metadata, reason = website.ready(require_ci=False)
            if metadata is None:
                raise ValueError(reason)
            metadata.update(source_sha=stable_sha, news_source_sha=news_sha, mode='release-news')
            website.assemble(metadata)
            check_current(metadata)
            shutil.copytree(snapshot / 'website/dist', destination)
        finally:
            website.ROOT = original
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory for the complete stable snapshot')
    parser.add_argument('--check-current', action='store_true')
    args = parser.parse_args()
    if args.check_current:
        check_current(json.loads((args.output / 'publication.json').read_text(encoding='utf-8')))
        return
    metadata = assemble(args.output)
    with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as summary:
        summary.write(f'Release news refreshed; stable site remains pinned to {metadata["tag"]} '
                      f'({metadata["source_sha"]}). No software release or main write.\n')


if __name__ == '__main__':
    main()
