"""Manual saves run on a worker while Qt continues processing input and painting."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal
from PySide6.QtWidgets import QLabel

from curvemole.core.serialization import capture_project_snapshot


class ManualSaveController(QObject):
    finished = Signal(bool)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._executor = None
        self._future = None
        self._pending = None
        self._source = None
        self._revision = None
        self._result = False
        self._closed = False
        self._status = None
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._poll)

    @property
    def busy(self):
        return self._pending is not None or self._future is not None

    def wait(self):
        if self.busy:
            loop = QEventLoop(self)
            self.finished.connect(loop.quit)
            try:
                loop.exec()
            finally:
                self.finished.disconnect(loop.quit)
        return self._result

    def save(self, path, writer, *, portable=False):
        if self._closed:
            return False
        if self.busy and not self.wait():
            return False
        self._result = False
        self._pending = (Path(path), writer, portable)
        if self._status is None:
            self._status = QLabel(self.window)
            self._status.setMaximumWidth(440)
            self.window.statusBar().addPermanentWidget(self._status)
        self._status.setText(self.tr('Saving "{name}"…').format(name=Path(path).name))
        self._status.setToolTip(str(path))
        self._status.show()
        for action in (self.window.save_action, self.window.save_as_action, self.window.portable_action):
            action.setEnabled(False)
        self.timer.start()
        self._poll()
        # Preserve the completion-result API used by Close/Open/Update, but keep
        # the Qt event loop alive. Serialization and disk work run on the worker.
        return self.wait()

    def _poll(self):
        if self._closed:
            return
        try:
            if self._future is None and self._pending is not None:
                if self.window._thread is not None:
                    return
                path, writer, portable = self._pending
                self._source = self.window.project
                snapshot = capture_project_snapshot(self._source)
                self._revision = snapshot.revision
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="CurveMoleSave")
                self._future = self._executor.submit(
                    writer, snapshot, path, portable=portable, update_project_path=False,
                )
            if self._future is None or not self._future.done():
                return
            path = self._future.result()
            _requested_path, _writer, portable = self._pending
            if portable:
                self.window._notify(self.tr("Portable copy saved."))
            else:
                if self.window.project is self._source:
                    self._source.path = path
                    self._source.read_only = False
                    if self._source.revision == self._revision:
                        self._source.mark_saved(path)
                        self.window._clear_recovery()
                        self.window._notify(self.tr("Project saved."))
                    else:
                        self.window._notify(self.tr("Snapshot saved; newer changes are still unsaved."))
                    self.window.setWindowTitle(self.window._title())
                self.window._remember_recent_project(path)
            self._complete(True)
        except Exception as exc:
            self.window._show_error(self.tr("Save project"), exc)
            self._complete(False)

    def _complete(self, result):
        self._result = result
        self._pending = self._future = self._source = None
        self.timer.stop()
        if self._status is not None:
            self._status.hide()
        for action in (self.window.save_action, self.window.save_as_action, self.window.portable_action):
            action.setEnabled(True)
        self.finished.emit(result)

    def shutdown(self):
        self._closed = True
        self.timer.stop()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
        self.finished.emit(False)
