"""Native desktop integration helpers for packaged CurveMole builds."""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path

DESKTOP_FILENAME = "curvemole.desktop"
MIME_TYPE = "application/x-curvemole-project"
MANAGED_MARKER = "X-CurveMole-Managed=true"


@dataclass(frozen=True, slots=True)
class LinuxIntegration:
    """Paths and migration information for one Linux desktop integration."""

    appimage: Path
    desktop_file: Path
    icon_file: Path
    mime_file: Path
    adopted_existing_launcher: bool = False
    backup_file: Path | None = None


def _xdg_data_home() -> Path:
    configured = os.environ.get("XDG_DATA_HOME", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(user_data_path("", appauthor=False))


def _desktop_exec(path: Path) -> str | None:
    """Return an existing desktop command without field-code arguments."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if not line.startswith("Exec="):
            continue
        value = line.removeprefix("Exec=").strip()
        for field_code in ("%f", "%F", "%u", "%U"):
            value = value.replace(field_code, "")
        return value.strip() or None
    return None


def _desktop_quote(path: Path) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _command_is_usable(command: str) -> bool:
    try:
        executable = shlex.split(command)[0]
    except (IndexError, ValueError):
        return False
    if Path(executable).is_absolute():
        return Path(executable).exists()
    return shutil.which(executable) is not None


def current_appimage() -> Path | None:
    """Return the running AppImage path when Linux exposes it."""
    value = os.environ.get("APPIMAGE", "").strip()
    if not value:
        return None
    path = Path(value).expanduser().absolute()
    return path if path.is_file() else None


def linux_integration_is_current(
    *, data_home: Path | None = None, home: Path | None = None
) -> bool:
    """Check whether the per-user launcher and MIME registration are complete."""
    root = data_home or _xdg_data_home()
    desktop = root / "applications" / DESKTOP_FILENAME
    mime = root / "mime" / "packages" / "curvemole.xml"
    managed_appimage = (home or Path.home()).expanduser() / ".local" / "opt" / "CurveMole" / "CurveMole.AppImage"
    try:
        text = desktop.read_text(encoding="utf-8")
    except OSError:
        return False
    command = _desktop_exec(desktop)
    try:
        executable = Path(shlex.split(command or "")[0]).expanduser()
    except (IndexError, ValueError):
        return False
    return (
        MANAGED_MARKER in text
        and MIME_TYPE in text
        and ("%f" in text or "%F" in text)
        and mime.is_file()
        and managed_appimage.is_file()
        and executable.is_absolute()
        and executable.resolve() == managed_appimage.resolve()
    )


def integrate_linux_desktop(
    *,
    appimage: Path | None = None,
    icon_source: Path,
    home: Path | None = None,
    data_home: Path | None = None,
    refresh_databases: bool = True,
) -> LinuxIntegration:
    """Install or safely adopt per-user Linux desktop integration.

    An existing manual ``curvemole.desktop`` launcher is adopted when its Exec
    command still resolves.  The file is backed up once before CurveMole starts
    managing it.  System launchers are never modified and no root access is used.
    """
    if platform.system() != "Linux":
        raise RuntimeError("Linux desktop integration is only available on Linux.")
    source = (appimage or current_appimage())
    if source is None or not source.is_file():
        raise RuntimeError("Run the packaged CurveMole AppImage before integrating it.")
    if not icon_source.is_file():
        raise RuntimeError("The bundled CurveMole icon could not be found.")

    user_home = (home or Path.home()).expanduser()
    root = (data_home or _xdg_data_home()).expanduser()
    applications = root / "applications"
    icons = root / "icons" / "hicolor" / "256x256" / "apps"
    mime_packages = root / "mime" / "packages"
    for directory in (applications, icons, mime_packages):
        directory.mkdir(parents=True, exist_ok=True)

    desktop_file = applications / DESKTOP_FILENAME
    existing_command = _desktop_exec(desktop_file)
    if existing_command is None:
        for candidate in (
            Path("/usr/local/share/applications") / DESKTOP_FILENAME,
            Path("/usr/share/applications") / DESKTOP_FILENAME,
        ):
            existing_command = _desktop_exec(candidate)
            if existing_command:
                break

    adopted = bool(existing_command and _command_is_usable(existing_command))
    installed_appimage = user_home / ".local" / "opt" / "CurveMole" / "CurveMole.AppImage"
    # A pre-existing manual launcher is adopted and backed up, but its command
    # must not be retained: it may point to an older CurveMole executable that
    # does not understand desktop file-open arguments.  Always install and use
    # the currently running AppImage as the managed launcher target.
    installed_appimage.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != installed_appimage.resolve():
        temporary = installed_appimage.with_suffix(".AppImage.new")
        shutil.copy2(source, temporary)
        os.replace(temporary, installed_appimage)
    installed_appimage.chmod(
        installed_appimage.stat().st_mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
    )
    launch_command = _desktop_quote(installed_appimage)
    effective_appimage = installed_appimage

    backup: Path | None = None
    if desktop_file.exists():
        old_text = desktop_file.read_text(encoding="utf-8")
        if MANAGED_MARKER not in old_text:
            backup = desktop_file.with_suffix(".desktop.pre-curvemole-integration.bak")
            if not backup.exists():
                shutil.copy2(desktop_file, backup)

    desktop_text = f"""[Desktop Entry]
Type=Application
Name=CurveMole
Comment=Modular Scientific Curve Fitting
Exec={launch_command} %f
Icon=curvemole
Categories=Science;Education;
Terminal=false
StartupNotify=true
StartupWMClass=CurveMole
MimeType={MIME_TYPE};
{MANAGED_MARKER}
"""
    desktop_file.write_text(desktop_text, encoding="utf-8")
    desktop_file.chmod(0o644)

    icon_file = icons / "curvemole.png"
    shutil.copy2(icon_source, icon_file)
    icon_file.chmod(0o644)

    mime_file = mime_packages / "curvemole.xml"
    mime_file.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-curvemole-project">
    <comment>CurveMole project</comment>
    <glob pattern="*.fitproj"/>
  </mime-type>
</mime-info>
""",
        encoding="utf-8",
    )
    mime_file.chmod(0o644)

    if refresh_databases:
        commands = (
            ("update-mime-database", str(root / "mime")),
            ("update-desktop-database", str(applications)),
            ("gtk-update-icon-cache", "-f", "-t", str(root / "icons" / "hicolor")),
        )
        for command in commands:
            if shutil.which(command[0]) is None:
                continue
            subprocess.run(command, check=False, capture_output=True, timeout=30)

    return LinuxIntegration(
        appimage=effective_appimage,
        desktop_file=desktop_file,
        icon_file=icon_file,
        mime_file=mime_file,
        adopted_existing_launcher=adopted,
        backup_file=backup,
    )
