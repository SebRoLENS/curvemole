"""Persistent unresolved recovery sessions; active windows retain their OS locks."""

import json
import uuid

from PySide6.QtCore import QLockFile


class RecoverySession:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.crashed_projects = set()
        inactive = []
        for marker in directory.glob("session-*.json"):
            lock = QLockFile(str(marker.with_suffix(".lock")))
            lock.setStaleLockTime(0)
            if not lock.tryLock(0):
                continue
            try:
                projects = json.loads(marker.read_text(encoding="utf-8"))
                if not isinstance(projects, list) or not all(isinstance(p, str) for p in projects):
                    raise ValueError("Invalid recovery session")
                self.crashed_projects.update(projects)
                inactive.append((marker, lock))
            except (OSError, ValueError):
                lock.unlock()
        self.marker = directory / f"session-{uuid.uuid4().hex}.json"
        self.lock = QLockFile(str(self.marker.with_suffix(".lock")))
        self.lock.setStaleLockTime(0)
        self.projects = set(self.crashed_projects)
        self._finished = False
        try:
            if not self.lock.tryLock(0):
                raise OSError("Could not establish recovery session lock")
            # Transfer unresolved sessions before deleting their old records.
            self.record()
            for marker, _lock in inactive:
                marker.unlink(missing_ok=True)
                marker.with_suffix(".tmp").unlink(missing_ok=True)
        except Exception:
            self.lock.unlock()
            raise
        finally:
            for _marker, lock in inactive:
                lock.unlock()

    def record(self, project_id=None):
        if self._finished:
            return
        if project_id is not None:
            self.projects.add(project_id)
        temporary = self.marker.with_suffix(".tmp")
        temporary.write_text(json.dumps(sorted(self.projects)), encoding="utf-8")
        temporary.replace(self.marker)

    def resolve(self, project_id):
        self.projects.discard(project_id)
        self.crashed_projects.discard(project_id)
        self.record()

    def finish(self, *, preserve=False):
        if self._finished:
            return
        try:
            if preserve:
                available = {path.name.split(".recovery-", 1)[0]
                             for path in self.directory.glob("*.recovery-*.fitproj")}
                self.projects.intersection_update(available)
            if preserve and self.projects:
                self.record()
            else:
                self.marker.unlink(missing_ok=True)
            self.marker.with_suffix(".tmp").unlink(missing_ok=True)
        finally:
            self._finished = True
            self.lock.unlock()
