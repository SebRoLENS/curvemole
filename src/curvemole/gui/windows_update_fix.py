"""Robust Windows self-update finalization for PyInstaller onefile builds."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QApplication, QMessageBox

from curvemole.gui import updates as _updates
from curvemole.gui.updates import ReleaseAsset, UpdateController


def _powershell_quote(value: str | Path) -> str:
    """Quote one literal value for a single-quoted PowerShell string."""
    return "'" + str(value).replace("'", "''") + "'"


def windows_update_script(
    current: Path,
    destination: Path,
    downloaded: Path,
    *,
    parent_pid: int,
    restart: bool = True,
) -> str:
    """Build the detached PowerShell helper used after the GUI exits.

    PyInstaller onefile uses a bootloader process in addition to the Python
    process. Waiting only for ``os.getpid()`` can therefore race the executable
    lock. The helper waits until both the parent PID and every process running
    the old executable have disappeared before touching either executable.
    """
    parent = current.parent
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$parentPid = {int(parent_pid)}",
        f"$current = {_powershell_quote(current)}",
        f"$destination = {_powershell_quote(destination)}",
        f"$downloaded = {_powershell_quote(downloaded)}",
        f"$workingDirectory = {_powershell_quote(parent)}",
        "$scriptPath = $MyInvocation.MyCommand.Path",
        "$logPath = Join-Path ([System.IO.Path]::GetTempPath()) ('CurveMole-update-' + $parentPid + '.log')",
        "function Write-UpdateLog([string]$message) {",
        "  Add-Content -LiteralPath $logPath -Value ((Get-Date -Format o) + ' ' + $message) -Encoding UTF8",
        "}",
        "function OldExecutableStillRunning {",
        "  $alive = $false",
        "  Get-Process -ErrorAction SilentlyContinue | ForEach-Object {",
        "    try {",
        "      if ($_.Path -and [string]::Equals($_.Path, $current, [System.StringComparison]::OrdinalIgnoreCase)) {",
        "        $alive = $true",
        "      }",
        "    } catch {}",
        "  }",
        "  return $alive",
        "}",
        "$success = $false",
        "try {",
        "  Write-UpdateLog ('Starting update from ' + $current + ' to ' + $destination)",
        "  $exitDeadline = (Get-Date).AddSeconds(90)",
        "  while ((Get-Date) -lt $exitDeadline) {",
        "    $parentAlive = $null -ne (Get-Process -Id $parentPid -ErrorAction SilentlyContinue)",
        "    if (-not $parentAlive -and -not (OldExecutableStillRunning)) { break }",
        "    Start-Sleep -Milliseconds 250",
        "  }",
        "  if (($null -ne (Get-Process -Id $parentPid -ErrorAction SilentlyContinue)) -or (OldExecutableStillRunning)) {",
        "    throw 'The previous CurveMole process did not release the executable in time.'",
        "  }",
        "",
        "  $moved = $false",
        "  $moveDeadline = (Get-Date).AddSeconds(30)",
        "  while (-not $moved -and (Get-Date) -lt $moveDeadline) {",
        "    try {",
        "      if (Test-Path -LiteralPath $destination) { Remove-Item -LiteralPath $destination -Force -ErrorAction Stop }",
        "      Move-Item -LiteralPath $downloaded -Destination $destination -Force -ErrorAction Stop",
        "      $moved = $true",
        "    } catch {",
        "      Start-Sleep -Milliseconds 250",
        "    }",
        "  }",
        "  if (-not $moved -or -not (Test-Path -LiteralPath $destination)) {",
        "    throw 'Could not move the verified update to its final executable name.'",
        "  }",
        "",
        "  if (-not [string]::Equals($current, $destination, [System.StringComparison]::OrdinalIgnoreCase)) {",
        "    $deleteDeadline = (Get-Date).AddSeconds(30)",
        "    while ((Test-Path -LiteralPath $current) -and (Get-Date) -lt $deleteDeadline) {",
        "      try { Remove-Item -LiteralPath $current -Force -ErrorAction Stop } catch { Start-Sleep -Milliseconds 250 }",
        "    }",
        "    if (Test-Path -LiteralPath $current) { throw 'The previous CurveMole executable could not be removed.' }",
        "  }",
    ]
    if restart:
        lines.append("  Start-Process -FilePath $destination -WorkingDirectory $workingDirectory")
    lines.extend(
        [
            "  Write-UpdateLog 'Update completed successfully.'",
            "  $success = $true",
            "} catch {",
            "  Write-UpdateLog ('FAILED: ' + $_.Exception.Message)",
            "  Remove-Item -LiteralPath $downloaded -Force -ErrorAction SilentlyContinue",
            "} finally {",
            "  Remove-Item -LiteralPath $scriptPath -Force -ErrorAction SilentlyContinue",
            "}",
            "if (-not $success) { exit 1 }",
            "exit 0",
            "",
        ]
    )
    return "\n".join(lines)


def _cleanup_stale_update_files(current: Path | None) -> None:
    if current is None:
        return
    for pattern in (".curvemole-update-*.ps1", ".curvemole-update-*.cmd", ".CurveMole-*.download-*"):
        for path in current.parent.glob(pattern):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _install_windows_download(
    controller: UpdateController,
    downloaded: Path,
    asset: ReleaseAsset,
    latest: str,
) -> None:
    current = _updates._running_desktop_binary()
    if current is None:
        raise RuntimeError(controller.window.tr("The running CurveMole executable could not be identified."))
    if not controller.window._confirm_discard_or_save():
        downloaded.unlink(missing_ok=True)
        return

    destination = current.parent / asset.name
    helper = current.parent / f".curvemole-update-{os.getpid()}.ps1"
    helper.write_text(
        windows_update_script(
            current,
            destination,
            downloaded,
            parent_pid=os.getpid(),
        ),
        encoding="utf-8-sig",
    )

    QMessageBox.information(
        controller.window,
        controller.window.tr("CurveMole updated"),
        controller.window.tr(
            "The update is verified. CurveMole will close, wait for the Windows executable to be fully released, replace the old executable, remove it from disk, and start the new version."
        ),
    )

    creationflags = 0
    creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
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
            close_fds=True,
            creationflags=creationflags,
        )
    except Exception:
        helper.unlink(missing_ok=True)
        raise

    # The save/discard decision was already handled above. Closing the real main
    # window gives Qt and PyInstaller a clean shutdown path before the helper acts.
    controller.window.project.dirty = False
    controller.window.close()
    app = QApplication.instance()
    if app is not None:
        app.quit()


def _install_fix() -> None:
    if getattr(UpdateController, "_curvemole_windows_update_fix", False):
        return

    original_init = UpdateController.__init__
    original_install = UpdateController._install_download

    def init(controller: UpdateController, window: Any) -> None:
        if platform.system() == "Windows":
            _cleanup_stale_update_files(_updates._running_desktop_binary())
        original_init(controller, window)

    def install_download(
        controller: UpdateController,
        downloaded: Path,
        asset: ReleaseAsset,
        latest: str,
    ) -> None:
        if platform.system() != "Windows":
            original_install(controller, downloaded, asset, latest)
            return
        _install_windows_download(controller, downloaded, asset, latest)

    UpdateController.__init__ = init
    UpdateController._install_download = install_download
    UpdateController._curvemole_windows_update_fix = True


_install_fix()
