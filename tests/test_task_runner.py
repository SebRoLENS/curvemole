import time

from PySide6.QtWidgets import QApplication, QWidget

from curvemole.gui.task_runner import TaskRunner, window_busy


class _Window(QWidget):
    def __init__(self):
        super().__init__()
        self.events = []
        self.task_runner = TaskRunner(self)

    @property
    def task_running(self):
        return self.task_runner.busy

    def _task_progress(self, value, text):
        self.events.append(("progress", text))

    def _task_failed(self, message, details):
        self.events.append(("failed", message))

    def _task_done(self):
        self.events.append(("done",))

    def _reset_task_state(self):
        self.task_runner.reset()

    def _log(self, text):
        self.events.append(("log", text))

    def _notify(self, text, warning=False):
        self.events.append(("notify", text))

    def cancel_task(self):
        self.task_runner.cancel()

    def tr(self, text):
        return text


def _wait(app, predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    return predicate()


def test_runner_delivers_results_on_the_gui_thread_and_releases_busy_state():
    app = QApplication.instance() or QApplication([])
    window = _Window()
    results = []

    def operation(progress):
        progress(1.0, "half")
        return 42

    assert window.task_runner.start(operation, results.append)
    assert window_busy(window)
    assert not window.task_runner.start(operation, results.append)  # one task at a time
    assert _wait(app, lambda: not window.task_runner.busy)
    assert results == [42]
    assert ("done",) in window.events


def test_failure_is_reported_and_cancellation_reaches_the_operation():
    app = QApplication.instance() or QApplication([])
    window = _Window()

    def failing(progress):
        raise ValueError("bad input")

    window.task_runner.start(failing, lambda result: None)
    assert _wait(app, lambda: not window.task_runner.busy)
    assert ("failed", "bad input") in window.events

    def waits_for_cancel(progress):
        token = window.task_runner.cancellation
        while not token.cancelled:
            time.sleep(0.005)
        raise RuntimeError("cancelled")

    window.task_runner.start(waits_for_cancel, lambda result: None)
    assert window.task_runner.cancel()
    assert _wait(app, lambda: not window.task_runner.busy)


def test_window_busy_accepts_historical_hosts():
    class Host:
        _thread = object()

    assert window_busy(Host())
    Host._thread = None
    assert not window_busy(Host())
