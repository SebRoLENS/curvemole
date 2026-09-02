"""GitHub release checks, version badge, and desktop self-update support."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QSettings, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication, QMessageBox, QToolButton

from curvemole.version import __version__

RELEASE_API = "https://api.github.com/repos/SebRoLENS/curvemole/releases/latest"
RELEASE_PAGE = "https://github.com/SebRoLENS/curvemole/releases"
CHECK_INTERVAL_MS = 60 * 60 * 1000


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    url: str
    digest: str = ""
    size: int = 0


def semantic_version(value: str) -> tuple[int, int, int] | None:
    """Parse the supported three-component semantic version form."""
    import re

    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", value.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def update_kind(current: tuple[int, int, int], latest: tuple[int, int, int]) -> str:
    """Classify an available update according to CurveMole's version policy."""
    if latest[0] != current[0]:
        return "major"
    if latest[1] != current[1]:
        return "minor"
    return "patch"


def should_notify(latest: str, already_notified: str) -> bool:
    """Automatic update notifications are shown only once for each release."""
    return latest != already_notified


def asset_suffix(system: str, machine: str) -> str | None:
    """Return the release asset suffix that can safely self-replace this build."""
    architecture = machine.lower()
    if architecture not in {"x86_64", "amd64"}:
        return None
    if system == "Linux":
        return "-linux-x86_64.AppImage"
    if system == "Windows":
        return "-windows-x86_64.exe"
    return None


