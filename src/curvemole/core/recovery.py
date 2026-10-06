"""Distinct autosave recovery rotation for modified projects."""

from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock

from curvemole.core.process import process_alive
from curvemole.core.project import Project
from curvemole.core.serialization import (
    ProjectSaveSnapshot,
    capture_project_snapshot,
    load_project,
    save_project,
    validate_project_archive,
)


@dataclass(slots=True)
class RecoveryManager:
    directory: Path
    keep: int = 6
    _last_revision: int = -1
    _last_project_id: str | None = None
    _last_saved_at: datetime | None = None
    _generations: dict[str, int] = field(default_factory=dict, repr=False)
    _lock: Lock = field(default_factory=Lock, repr=False)
    cleanup_errors: list[str] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.cleanup_stale_files()

    def cleanup_stale_files(self) -> None:
        """Remove abandoned staging files only when their owning process is gone."""
        for path in self.directory.iterdir():
            match = re.match(r"^\.+autosave-(\d+)-.*\.(?:fitproj|tmp)$", path.name)
            if match and not process_alive(int(match.group(1))):
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    self.cleanup_errors.append(f"{path.name}: {exc}")

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
        descriptor, pending_name = tempfile.mkstemp(prefix=f".autosave-{os.getpid()}-", suffix=".fitproj", dir=self.directory)
        os.close(descriptor)
        pending = Path(pending_name)
        try:
            snapshot = capture_project_snapshot(project) if isinstance(project, Project) else project
            save_project(snapshot, pending, update_project_path=False)
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

    def files(self, project_id: str | None = None) -> list[Path]:
        """Completed recovery files, including damaged copies for manual cleanup."""
        pattern = f"{project_id}.recovery-*.fitproj" if project_id else "*.recovery-*.fitproj"
        dated = []
        for path in self.directory.glob(pattern):
            try:
                dated.append((path.stat().st_mtime_ns, path.name, path))
            except FileNotFoundError:
                # A foreground Save/Discard can clear files during background rotation.
                continue
        return [item[2] for item in sorted(dated, reverse=True)]

    def candidates(self, project_id: str | None = None) -> list[Path]:
        return [path for path in self.files(project_id)
                if not validate_project_archive(path, raise_on_error=False)]

    @staticmethod
    def description(path: Path) -> dict:
        try:
            with zipfile.ZipFile(path) as archive:
                metadata = json.loads(archive.read("manifest.json"))["project"]
            if not isinstance(metadata, dict):
                raise ValueError("Invalid project metadata")
            info = metadata.get("recovery", {})
            if not isinstance(info, dict):
                info = {}
            name = info.get("display_name") or metadata.get("name") or "Untitled"
            if not isinstance(name, str):
                name = "Untitled"
            if name == "Untitled":
                name += " — " + path.name.split(".recovery-", 1)[0]
            source = info.get("source_file", "")
            return {"name": name, "source_file": source if isinstance(source, str) else "", "readable": True}
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            return {"name": path.name, "source_file": "", "readable": False}

    def recover(self, path: str | Path) -> Project:
        project = load_project(path)
        project.dirty = True
        project.path = None
        info = self.description(Path(path))
        if info["source_file"]:
            project.ui_state["recovery_source_file"] = info["source_file"]
        if project.name == "Untitled":
            project.name = info["name"]
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

    def delete_copies(self, paths: list[Path]) -> set[str]:
        """Delete selected completed copies, never paths outside this cache."""
        available = set(self.files())
        if not set(paths) <= available:
            raise ValueError("Only existing recovery copies in this cache can be deleted.")
        ids = {path.name.split(".recovery-", 1)[0] for path in paths}
        with self._lock:
            for project_id in ids:
                self._generations[project_id] = self._generations.get(project_id, 0) + 1
            for path in paths:
                path.unlink(missing_ok=True)
            empty = {project_id for project_id in ids if not self.files(project_id)}
            if self._last_project_id in empty:
                self._last_revision = -1
                self._last_project_id = None
        return empty

    def _rotate(self, project_id: str) -> None:
        for obsolete in self.candidates(project_id)[self.keep :]:
            obsolete.unlink(missing_ok=True)
