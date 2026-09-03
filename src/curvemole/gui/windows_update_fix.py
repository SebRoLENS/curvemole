"""Robust Windows self-update finalization for PyInstaller onefile builds."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtWidgets import QApplication, QMessageBox

from curvemole.gui import updates as _updates
from curvemole.gui.updates import ReleaseAsset, UpdateController

_WINDOWS_RELEASE_GLOB = "CurveMole-*-windows-x86_64.exe"


def _powershell_quote(value: str | Path) -> str:
    """Quote one literal value for a single-quoted PowerShell string."""
    return "'" + str(value).replace("'", "''") + "'"


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _windows_temp_download_path(asset: ReleaseAsset, *, pid: int | None = None) -> Path:
    """Keep partial Windows downloads outside the application directory."""
    process_id = os.getpid() if pid is None else int(pid)
    safe_name = Path(asset.name).name
    return Path(tempfile.gettempdir()) / f"CurveMole-update-{process_id}-{safe_name}.part"


def windows_update_script(
    current: Path,
    destination: Path,
    source: Path,
    *,
    parent_pid: int,
    restart: bool = True,
    source_preinstalled: bool = False,
    expected_sha256: str = "",
) -> str:
    """Build the post-exit PowerShell finalizer for a Windows onefile update.

    For normal versioned releases the verified new executable is staged at its
    final filename *before* the GUI exits.  The helper therefore only has to
    wait for the old PyInstaller process tree to release the previous file,
    remove every obsolete versioned CurveMole executable, and restart the new
    one.  This avoids leaving a dot-prefixed partial download beside the app.
    """
    parent = current.parent
    same_destination = _same_path(current, destination)
    expected = expected_sha256.lower().removeprefix("sha256:")
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$parentPid = {int(parent_pid)}",
        f"$current = {_powershell_quote(current)}",
        f"$destination = {_powershell_quote(destination)}",
        f"$source = {_powershell_quote(source)}",
        f"$workingDirectory = {_powershell_quote(parent)}",
        f"$sourcePreinstalled = ${str(bool(source_preinstalled)).lower()}",
        f"$sameDestination = ${str(bool(same_destination)).lower()}",
        f"$expectedSha256 = {_powershell_quote(expected)}",
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
        "function Remove-WithRetry([string]$path, [int]$seconds = 120) {",
        "  if (-not (Test-Path -LiteralPath $path)) { return }",
        "  $deadline = (Get-Date).AddSeconds($seconds)",
        "  while ((Test-Path -LiteralPath $path) -and (Get-Date) -lt $deadline) {",
        "    try {",
        "      Remove-Item -LiteralPath $path -Force -ErrorAction Stop",
        "    } catch {",
        "      Start-Sleep -Milliseconds 250",
        "    }",
        "  }",
        "  if (Test-Path -LiteralPath $path) { throw ('Could not remove old executable: ' + $path) }",
        "}",
        "$success = $false",
        "try {",
        "  Write-UpdateLog ('Starting update from ' + $current + ' to ' + $destination)",
        "  $exitDeadline = (Get-Date).AddSeconds(120)",
        "  while ((Get-Date) -lt $exitDeadline) {",
        "    $parentAlive = $null -ne (Get-Process -Id $parentPid -ErrorAction SilentlyContinue)",
        "    if (-not $parentAlive -and -not (OldExecutableStillRunning)) { break }",
        "    Start-Sleep -Milliseconds 250",
        "  }",
        "  if (($null -ne (Get-Process -Id $parentPid -ErrorAction SilentlyContinue)) -or (OldExecutableStillRunning)) {",
        "    throw 'The previous CurveMole process did not release the executable in time.'",
        "  }",
        "",
        "  if (-not $sourcePreinstalled) {",
        "    if (-not (Test-Path -LiteralPath $source)) { throw 'The verified update source is missing.' }",
        "    if ($sameDestination) { Remove-WithRetry $current 30 }",
        "    Copy-Item -LiteralPath $source -Destination $destination -Force -ErrorAction Stop",
        "  }",
        "  if (-not (Test-Path -LiteralPath $destination)) { throw 'The new CurveMole executable is missing.' }",
        "  if ($expectedSha256) {",
        "    $actualSha256 = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()",
        "    if ($actualSha256 -ne $expectedSha256) { throw 'The staged update failed SHA-256 verification.' }",
        "  }",
        "",
        "  if (-not $sameDestination) { Remove-WithRetry $current 120 }",
        "",
        f"  Get-ChildItem -LiteralPath $workingDirectory -Filter {_powershell_quote(_WINDOWS_RELEASE_GLOB)} -File -ErrorAction SilentlyContinue | ForEach-Object {{",
        "    if (-not [string]::Equals($_.FullName, $destination, [System.StringComparison]::OrdinalIgnoreCase)) {",
        "      Remove-WithRetry $_.FullName 30",
        "    }",
        "  }",
        "  Get-ChildItem -LiteralPath $workingDirectory -Filter '.CurveMole-*.download-*' -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue",
        "  Get-ChildItem -LiteralPath $workingDirectory -Filter '.curvemole-update-*' -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue",
    ]
    if restart:
        lines.append("  Start-Process -FilePath $destination -WorkingDirectory $workingDirectory")
    lines.extend(
        [
            "  Write-UpdateLog 'Update completed successfully.'",
            "  $success = $true",
            "} catch {",
            "  Write-UpdateLog ('FAILED: ' + $_.Exception.Message)",
            "} finally {",
            "  if (-not [string]::Equals($source, $destination, [System.StringComparison]::OrdinalIgnoreCase)) {",
            "    Remove-Item -LiteralPath $source -Force -ErrorAction SilentlyContinue",
            "  }",
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
    parent = current.parent
    for pattern in (
        ".curvemole-update-*.ps1",
        ".curvemole-update-*.cmd",
        ".CurveMole-*.download-*",
    ):
        for path in parent.glob(pattern):
            with suppress(OSError):
                path.unlink(missing_ok=True)

    # A successful update must leave exactly one versioned Windows executable in
    # the application folder.  Clean leftovers from older updater revisions on
    # the next launch as an additional safety net.
    if current.match(_WINDOWS_RELEASE_GLOB):
        for path in parent.glob(_WINDOWS_RELEASE_GLOB):
            if _same_path(path, current):
                continue
            with suppress(OSError):
                path.unlink(missing_ok=True)


def _download_windows_update(
    controller: UpdateController,
    asset: ReleaseAsset,
    latest: str,
) -> None:
    """Download a Windows update into the system temp directory, never beside the app."""
    if controller._download_reply is not None:
        controller.window._notify(controller.window.tr("An update download is already in progress."))
        return
    if getattr(controller.window, "_thread", None) is not None:
        QMessageBox.warning(
            controller.window,
            controller.window.tr("Update CurveMole"),
            controller.window.tr("Finish or cancel the running task before updating CurveMole."),
        )
        return

    current = _updates._running_desktop_binary()
    if current is None:
        QMessageBox.warning(
            controller.window,
            controller.window.tr("Update CurveMole"),
            controller.window.tr("This CurveMole installation cannot replace itself automatically."),
        )
        return
    if not os.access(current.parent, os.W_OK):
        QMessageBox.warning(
            controller.window,
            controller.window.tr("Update CurveMole"),
            controller.window.tr("CurveMole cannot write to its current application folder."),
        )
        return

    _cleanup_stale_update_files(current)
    download_path = _windows_temp_download_path(asset)
    try:
        download_path.unlink(missing_ok=True)
        handle = download_path.open("wb")
    except OSError as exc:
        QMessageBox.warning(controller.window, controller.window.tr("Update CurveMole"), str(exc))
        return

    request = QNetworkRequest(QUrl(asset.url))
    request.setRawHeader(b"User-Agent", f"CurveMole/{_updates.__version__}".encode("ascii"))
    request.setTransferTimeout(120_000)
    reply = controller.manager.get(request)
    controller._download_reply = reply
    controller._download_handle = handle
    controller._download_path = download_path
    controller._download_asset = asset
    controller._download_version = latest

    controller.window.progress.setRange(0, 100)
    controller.window.progress.setValue(0)
    controller.window.progress.setVisible(True)
    controller.window.fit_action.setEnabled(False)
    controller.window.statusBar().showMessage(
        controller.window.tr("Downloading CurveMole ") + latest + "…"
    )
    reply.readyRead.connect(controller._drain_download)
    reply.downloadProgress.connect(controller._download_progress)
    reply.finished.connect(lambda reply=reply: controller._download_finished(reply))


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

    destination = current.parent / Path(asset.name).name
    source = downloaded
    source_preinstalled = False
    expected = asset.digest.lower().removeprefix("sha256:")

    # Normal versioned updates have a different filename.  Put the verified new
    # executable at its final name while the old one is still running; Windows
    # only locks the current executable, not a new sibling file.  The detached
    # helper then has a very small, reliable job after shutdown.
    if not _same_path(current, destination):
        if destination.exists():
            destination.unlink()
        shutil.copy2(downloaded, destination)
        if expected and _updates._sha256(destination) != expected:
            destination.unlink(missing_ok=True)
            raise RuntimeError(controller.window.tr("The staged update failed SHA-256 verification."))
        downloaded.unlink(missing_ok=True)
        source = destination
        source_preinstalled = True

    helper = Path(tempfile.gettempdir()) / f"CurveMole-update-{os.getpid()}.ps1"
    helper.write_text(
        windows_update_script(
            current,
            destination,
            source,
            parent_pid=os.getpid(),
            source_preinstalled=source_preinstalled,
            expected_sha256=expected,
        ),
        encoding="utf-8-sig",
    )

    QMessageBox.information(
        controller.window,
        controller.window.tr("CurveMole updated"),
        controller.window.tr(
            "The new CurveMole executable is verified and ready. CurveMole will close, remove all older Windows executables from this folder, and start the new version."
        ),
    )

    creationflags = 0
    creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
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
        if source_preinstalled and destination.exists():
            destination.unlink(missing_ok=True)
        raise

    # The save/discard decision was already handled above. Closing the real main
    # window gives Qt and the PyInstaller bootloader a clean shutdown path.
    controller.timer.stop()
    controller.window.project.dirty = False
    controller.window.close()
    app = QApplication.instance()
    if app is not None:
        app.quit()


def _install_fix() -> None:
    if getattr(UpdateController, "_curvemole_windows_update_fix", False):
        return

    original_init = UpdateController.__init__
    original_download = UpdateController._download_update
    original_install = UpdateController._install_download

    def init(controller: UpdateController, window: Any) -> None:
        if platform.system() == "Windows":
            _cleanup_stale_update_files(_updates._running_desktop_binary())
        original_init(controller, window)

    def download_update(
        controller: UpdateController,
        asset: ReleaseAsset,
        latest: str,
    ) -> None:
        if platform.system() != "Windows":
            original_download(controller, asset, latest)
            return
        _download_windows_update(controller, asset, latest)

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
    UpdateController._download_update = download_update
    UpdateController._install_download = install_download
    UpdateController._curvemole_windows_update_fix = True


_install_fix()