def _running_desktop_binary() -> Path | None:
    system = platform.system()
    if system == "Linux":
        appimage = os.environ.get("APPIMAGE", "").strip()
        if appimage:
            path = Path(appimage).expanduser().absolute()
            if path.is_file():
                return path
        return None
    if system == "Windows" and getattr(sys, "frozen", False):
        path = Path(sys.executable).absolute()
        if path.is_file():
            return path
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class UpdateController(QObject):
    """Own the visible version state and the release-update lifecycle."""

    _BADGE_STYLES = {
        "checking": "background:#6b7280;color:white;border-radius:7px;padding:2px 8px;",
        "current": "background:#2e7d32;color:white;border-radius:7px;padding:2px 8px;",
        "patch": "background:#f9a825;color:#111;border-radius:7px;padding:2px 8px;",
        "minor": "background:#c62828;color:white;border-radius:7px;padding:2px 8px;",
        "major": "background:#b71c1c;color:white;border-radius:7px;padding:2px 8px;font-weight:bold;",
        "error": "background:#6b7280;color:white;border-radius:7px;padding:2px 8px;",
    }

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self.settings = QSettings("CurveMole", "CurveMole")
        self.manager = QNetworkAccessManager(self)
        self._release_reply: QNetworkReply | None = None
        self._download_reply: QNetworkReply | None = None
        self._download_handle: Any | None = None
        self._download_path: Path | None = None
        self._download_asset: ReleaseAsset | None = None
        self._download_version = ""
        self._latest_payload: dict[str, Any] | None = None
        self._latest_version: tuple[int, int, int] | None = None

        # MainWindow versions before this controller had a separate checker. Stop
        # its periodic timer and make its already-scheduled startup callback a no-op.
        legacy_timer = getattr(window, "update_check_timer", None)
        if legacy_timer is not None:
            legacy_timer.stop()
        self.settings.setValue("updates/last_check", time.time())

        self.badge = QToolButton(window)
        self.badge.setAutoRaise(False)
        self.badge.setText(f"v{__version__}")
        self.badge.setToolTip(window.tr("Checking the latest CurveMole version…"))
        self.badge.setStyleSheet(self._BADGE_STYLES["checking"])
        self.badge.clicked.connect(lambda checked=False: self._badge_clicked())
        window.statusBar().addPermanentWidget(self.badge)

        # Reuse the existing Help menu action, but route it through the new checker.
        try:
            window.update_action.triggered.disconnect()
        except (RuntimeError, TypeError):
            pass
        window.update_action.triggered.connect(
            lambda checked=False: self.check(force=True)
        )

        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_INTERVAL_MS)
        self.timer.timeout.connect(self.check)
        self.timer.start()
        QTimer.singleShot(0, self.check)

    def check(self, *, force: bool = False) -> None:
        """Check GitHub now; automatic calls are never throttled below one hour."""
        if self._release_reply is not None:
            if force:
                self.window._notify(self.window.tr("An update check is already in progress."))
            return

        self.settings.setValue("updates/last_check", time.time())
        request = QNetworkRequest(QUrl(RELEASE_API))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", f"CurveMole/{__version__}".encode("ascii"))
        request.setTransferTimeout(10_000)
        reply = self.manager.get(request)
        self._release_reply = reply
        reply.finished.connect(
            lambda reply=reply, force=force: self._release_finished(reply, force)
        )

    def _release_finished(self, reply: QNetworkReply, force: bool) -> None:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                message = self.window.tr("Could not check for CurveMole updates: ") + reply.errorString()
                self.window._log(message)
                self.badge.setToolTip(message)
                if self._latest_version is None:
                    self.badge.setStyleSheet(self._BADGE_STYLES["error"])
                if force:
                    QMessageBox.warning(self.window, self.window.tr("Check for updates"), message)
                return

            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            current = semantic_version(__version__)
            latest = semantic_version(str(payload.get("tag_name", "")))
            if current is None or latest is None:
                raise ValueError(self.window.tr("GitHub returned an unrecognised release version."))

            self._latest_payload = payload
            self._latest_version = latest
            latest_text = ".".join(str(value) for value in latest)
            if latest <= current:
                self._set_badge(
                    "current",
                    self.window.tr("CurveMole is up to date. Installed version: ") + __version__,
                )
                if force:
                    QMessageBox.information(
                        self.window,
                        self.window.tr("Check for updates"),
                        self.window.tr("CurveMole is up to date. Installed version: ") + __version__,
                    )
                return

            kind = update_kind(current, latest)
            self._set_badge(kind, self._badge_tooltip(latest_text, kind))

            notified = str(
                self.settings.value("updates/notified_version", "")
                or self.settings.value("updates/last_notified_version", "")
                or ""
            )
            if force or should_notify(latest_text, notified):
                self._show_update_available(payload, latest_text, kind)
                # Being shown the dialog counts as the one notification for this release.
                self.settings.setValue("updates/notified_version", latest_text)
                self.settings.setValue("updates/last_notified_version", latest_text)
        except Exception as exc:
            self.window._log(f"Update check failed: {exc}")
            if self._latest_version is None:
                self.badge.setStyleSheet(self._BADGE_STYLES["error"])
                self.badge.setToolTip(str(exc))
            if force:
                QMessageBox.warning(self.window, self.window.tr("Check for updates"), str(exc))
        finally:
            self._release_reply = None
            reply.deleteLater()

    def _set_badge(self, state: str, tooltip: str) -> None:
        self.badge.setText(f"v{__version__}")
        self.badge.setStyleSheet(self._BADGE_STYLES[state])
        self.badge.setToolTip(tooltip)

    def _badge_tooltip(self, latest: str, kind: str) -> str:
        if kind == "patch":
            detail = self.window.tr("bug-fix update")
        elif kind == "minor":
            detail = self.window.tr("feature update")
        else:
            detail = self.window.tr("major update")
        return (
            self.window.tr("Installed: ")
            + __version__
            + self.window.tr(" · Latest: ")
            + latest
            + f" ({detail})"
        )

    def _badge_clicked(self) -> None:
        current = semantic_version(__version__)
        if (
            current is not None
            and self._latest_version is not None
            and self._latest_version > current
            and self._latest_payload is not None
        ):
            latest_text = ".".join(str(value) for value in self._latest_version)
            kind = update_kind(current, self._latest_version)
            self._show_update_available(self._latest_payload, latest_text, kind)
            self.settings.setValue("updates/notified_version", latest_text)
            self.settings.setValue("updates/last_notified_version", latest_text)
            return
        self.check(force=True)

    def _release_asset(self, payload: dict[str, Any]) -> ReleaseAsset | None:
        binary = _running_desktop_binary()
        suffix = asset_suffix(platform.system(), platform.machine())
        if binary is None or suffix is None:
            return None
        for raw in payload.get("assets", []):
            name = str(raw.get("name", ""))
            url = str(raw.get("browser_download_url", ""))
            if name.endswith(suffix) and url:
                return ReleaseAsset(
                    name=name,
                    url=url,
                    digest=str(raw.get("digest", "") or ""),
                    size=int(raw.get("size", 0) or 0),
                )
        return None

    def _show_update_available(
        self,
        payload: dict[str, Any],
        latest: str,
        kind: str,
    ) -> None:
        if kind == "patch":
            description = self.window.tr(
                "A bug-fix update is available (x.x.y)."
            )
        elif kind == "minor":
            description = self.window.tr(
                "A feature update is available (x.y.x)."
            )
        else:
            description = self.window.tr(
                "WARNING: the major version has changed (y.x.x). Review compatibility and release notes before updating."
            )

        asset = self._release_asset(payload)
        message = (
            self.window.tr("CurveMole ")
            + latest
            + self.window.tr(" is available. ")
            + description
            + "\n\n"
            + self.window.tr("Updating is recommended.")
        )
        if asset is None:
            message += "\n\n" + self.window.tr(
                "Automatic replacement is not available for this installation. Use the release page instead."
            )

        box = QMessageBox(self.window)
        box.setIcon(
            QMessageBox.Icon.Warning if kind == "major" else QMessageBox.Icon.Information
        )
        box.setWindowTitle(self.window.tr("CurveMole update available"))
        box.setText(message)
        update_button = None
        if asset is not None:
            update_button = box.addButton(
                self.window.tr("Update now"), QMessageBox.ButtonRole.AcceptRole
            )
        release_button = box.addButton(
            self.window.tr("Release notes"), QMessageBox.ButtonRole.ActionRole
        )
        box.addButton(self.window.tr("Later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()

        if update_button is not None and box.clickedButton() is update_button:
            self._download_update(asset, latest)
        elif box.clickedButton() is release_button:
            self.window._open_external(str(payload.get("html_url") or RELEASE_PAGE))

    def _download_update(self, asset: ReleaseAsset, latest: str) -> None:
        if self._download_reply is not None:
            self.window._notify(self.window.tr("An update download is already in progress."))
            return
        if getattr(self.window, "_thread", None) is not None:
            QMessageBox.warning(
                self.window,
                self.window.tr("Update CurveMole"),
                self.window.tr("Finish or cancel the running task before updating CurveMole."),
            )
            return

        current = _running_desktop_binary()
        if current is None:
            QMessageBox.warning(
                self.window,
                self.window.tr("Update CurveMole"),
                self.window.tr("This CurveMole installation cannot replace itself automatically."),
            )
            return
        if not os.access(current.parent, os.W_OK):
            QMessageBox.warning(
                self.window,
                self.window.tr("Update CurveMole"),
                self.window.tr("CurveMole cannot write to its current application folder."),
            )
            return

        download_path = current.parent / f".{asset.name}.download-{os.getpid()}"
        try:
            download_path.unlink(missing_ok=True)
            handle = download_path.open("wb")
        except OSError as exc:
            QMessageBox.warning(self.window, self.window.tr("Update CurveMole"), str(exc))
            return

        request = QNetworkRequest(QUrl(asset.url))
        request.setRawHeader(b"User-Agent", f"CurveMole/{__version__}".encode("ascii"))
        request.setTransferTimeout(120_000)
        reply = self.manager.get(request)
        self._download_reply = reply
        self._download_handle = handle
        self._download_path = download_path
        self._download_asset = asset
        self._download_version = latest

        self.window.progress.setRange(0, 100)
        self.window.progress.setValue(0)
        self.window.progress.setVisible(True)
        self.window.fit_action.setEnabled(False)
        self.window.statusBar().showMessage(
            self.window.tr("Downloading CurveMole ") + latest + "…"
        )
        reply.readyRead.connect(self._drain_download)
        reply.downloadProgress.connect(self._download_progress)
        reply.finished.connect(lambda reply=reply: self._download_finished(reply))

    def _drain_download(self) -> None:
        if self._download_reply is None or self._download_handle is None:
            return
        data = bytes(self._download_reply.readAll())
        if data:
            self._download_handle.write(data)

    def _download_progress(self, received: int, total: int) -> None:
        if total <= 0:
            self.window.progress.setRange(0, 0)
            return
        self.window.progress.setRange(0, 100)
        self.window.progress.setValue(max(0, min(100, round(received * 100 / total))))

    def _download_finished(self, reply: QNetworkReply) -> None:
        path = self._download_path
        asset = self._download_asset
        latest = self._download_version
        try:
            self._drain_download()
            if self._download_handle is not None:
                self._download_handle.flush()
                self._download_handle.close()
                self._download_handle = None

            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise RuntimeError(reply.errorString())
            if path is None or asset is None:
                raise RuntimeError(self.window.tr("The downloaded update could not be located."))

            expected = asset.digest.lower()
            if expected.startswith("sha256:"):
                actual = _sha256(path)
                if actual != expected.split(":", 1)[1]:
                    raise RuntimeError(
                        self.window.tr("The downloaded update failed SHA-256 verification.")
                    )

            self._install_download(path, asset, latest)
        except Exception as exc:
            if path is not None:
                path.unlink(missing_ok=True)
            self.window._log(f"Update download/install failed: {exc}")
            QMessageBox.warning(self.window, self.window.tr("Update CurveMole"), str(exc))
        finally:
            if self._download_handle is not None:
                self._download_handle.close()
                self._download_handle = None
            self._download_reply = None
            self._download_path = None
            self._download_asset = None
            self._download_version = ""
            reply.deleteLater()
            self.window.progress.setVisible(False)
            if getattr(self.window, "_thread", None) is None:
                self.window.fit_action.setEnabled(True)

    def _install_download(self, downloaded: Path, asset: ReleaseAsset, latest: str) -> None:
        current = _running_desktop_binary()
        if current is None:
            raise RuntimeError(self.window.tr("The running CurveMole executable could not be identified."))
        destination = current.parent / asset.name
        system = platform.system()

        if system == "Linux":
            if destination.exists() and destination != current:
                destination.unlink()
            os.replace(downloaded, destination)
            destination.chmod(
                destination.stat().st_mode
                | stat.S_IXUSR
                | stat.S_IXGRP
                | stat.S_IXOTH
            )
            if current != destination and current.exists():
                current.unlink()
            self.timer.stop()
            self.window._log(
                f"Installed CurveMole {latest}: {destination}; removed {current}"
            )
            QMessageBox.information(
                self.window,
                self.window.tr("CurveMole updated"),
                self.window.tr("CurveMole ")
                + latest
                + self.window.tr(
                    " has been installed and the previous AppImage has been removed. Close and reopen CurveMole to use the new version."
                ),
            )
            return

        if system == "Windows":
            if not self.window._confirm_discard_or_save():
                downloaded.unlink(missing_ok=True)
                return
            helper = current.parent / f".curvemole-update-{os.getpid()}.cmd"
            helper.write_text(
                self._windows_helper_script(current, destination, downloaded),
                encoding="utf-8",
            )
            QMessageBox.information(
                self.window,
                self.window.tr("CurveMole updated"),
                self.window.tr(
                    "The update is verified. CurveMole will close, replace the old executable, remove it from disk, and start the new version."
                ),
            )
            creationflags = 0
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
            subprocess.Popen(
                ["cmd.exe", "/c", str(helper)],
                close_fds=True,
                creationflags=creationflags,
            )
            # _confirm_discard_or_save() already handled the user's choice; avoid
            # prompting a second time from MainWindow.closeEvent during restart.
            self.window.project.dirty = False
            QApplication.instance().quit()
            return

        raise RuntimeError(
            self.window.tr("Automatic executable replacement is not supported on this platform.")
        )

    @staticmethod
    def _windows_helper_script(current: Path, destination: Path, downloaded: Path) -> str:
        pid = os.getpid()
        current_text = str(current)
        destination_text = str(destination)
        downloaded_text = str(downloaded)
        return f"""@echo off
setlocal
:wait_for_curvemole
tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL
if not errorlevel 1 (
  >NUL 2>&1 timeout /T 1 /NOBREAK
  goto wait_for_curvemole
)
move /Y "{downloaded_text}" "{destination_text}" >NUL
if errorlevel 1 goto update_failed
if /I not "{current_text}"=="{destination_text}" del /F /Q "{current_text}" >NUL 2>&1
start "" "{destination_text}"
del /F /Q "%~f0" >NUL 2>&1
exit /B 0
:update_failed
exit /B 1
"""
