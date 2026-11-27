"""Background task execution for the main window."""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from curvemole.core.fitting import CancellationToken
from curvemole.gui.task_thread import TaskThread


class Worker(QObject):
    finished = Signal(object)
    failed = Signal(str, str)
    progress = Signal(object, str)
    partial = Signal(object)

    def __init__(self, operation: Callable[..., Any], *, streaming: bool = False) -> None:
        super().__init__()
        self.operation = operation
        self.streaming = streaming
        self.outcome = None
        self._last_progress = 0.0

    @Slot()
    def run(self) -> None:
        try:
            def progress(value, text):
                now = time.monotonic()
                if now - self._last_progress >= .05 or value == 1:
                    self._last_progress = now
                    self.progress.emit(value, text)
            result = (self.operation(progress, self.partial.emit) if self.streaming
                      else self.operation(progress))
            self.outcome = ("finished", result)
            self.finished.emit(result)
        except BaseException as exc:
            message = str(exc) or type(exc).__name__
            details = traceback.format_exc()
            self.outcome = ("failed", (message, details))
            self.failed.emit(message, details)


class TaskCallbacks(QObject):
    """Stable Qt slots keep wrapped Python handlers on the GUI thread."""

    def __init__(self, runner, finished, partial=None):
        super().__init__(runner)
        self.runner = runner
        self.window = runner.window
        self.on_finished = finished
        self.on_partial = partial
        self.delivered = False
        self.closed = False

    def active(self):
        return not self.closed and self.runner.callbacks is self

    def report_failure(self, message, details):
        try:
            self.window._task_failed(message, details)
        except BaseException:
            self.window._log(traceback.format_exc())
            self.window._notify(message, warning=True)

    @Slot(object, str)
    def progress(self, value, text):
        if self.active() and not self.delivered:
            self.window._task_progress(value, text)

    @Slot(object)
    def partial(self, result):
        if self.active() and not self.delivered and self.on_partial is not None:
            try:
                self.on_partial(result)
            except BaseException as exc:
                self.delivered = True
                self.window.cancel_task()
                self.report_failure(str(exc) or type(exc).__name__, traceback.format_exc())

    @Slot(object)
    def finished(self, result):
        if self.active() and not self.delivered:
            self.delivered = True
            try:
                self.on_finished(result)
            except BaseException as exc:
                self.report_failure(str(exc) or type(exc).__name__, traceback.format_exc())

    @Slot(str, str)
    def failed(self, message, details):
        if self.active() and not self.delivered:
            self.delivered = True
            self.report_failure(message, details)

    @Slot()
    def done(self):
        if not self.active():
            return
        # A watchdog can also reach here if a completion notification was lost.
        outcome = self.runner.worker.outcome if self.runner.worker else None
        if not self.delivered and outcome is not None:
            kind, value = outcome
            self.finished(value) if kind == "finished" else self.failed(*value)
        if not self.active():
            return
        self.cleanup()

    def retire(self):
        if not self.active():
            return
        self.delivered = True
        self.closed = True
        self.report_failure(
            self.window.tr("Task cancelled: the calculation did not respond. Previous valid results were retained."),
            "Task retired after cancellation grace period; late callbacks are ignored.",
        )
        self.cleanup()

    def cleanup(self):
        self.closed = True
        # Finished handlers capture detached fit inputs/results. Release those
        # closures immediately even when Qt defers destruction of this object.
        self.on_finished = None
        self.on_partial = None
        try:
            self.window._task_done()
        except BaseException:
            self.window._log(traceback.format_exc())
        finally:
            # Even errors in a GUI completion hook must release the busy state.
            if self.runner.callbacks is self:
                self.window._reset_task_state()
                self.runner.callbacks = None
            self.deleteLater()


class TaskRunner(QObject):
    """Runs one background task at a time for a window and delivers its results.

    The operation runs on a TaskThread; progress, partial results, completion and
    failure reach the window on the GUI thread through queued TaskCallbacks. A
    watchdog recovers lost completion notifications and retires a task that does
    not respond within ``CANCEL_GRACE_SECONDS`` after a cancellation request
    (only for tasks working on a snapshot, ``snapshot_safe``).

    The window provides the hooks ``_task_progress``, ``_task_failed``,
    ``_task_done`` and ``_reset_task_state`` and keeps the visible busy state.
    """

    CANCEL_GRACE_SECONDS = 5

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self.worker: Worker | None = None
        self.thread: TaskThread | None = None
        self.callbacks: TaskCallbacks | None = None
        self.cancellation: CancellationToken | None = None
        self.cancel_requested_at: float | None = None
        self.snapshot_safe = False
        self.watchdog = QTimer(self)
        self.watchdog.setInterval(250)
        self.watchdog.timeout.connect(self.poll)

    @property
    def busy(self) -> bool:
        return self.thread is not None

    def start(self, operation: Callable[..., Any], finished: Callable[[Any], None],
              partial: Callable[[Any], None] | None = None) -> bool:
        """Start ``operation``; return False if another task is still running."""
        if self.busy:
            return False
        if self.cancellation is None:
            self.cancellation = CancellationToken()
        self.worker = Worker(operation, streaming=partial is not None)
        self.thread = TaskThread(self.worker, self.cancellation)
        self.callbacks = TaskCallbacks(self, finished, partial)
        queued = Qt.ConnectionType.QueuedConnection
        self.worker.progress.connect(self.callbacks.progress, queued)
        if partial is not None:
            self.worker.partial.connect(self.callbacks.partial, queued)
        self.worker.finished.connect(self.callbacks.finished, queued)
        self.worker.failed.connect(self.callbacks.failed, queued)
        # The runner owns the emitter until the operation returns, including
        # after cancellation has retired its GUI callbacks.
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.callbacks.done, queued)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()
        self.watchdog.start()
        return True

    def poll(self) -> None:
        callbacks = self.callbacks
        if self.thread is None or callbacks is None or not callbacks.active():
            return
        if not self.thread.isRunning():
            callbacks.done()
        elif (self.snapshot_safe and self.cancel_requested_at is not None
              and time.monotonic() - self.cancel_requested_at >= self.CANCEL_GRACE_SECONDS):
            callbacks.retire()

    def cancel(self) -> bool:
        """Request cancellation; return True if a running task was asked to stop."""
        self.poll()
        if not self.cancellation:
            return False
        self.cancellation.cancel()
        if self.cancel_requested_at is None:
            self.cancel_requested_at = time.monotonic()
        return True

    def reset(self) -> None:
        """Idempotently forget the current task."""
        self.watchdog.stop()
        self.thread = None
        self.worker = None
        self.cancellation = None
        self.cancel_requested_at = None
        self.snapshot_safe = False


def window_busy(window: Any) -> bool:
    """Whether ``window`` runs a task; also accepts host objects that only
    provide the historical ``_thread`` attribute (plugin hosts, test doubles)."""
    busy = getattr(window, "task_running", None)
    if isinstance(busy, bool):
        return busy
    return getattr(window, "_thread", None) is not None
