from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from curvemole.gui.updates import (
    ReleaseAsset,
    asset_suffix,
    semantic_version,
    should_notify,
    update_kind,
)
from curvemole.gui.windows_update_fix import (
    _cleanup_stale_update_files,
    _windows_temp_download_path,
    windows_update_script,
)


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


def test_windows_partial_download_is_not_a_dot_file_beside_the_application() -> None:
    asset = ReleaseAsset(
        name="CurveMole-0.12.5-windows-x86_64.exe",
        url="https://example.invalid/CurveMole.exe",
    )
    path = _windows_temp_download_path(asset, pid=123)

    assert path.name == "CurveMole-update-123-CurveMole-0.12.5-windows-x86_64.exe.part"
    assert not path.name.startswith(".")


def test_windows_helper_waits_for_executable_and_removes_all_old_releases(tmp_path: Path) -> None:
    current = tmp_path / "CurveMole-0.12.3-windows-x86_64.exe"
    destination = tmp_path / "CurveMole-0.12.5-windows-x86_64.exe"
    script = windows_update_script(
        current,
        destination,
        destination,
        parent_pid=123,
        source_preinstalled=True,
    )

    assert "OldExecutableStillRunning" in script
    assert "$_.Path" in script
    assert "Remove-WithRetry $current 120" in script
    assert "CurveMole-*-windows-x86_64.exe" in script
    assert ".CurveMole-*.download-*" in script
    assert "Start-Process -FilePath $destination" in script


def test_windows_startup_cleanup_removes_old_versions_and_legacy_partials(tmp_path: Path) -> None:
    current = tmp_path / "CurveMole-0.12.5-windows-x86_64.exe"
    old = tmp_path / "CurveMole-0.12.4-windows-x86_64.exe"
    partial = tmp_path / ".CurveMole-0.12.5-windows-x86_64.exe.download-123"
    helper = tmp_path / ".curvemole-update-123.ps1"
    current.write_bytes(b"current")
    old.write_bytes(b"old")
    partial.write_bytes(b"partial")
    helper.write_text("stale", encoding="utf-8")

    _cleanup_stale_update_files(current)

    assert current.exists()
    assert not old.exists()
    assert not partial.exists()
    assert not helper.exists()


@pytest.mark.skipif(os.name != "nt", reason="Exercises the real Windows PowerShell helper")
def test_windows_helper_keeps_new_executable_and_removes_every_old_release(tmp_path: Path) -> None:
    current = tmp_path / "CurveMole-0.12.3-windows-x86_64.exe"
    stale = tmp_path / "CurveMole-0.12.2-windows-x86_64.exe"
    destination = tmp_path / "CurveMole-0.12.5-windows-x86_64.exe"
    helper = tmp_path / "CurveMole-update-test.ps1"
    current.write_bytes(b"old executable")
    stale.write_bytes(b"older executable")
    destination.write_bytes(b"new executable")
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    helper.write_text(
        windows_update_script(
            current,
            destination,
            destination,
            parent_pid=2_000_000_000,
            restart=False,
            source_preinstalled=True,
            expected_sha256=digest,
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
    assert not stale.exists()
    assert not helper.exists()
