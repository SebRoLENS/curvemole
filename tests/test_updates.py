from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from curvemole.gui.updates import asset_suffix, semantic_version, should_notify, update_kind
from curvemole.gui.windows_update_fix import windows_update_script


def test_semantic_version_and_update_kind() -> None:
    current = semantic_version("0.8.5")
    assert current == (0, 8, 5)
    assert semantic_version("v0.8.6") == (0, 8, 6)
    assert semantic_version("not-a-version") is None

    assert update_kind(current, (0, 8, 6)) == "patch"
    assert update_kind(current, (0, 9, 0)) == "minor"
    assert update_kind(current, (1, 0, 0)) == "major"


def test_automatic_notification_is_once_per_release() -> None:
    assert should_notify("0.9.0", "0.8.5")
    assert not should_notify("0.9.0", "0.9.0")


def test_self_update_asset_suffixes() -> None:
    assert asset_suffix("Linux", "x86_64") == "-linux-x86_64.AppImage"
    assert asset_suffix("Windows", "AMD64") == "-windows-x86_64.exe"
    assert asset_suffix("Darwin", "arm64") is None
    assert asset_suffix("Linux", "aarch64") is None


def test_windows_helper_waits_for_the_executable_not_only_the_python_pid(tmp_path: Path) -> None:
    current = tmp_path / "CurveMole-0.12.1-windows-x86_64.exe"
    destination = tmp_path / "CurveMole-0.12.2-windows-x86_64.exe"
    downloaded = tmp_path / ".CurveMole-0.12.2-windows-x86_64.exe.download-123"
    script = windows_update_script(
        current,
        destination,
        downloaded,
        parent_pid=123,
    )

    assert "OldExecutableStillRunning" in script
    assert "$_.Path" in script
    assert "Move-Item -LiteralPath $downloaded" in script
    assert "Remove-Item -LiteralPath $current" in script
    assert "Start-Process -FilePath $destination" in script


@pytest.mark.skipif(os.name != "nt", reason="Exercises the real Windows PowerShell helper")
def test_windows_helper_replaces_and_removes_files_on_windows(tmp_path: Path) -> None:
    current = tmp_path / "CurveMole-0.12.1-windows-x86_64.exe"
    destination = tmp_path / "CurveMole-0.12.2-windows-x86_64.exe"
    downloaded = tmp_path / ".CurveMole-0.12.2-windows-x86_64.exe.download-123"
    helper = tmp_path / ".curvemole-update-test.ps1"
    current.write_bytes(b"old executable")
    downloaded.write_bytes(b"new executable")
    helper.write_text(
        windows_update_script(
            current,
            destination,
            downloaded,
            parent_pid=2_000_000_000,
            restart=False,
        ),
        encoding="utf-8-sig",
    )

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert destination.read_bytes() == b"new executable"
    assert not current.exists()
    assert not downloaded.exists()
    assert not helper.exists()
