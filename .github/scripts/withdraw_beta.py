"""Make explicitly superseded betas non-public after a verified replacement."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def read_json(repository: str, endpoint: str, *, missing_ok: bool = False):
    response = subprocess.run(['gh', 'api', f'repos/{repository}/{endpoint}'],
                              capture_output=True, text=True, check=False)
    if response.returncode:
        if missing_ok and 'HTTP 404' in response.stderr:
            return None
        raise RuntimeError(response.stderr)
    return json.loads(response.stdout)


def require_beta(release, tag: str, source: str, *, published: bool = False):
    if (not re.fullmatch(r'v\d+\.\d+\.\d+-beta\.[1-9]\d*', tag)
            or release.get('tag_name') != tag or release.get('prerelease') is not True
            or release.get('target_commitish') != source
            or (published and release.get('draft') is not False)):
        raise ValueError('Release identity or beta status changed; refusing withdrawal.')


def withdraw(replacement: str, root: Path = Path('.')) -> list[str]:
    match = re.fullmatch(r'(\d+\.\d+\.\d+)b([1-9]\d*)', replacement)
    if not match or os.environ.get('GITHUB_REF') != 'refs/heads/testing':
        raise ValueError('Withdrawal requires a published testing beta.')
    entries = json.loads((root / '.github/beta-withdrawals.json').read_text())
    selected = [entry for entry in entries if entry['replacement_target'] == match[1]]
    if not selected:
        return []
    repository = os.environ['GITHUB_REPOSITORY']
    new_tag = f'v{match[1]}-beta.{match[2]}'
    new = read_json(repository, f'releases/tags/{new_tag}')
    require_beta(new, new_tag, os.environ['GITHUB_SHA'], published=True)
    changed = []
    for entry in selected:
        old_tag, source = entry['tag'], entry['source']
        if old_tag == new_tag or not re.fullmatch(r'[0-9a-f]{40}', source):
            raise ValueError('Invalid withdrawal record.')
        old = read_json(repository, f'releases/tags/{old_tag}', missing_ok=True)
        if old is None:
            continue  # An already deleted release needs no further mutation.
        require_beta(old, old_tag, source)
        if old.get('draft') is True:
            continue
        subprocess.run(['gh', 'release', 'edit', old_tag, '--repo', repository, '--draft'],
                       check=True)
        confirmed = read_json(repository, f'releases/tags/{old_tag}')
        require_beta(confirmed, old_tag, source)
        if confirmed.get('draft') is not True:
            raise RuntimeError('Superseded beta is still public.')
        changed.append(old_tag)
    return changed


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--replacement', required=True)
    args = parser.parse_args()
    print('Withdrawn betas:', withdraw(args.replacement))
