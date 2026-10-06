"""Daemon task runners can be retired without destroying a running QThread."""

from __future__ import annotations

import threading
from contextlib import suppress

from PySide6.QtCore import QObject, Signal

# Keep runners and their signal emitters alive even if a window closes after an
# uncooperative calculation has been retired. They only own detached task inputs.
_live_runners: set[TaskThread] = set()


class TaskThread(QObject):
    finished = Signal()

    def __init__(self, worker, cancellation):
        super().__init__()
        self.worker = worker
        self.cancellation = cancellation
        self._python_thread = threading.Thread(
            target=self._run, name="CurveMoleTask", daemon=True,
        )

    def start(self):
        _live_runners.add(self)
        self._python_thread.start()

    def _run(self):
        try:
            self.worker.run()
        finally:
            # QApplication may already have exited after a task was retired.
            with suppress(RuntimeError):
                self.finished.emit()
            _live_runners.discard(self)

    def isRunning(self):
        return self._python_thread.is_alive()

    def quit(self):
        if self.cancellation is not None:
            self.cancellation.cancel()

    def wait(self, milliseconds=None):
        self._python_thread.join(None if milliseconds is None else milliseconds / 1000)
        return not self.isRunning()
