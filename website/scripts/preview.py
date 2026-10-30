"""Serve an assembled website snapshot on loopback without changing source metadata."""
from __future__ import annotations

import argparse
import functools
import http.server
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--metadata-ref', help='Local Git ref supplying stable citation and changelog')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / '.github/scripts'))
    spec = importlib.util.spec_from_file_location('website_release', ROOT / '.github/scripts/website_release.py')
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
    with tempfile.TemporaryDirectory(prefix='curvemole-preview-') as directory:
        snapshot = Path(directory)
        dist = snapshot / 'website/dist'
        shutil.copytree(ROOT / 'website/dist', dist)
        for name in ('CITATION.cff', 'CHANGELOG.md'):
            content = (subprocess.check_output(['git', 'show', f'{args.metadata_ref}:{name}'], cwd=ROOT)
                       if args.metadata_ref else (ROOT / name).read_bytes())
            (snapshot / name).write_bytes(content)
        citation = (snapshot / 'CITATION.cff').read_text(encoding='utf-8')
        version = release.field(citation, 'version')
        sha = subprocess.check_output(
            ['git', 'rev-parse', args.metadata_ref or 'HEAD'], cwd=ROOT, text=True).strip()
        release.ROOT = snapshot
        release.assemble({'version': version, 'tag': f'v{version}',
                          'doi': release.field(citation, 'doi'), 'source_sha': sha, 'mode': 'local-preview'})
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(dist))
        with http.server.ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
            print(f'CurveMole local preview: http://127.0.0.1:{args.port}/', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == '__main__':
    main()
