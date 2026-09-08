"""Track abnormal exits without mistaking another running window for a crash."""

import json
import uuid

from PySide6.QtCore import QLockFile


class RecoverySession:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.crashed_projects = set()
        for marker in directory.glob("session-*.json"):
            lock = QLockFile(str(marker.with_suffix(".lock")))
            lock.setStaleLockTime(0)
            if not lock.tryLock(0):
                continue
            try:
                self.crashed_projects.update(json.loads(marker.read_text(encoding="utf-8")))
                marker.unlink()
            except (OSError, ValueError):
                pass
            finally:
                lock.unlock()
        self.marker = directory / f"session-{uuid.uuid4().hex}.json"
        self.lock = QLockFile(str(self.marker.with_suffix(".lock")))
        self.lock.setStaleLockTime(0)
        if not self.lock.tryLock(0):
            raise OSError("Could not establish recovery session lock")
        self.projects = set()
        self.record()

    def record(self, project_id=None):
        if project_id is not None:
            self.projects.add(project_id)
        temporary = self.marker.with_suffix(".tmp")
        temporary.write_text(json.dumps(sorted(self.projects)), encoding="utf-8")
        temporary.replace(self.marker)

    def finish(self):
        self.marker.unlink(missing_ok=True)
        self.lock.unlock()
