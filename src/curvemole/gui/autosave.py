"""One independent autosave worker, with all Qt interactions on the GUI thread."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer

from curvemole.core.serialization import capture_project_snapshot

if TYPE_CHECKING:
    from curvemole.gui.main_window import MainWindow


class AutosaveController(QObject):
    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self.window = window
        self._executor: ThreadPoolExecutor | None = None
        self._future: Future[Path | None] | None = None
        self._manager = None
        self._project_id: str | None = None
        self._generation: int | None = None
        self._requested = False
        self._closed = False
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._poll)

    @property
    def busy(self) -> bool:
        return not self._closed and (self._future is not None or self._requested)

    def request(self) -> None:
        if not self._closed:
            self._requested = True
            self._poll()

    def _poll(self) -> None:
        if self._closed:
            return
        if self._future is not None:
            if not self._future.done():
                return
            future, self._future = self._future, None
            try:
                path = future.result()
                if path and self._manager.generation(self._project_id) == self._generation:
                    self.window._log(f"Recovery saved: {path.name}")
            except Exception as exc:
                self.window._log(f"Autosave failed: {exc}")
            self._manager = None
            self._project_id = None
            self._generation = None

        if self._requested:
            # Built-in calculations own detached inputs. Preserve the wait for
            # callers that have not declared their task safe for snapshotting.
            if self.window._thread is not None and not self.window._task_snapshot_safe:
                self.timer.start()
                return
            self._requested = False
            try:
                manager, project = self.window.recovery, self.window.project
                if manager.needs_autosave(project):
                    generation = manager.generation(project.id)
                    snapshot = capture_project_snapshot(project)
                    # Track a first backup before publication, so a crash between
                    # worker completion and the next Qt timer tick is recoverable.
                    session = getattr(self.window, "_recovery_session", None)
                    if session is not None:
                        session.record(snapshot.id)
                    if self._executor is None:
                        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="CurveMoleAutosave")
                    self._manager, self._project_id = manager, snapshot.id
                    self._generation = generation
                    self._future = self._executor.submit(manager.autosave, snapshot, generation=generation)
            except Exception as exc:
                self.window._log(f"Autosave failed: {exc}")
        if self.busy:
            self.timer.start()
        else:
            self.timer.stop()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._requested = False
        self.timer.stop()
        if self._manager is not None and self._project_id is not None:
            self._manager.cancel_pending(self._project_id)
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
