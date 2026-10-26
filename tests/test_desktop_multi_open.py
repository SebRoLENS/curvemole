"""A real window and normal mapping dialog receive all 100 selected files."""
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def wait_for(path, process, timeout=30):
    deadline = time.monotonic() + timeout
    while not path.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(.02)
    assert path.exists(), f'Desktop did not reach {path.name}'


@pytest.mark.parametrize('separate_launches', [False, True])
def test_one_import_batch_for_100_files(tmp_path, separate_launches):
    script = Path(__file__).with_name('desktop_open_process.py')
    directory = tmp_path / 'ipc'
    output = tmp_path / 'result.json'
    paths = [tmp_path / f'spettro λ {index}.xy' for index in range(100)]
    for path in paths:
        path.write_text('0 1\n1 2\n2 4\n3 3\n4 1\n')
    initial = paths[:1] if separate_launches else paths
    primary = subprocess.Popen([sys.executable, str(script), 'primary', str(directory), str(output),
                                '100', *map(str, initial)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        wait_for(output.with_suffix('.ready'), primary)
        if separate_launches:
            # Deliberately start the rest after the first mapping dialog is open,
            # exercising the late-arrival path used by per-file Windows launches.
            wait_for(output.with_suffix('.dialog'), primary)
            def forward(path):
                process = subprocess.run([sys.executable, str(script), 'forward', str(directory), str(output), str(path)],
                                         capture_output=True, timeout=40)
                assert process.returncode == 0, process.stderr.decode(errors='replace')
            with ThreadPoolExecutor(max_workers=16) as pool:
                list(pool.map(forward, paths[1:]))
        stdout, stderr = primary.communicate(timeout=80)
        assert primary.returncode == 0, (stdout, stderr)
        result = json.loads(output.read_text(encoding='utf-8'))
        assert result['errors'] == []
        assert result['windows'] == 1
        assert result['dialogs'] == 1
        assert len(result['paths']) == 100
        assert set(result['paths']) == set(map(str, paths))
    finally:
        if primary.poll() is None:
            primary.kill()
        primary.wait()
