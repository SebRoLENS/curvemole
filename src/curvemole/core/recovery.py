"""Distinct autosave recovery rotation for modified projects."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock

from curvemole.core.project import Project
from curvemole.core.serialization import (
    ProjectSaveSnapshot,
    load_project,
    save_project,
    validate_project_archive,
)


@dataclass(slots=True)
class RecoveryManager:
    directory: Path
    keep: int = 3
    _last_revision: int = -1
    _last_project_id: str | None = None
    _last_saved_at: datetime | None = None
    _generations: dict[str, int] = field(default_factory=dict, repr=False)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def __post_init__(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)

    def _needs_autosave(self, project: Project | ProjectSaveSnapshot) -> bool:
        return not (project.read_only or not project.dirty or (
            project.id == self._last_project_id and project.revision == self._last_revision
        ))

    def needs_autosave(self, project: Project | ProjectSaveSnapshot) -> bool:
        with self._lock:
            return self._needs_autosave(project)

    def generation(self, project_id: str) -> int:
        with self._lock:
            return self._generations.get(project_id, 0)

    def cancel_pending(self, project_id: str) -> None:
        """Invalidate in-flight snapshots without removing completed backups."""
        with self._lock:
            self._generations[project_id] = self._generations.get(project_id, 0) + 1

    def autosave(
        self, project: Project | ProjectSaveSnapshot, *, generation: int | None = None,
    ) -> Path | None:
        with self._lock:
            current_generation = self._generations.get(project.id, 0)
            if generation is None:
                generation = current_generation
            if generation != current_generation or not self._needs_autosave(project):
                return None
            revision = project.revision
            saved_at = datetime.now(UTC)
            if self._last_saved_at is not None:
                saved_at = max(saved_at, self._last_saved_at + timedelta(microseconds=1))
            while True:
                stamp = saved_at.strftime("%Y%m%dT%H%M%S%fZ")
                destination = self.directory / f"{project.id}.recovery-{stamp}.fitproj"
                if not destination.exists():
                    break
                saved_at += timedelta(microseconds=1)
            self._last_saved_at = saved_at

        # A verified pending file is published only if Save/Discard/close has not
        # invalidated this request in the meantime. Heavy work never holds the lock.
        descriptor, pending_name = tempfile.mkstemp(prefix=".autosave-", suffix=".fitproj", dir=self.directory)
        os.close(descriptor)
        pending = Path(pending_name)
        try:
            save_project(project, pending, update_project_path=False)
            with self._lock:
                if generation != self._generations.get(project.id, 0):
                    return None
                os.replace(pending, destination)
                self._last_revision = revision
                self._last_project_id = project.id
        finally:
            pending.unlink(missing_ok=True)
        self._rotate(project.id)
        return destination

    def candidates(self, project_id: str | None = None) -> list[Path]:
        pattern = f"{project_id}.recovery-*.fitproj" if project_id else "*.recovery-*.fitproj"
        dated = []
        for path in self.directory.glob(pattern):
            try:
                dated.append((path.stat().st_mtime_ns, path.name, path))
            except FileNotFoundError:
                # A foreground Save/Discard can clear files during background rotation.
                continue
        candidates = [item[2] for item in sorted(dated, reverse=True)]
        return [path for path in candidates if not validate_project_archive(path, raise_on_error=False)]

    def recover(self, path: str | Path) -> Project:
        project = load_project(path)
        project.dirty = True
        project.path = None
        with self._lock:
            self._generations[project.id] = self._generations.get(project.id, 0) + 1
            self._last_revision = -1
            self._last_project_id = None
        return project

    def clear(self, project_id: str) -> None:
        with self._lock:
            self._generations[project_id] = self._generations.get(project_id, 0) + 1
            for path in self.directory.glob(f"{project_id}.recovery-*.fitproj"):
                path.unlink(missing_ok=True)
            if self._last_project_id == project_id:
                self._last_revision = -1
                self._last_project_id = None

    def _rotate(self, project_id: str) -> None:
        for obsolete in self.candidates(project_id)[self.keep :]:
            obsolete.unlink(missing_ok=True)
