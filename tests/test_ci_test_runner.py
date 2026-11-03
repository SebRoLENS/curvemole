"""CI worker termination must preserve pytest results and completed teardown."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "scripts/run_ci_tests.py"


def run_worker(directory, args, *, hard_exit, pythonpath=None):
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    if pythonpath is not None:
        env["PYTHONPATH"] = str(pythonpath)
    command = (
        f"import runpy; runner = runpy.run_path({str(RUNNER)!r}); "
        f"status = runner['main']({args!r}, hard_exit={hard_exit!r}); raise SystemExit(status)"
    )
    return subprocess.run([sys.executable, "-c", command], cwd=directory, env=env,
                          capture_output=True, text=True, timeout=20)


@pytest.mark.parametrize("status", [0, 1, 2, 3, 4, 5])
def test_completed_worker_preserves_every_pytest_exit_status(tmp_path, status):
    (tmp_path / "pytest.py").write_text(
        "import atexit\nfrom pathlib import Path\n"
        "atexit.register(lambda: Path('interpreter-exit').write_text('ran'))\n"
        "def main(args):\n"
        "    assert args == ['-q', 'example']\n"
        "    print('test output was flushed')\n"
        f"    return {status}\n", encoding="utf-8")
    result = run_worker(tmp_path, ["-q", "example"], hard_exit=True, pythonpath=tmp_path)
    assert result.returncode == status, result.stderr
    assert "test output was flushed" in result.stdout
    assert f"pytest.main returned {status}" in result.stdout
    assert not (tmp_path / "interpreter-exit").exists()


@pytest.mark.parametrize("success", [True, False])
def test_real_pytest_finalizes_fixtures_and_plugins_before_worker_exit(tmp_path, success):
    (tmp_path / "conftest.py").write_text(
        "import atexit\nfrom pathlib import Path\nimport pytest\n"
        "atexit.register(lambda: Path('interpreter-exit').write_text('ran'))\n"
        "def record(text):\n"
        "    with open('completed', 'a') as stream: stream.write(text + '\\n')\n"
        "@pytest.fixture\n"
        "def resource():\n"
        "    yield\n"
        "    record('fixture finalized')\n"
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    record('session status=' + str(int(exitstatus)))\n"
        "def pytest_unconfigure(config):\n"
        "    record('plugins finalized')\n", encoding="utf-8")
    (tmp_path / "test_example.py").write_text(
        f"def test_example(resource):\n    assert {success!r}\n", encoding="utf-8")
    result = run_worker(tmp_path, ["-q", "test_example.py"], hard_exit=True)
    expected = 0 if success else 1
    assert result.returncode == expected, result.stdout + result.stderr
    assert (tmp_path / "completed").read_text().splitlines() == [
        "fixture finalized", f"session status={expected}", "plugins finalized"]
    assert not (tmp_path / "interpreter-exit").exists()


def test_normal_exit_mode_keeps_interpreter_cleanup(tmp_path):
    (tmp_path / "pytest.py").write_text(
        "import atexit\nfrom pathlib import Path\n"
        "atexit.register(lambda: Path('interpreter-exit').write_text('ran'))\n"
        "def main(args): return 0\n", encoding="utf-8")
    result = run_worker(tmp_path, [], hard_exit=False, pythonpath=tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "interpreter-exit").read_text() == "ran"
