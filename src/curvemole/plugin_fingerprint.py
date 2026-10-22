"""Canonical plugin source fingerprint; standalone stdlib-only build contract."""
from __future__ import annotations

import hashlib
from pathlib import Path


def fingerprint(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*"), key=lambda item: item.relative_to(folder).as_posix()):
        relative = path.relative_to(folder)
        if path.is_symlink():
            raise ValueError("Symlinks are not allowed in plugins")
        if any(part in {"__pycache__", ".pytest_cache"} for part in relative.parts) or path.suffix == ".pyc":
            continue
        if path.is_file():
            digest.update(relative.as_posix().encode())
            digest.update(b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()
