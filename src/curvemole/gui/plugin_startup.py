"""Load trusted plugins after first paint, one at a time on the GUI thread."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDockWidget, QToolBar


class PluginStartup(QObject):
    def __init__(self, window, recovered: bool):
        super().__init__(window)
        self.window = window
        self.recovered = recovered
        self.failures: set[str] = set()
        self.steps = window.plugin_manager.autoload_steps()
        self.completed = 0
        self.total = sum(bool(record.get("enabled")) for record in window.plugin_manager.installed.values())
        self.waiting_for_paint = True
        self.cancelled = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.advance)
        # Keep project operations unavailable until all plugin functions exist.
        # Native window controls (including close) remain usable throughout.
        controls = [window.centralWidget(), window.menuBar(),
                    *window.findChildren(QDockWidget), *window.findChildren(QToolBar),
                    *window.findChildren(QAction)]
        self.controls = [(control, control.isEnabled()) for control in controls]
        for control, _ in self.controls:
            control.setEnabled(False)
        self.accept_drops = window.acceptDrops()
        window.setAcceptDrops(False)
        window.statusBar().showMessage(window.tr("Loading plugins…"))
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if self.waiting_for_paint and event.type() == QEvent.Type.Paint:
            self.waiting_for_paint = False
            self.window.removeEventFilter(self)
            # Give the other visible widgets a turn to paint as well.
            self.timer.start(10)
        return False

    def advance(self):
        if self.cancelled or self.window._session_finished:
            return
        try:
            identifier, success = next(self.steps)
        except StopIteration:
            self.restore_controls()
            self.window._complete_plugin_startup(self.recovered, self.failures)
            return
        except Exception as exc:
            # Persistence can fail even while quarantining a broken plugin.
            # Do not leave the desktop permanently disabled in a Qt slot.
            self.restore_controls()
            self.window._complete_plugin_startup(self.recovered, self.failures)
            self.window._notify(f"Plugin startup was interrupted: {exc}", warning=True)
            return
        self.completed += 1
        if not success:
            self.failures.add(identifier)
        elapsed = self.window.plugin_manager.load_timings[identifier]
        self.window._log(f"Plugin {identifier}: loaded in {elapsed * 1000:.0f} ms"
                         if success else f"Plugin {identifier}: disabled after a loading failure")
        if not self.cancelled:
            self.window.statusBar().showMessage(
                self.window.tr("Loading plugins…") + f" {self.completed}/{self.total}")
            self.timer.start(1)

    def restore_controls(self):
        for control, enabled in self.controls:
            control.setEnabled(enabled)
        self.controls.clear()
        self.window.setAcceptDrops(self.accept_drops)

    def cancel(self):
        self.cancelled = True
        self.timer.stop()
        self.window.removeEventFilter(self)
        # A plugin can run a nested Qt loop during register(); closing the
        # window there must not try to close a generator currently executing.
        if not self.steps.gi_running:
            self.steps.close()
        self.restore_controls()
