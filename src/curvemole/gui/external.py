"""Open host files and URLs without leaking PyInstaller/AppImage libraries."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping

_BUNDLED_ENVIRONMENT_KEYS = (
    "APPDIR",
    "APPIMAGE",
    "ARGV0",
    "LD_PRELOAD",
    "QML2_IMPORT_PATH",
    "QML_IMPORT_PATH",
    "QT_PLUGIN_PATH",
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    "_MEIPASS2",
)


def host_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    """Restore the environment that existed before the frozen application started."""
    result = dict(os.environ if environment is None else environment)
    original_library_path = result.pop("LD_LIBRARY_PATH_ORIG", None)
    if original_library_path:
        result["LD_LIBRARY_PATH"] = original_library_path
    else:
        result.pop("LD_LIBRARY_PATH", None)
    for key in _BUNDLED_ENVIRONMENT_KEYS:
        result.pop(key, None)
    return result


def open_with_host_application(target: str) -> bool:
    """Launch the desktop opener with a clean environment on Linux."""
    if not sys.platform.startswith("linux"):
        return False
    environment = host_environment()
    command = shutil.which("xdg-open", path=environment.get("PATH"))
    if command is None:
        return False
    subprocess.Popen(  # noqa: S603 - fixed executable and an argument list, never a shell
        [command, target],
        env=environment,
        start_new_session=True,
    )
    return True
