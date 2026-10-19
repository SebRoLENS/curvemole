"""Keep cyclic destruction of GUI objects on Qt's application thread."""

from __future__ import annotations

import gc

from PySide6.QtCore import QObject, QThread, QTimer, Slot
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
        if self._restore_automatic:
            # Automatic GC can run in an import/save worker and destroy unreachable
            # Qt wrappers there. Qt objects must be destroyed on their owning thread.
            gc.disable()
            self.timer.start()
        app.aboutToQuit.connect(self.stop)

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
