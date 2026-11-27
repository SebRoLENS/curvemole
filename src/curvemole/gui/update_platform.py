"""Platform helpers shared by the update controller and the Windows updater.

Kept free of both modules so that ``updates`` and ``updates_windows`` do not
import each other.
"""

from __future__ import annotations

import hashlib
import os
import platform
import sys
from pathlib import Path


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
