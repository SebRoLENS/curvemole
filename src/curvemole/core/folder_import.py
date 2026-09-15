"""Explicit folder-import session: stable files, substring filtering, no duplicates."""

from __future__ import annotations

import time
from pathlib import Path


class FolderScan:
    def __init__(self, folder, contains="", *, include_existing=False, modified=False, settle=2.0):
        self.folder = Path(folder).resolve()
        if not self.folder.is_dir():
            raise ValueError("Choose an existing folder.")
        self.contains = contains.casefold()
        self.modified = modified
        self.settle = max(0.1, float(settle))
        self.observed = {}
        self.consumed = {}
        self.failed = {}
        if not include_existing:
            self.consumed = dict(self.files())

    def files(self):
        for path in sorted(self.folder.iterdir()):
            if path.is_symlink() or not path.is_file() or self.contains not in path.name.casefold():
                continue
            if path.name.startswith(".") or path.suffix.lower() in {
                ".tmp",
                ".part",
                ".partial",
                ".fitproj",
            }:
                continue
            try:
                stat = path.stat()
                yield path, (stat.st_size, stat.st_mtime_ns)
            except OSError:
                continue

    def ready(self, now=None):
        now = time.monotonic() if now is None else now
        ready = []
        for path, signature in self.files():
            if signature[0] == 0 or self.failed.get(path) == signature:
                continue
            if path in self.consumed and (not self.modified or self.consumed[path] == signature):
                continue
            previous = self.observed.get(path)
            if previous is None or previous[0] != signature:
                self.observed[path] = (signature, now)
            elif now - previous[1] >= self.settle:
                ready.append((path, signature))
        return ready
