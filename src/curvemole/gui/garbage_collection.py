"""Keep cyclic destruction of GUI objects on Qt's application thread."""

from __future__ import annotations

import gc

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, QTimer, Slot
from PySide6.QtWidgets import QApplication


class GuiGarbageCollector(QObject):
    def __init__(self, app: QApplication):
        super().__init__(app)
        self._restore_automatic = gc.isenabled()
        self._young_collections = 0
        self._old_collections = 0
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.collect)
        self._retirement_timer = QTimer(self)
        self._retirement_timer.setSingleShot(True)
        self._retirement_timer.timeout.connect(self._collect_retired_project)
        if self._restore_automatic:
            # Automatic GC can run in an import/save worker and destroy unreachable
            # Qt wrappers there. Qt objects must be destroyed on their owning thread.
            gc.disable()
            self.timer.start()
        app.aboutToQuit.connect(self.stop)

    def retire_project(self) -> None:
        """Queue one full GUI-thread collection after a project is replaced.

        Old widget cycles may already be in an older GC generation. Waiting for
        enough new allocations to reach that generation keeps large projects in
        memory throughout an otherwise idle session. Debounce project switches
        instead of running frequent full collections during ordinary rendering.
        """
        if self._restore_automatic:
            self._retirement_timer.start(0)

    @Slot()
    def _collect_retired_project(self) -> None:
        if not self._restore_automatic or QThread.currentThread() != self.thread():
            return
        # The queued timer runs after the replacing handler has read all dialog
        # values. Dispose its closed native widgets before collecting their
        # Python cycles, which can still reference the retired project.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect(2)
        self._young_collections = self._old_collections = 0

    @Slot()
    def collect(self):
        if QThread.currentThread() != self.thread():
            return
        thresholds = gc.get_threshold()
        if gc.get_count()[0] < max(1, thresholds[0]):
            return
        gc.collect(0)
        self._young_collections += 1
        if self._young_collections >= max(1, thresholds[1]):
            gc.collect(1)
            self._young_collections = 0
            self._old_collections += 1
            if self._old_collections >= max(1, thresholds[2]):
                gc.collect(2)
                self._old_collections = 0

    @Slot()
    def stop(self):
        self.timer.stop()
        self._retirement_timer.stop()
        if self._restore_automatic:
            gc.enable()
            self._restore_automatic = False


def ensure_gui_garbage_collection() -> GuiGarbageCollector:
    app = QApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        raise RuntimeError("GUI garbage collection must be installed on the application thread.")
    collector = getattr(app, "_curvemole_garbage_collector", None)
    if collector is None:
        collector = GuiGarbageCollector(app)
        app._curvemole_garbage_collector = collector
    return collector
