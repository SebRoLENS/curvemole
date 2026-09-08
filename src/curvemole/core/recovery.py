"""Distinct autosave recovery rotation for modified projects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from curvemole.core.project import Project
from curvemole.core.serialization import load_project, save_project, validate_project_archive


@dataclass(slots=True)
class RecoveryManager:
    directory: Path
    keep: int = 3
    _last_revision: int = -1
    _last_project_id: str | None = None
    _last_saved_at: datetime | None = None

    def __post_init__(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)

    def autosave(self, project: Project) -> Path | None:
        if project.read_only or not project.dirty or (
            project.id == self._last_project_id and project.revision == self._last_revision
        ):
            return None
        saved_at = datetime.now(UTC)
        if self._last_saved_at is not None:
            saved_at = max(saved_at, self._last_saved_at + timedelta(microseconds=1))
        while True:
            stamp = saved_at.strftime("%Y%m%dT%H%M%S%fZ")
            destination = self.directory / f"{project.id}.recovery-{stamp}.fitproj"
            if not destination.exists():
                break
            saved_at += timedelta(microseconds=1)
        save_project(project, destination, update_project_path=False)
        self._last_revision = project.revision
        self._last_project_id = project.id
        self._last_saved_at = saved_at
        self._rotate(project.id)
        return destination

    def candidates(self, project_id: str | None = None) -> list[Path]:
        pattern = f"{project_id}.recovery-*.fitproj" if project_id else "*.recovery-*.fitproj"
        candidates = sorted(self.directory.glob(pattern), key=lambda path: (path.stat().st_mtime_ns, path.name), reverse=True)
        return [path for path in candidates if not validate_project_archive(path, raise_on_error=False)]

    def recover(self, path: str | Path) -> Project:
        project = load_project(path)
        project.dirty = True
        project.path = None
        self._last_revision = -1
        self._last_project_id = None
        return project

    def clear(self, project_id: str) -> None:
        for path in self.directory.glob(f"{project_id}.recovery-*.fitproj"):
            path.unlink(missing_ok=True)
        if self._last_project_id == project_id:
            self._last_revision = -1
            self._last_project_id = None

    def _rotate(self, project_id: str) -> None:
        for obsolete in self.candidates(project_id)[self.keep :]:
            obsolete.unlink(missing_ok=True)
