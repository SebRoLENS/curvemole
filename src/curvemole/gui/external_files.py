"""Coalesce OS open requests and extend the normal, live import batch."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication


class ExternalImportBatch:
    def __init__(self, paths):
        self.paths = list(paths)
        self.seen = {os.path.normcase(path) for path in paths}
        self.dialog = None
        self.index = -1
        self.accepting = True

    def add(self, paths):
        for path in paths:
            key = os.path.normcase(path)
            if key not in self.seen:
                self.seen.add(key)
                self.paths.append(path)
        # Preserve the current/processed files while sorting the unprocessed tail.
        from curvemole.gui.import_sort_fix import sort_import_paths
        self.paths[self.index + 1:] = sort_import_paths(self.paths[self.index + 1:])
        if self.dialog is not None and len(self.paths) > 1:
            checkbox = self.dialog.apply_all
            if checkbox.isHidden():
                checkbox.setChecked(True)
            checkbox.show()
            checkbox.setText(self.dialog.tr("Apply this mapping to all files in this batch")
                             + f" ({len(self.paths)})")


class ExternalFileController(QObject):
    """One modal import flow, including requests arriving during its event loop."""
    def __init__(self, window, *, delay_ms=500):
        super().__init__(window)
        self.window = window
        self.pending = []
        self.seen = set()
        self.busy = False
        self.delivering = set()
        self.delay_ms = delay_ms
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(delay_ms)
        self.timer.timeout.connect(self.flush)

    def activate(self):
        if self.window._session_finished:
            return
        if self.window.isMinimized():
            self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()
        modal = QApplication.activeModalWidget()
        if modal is not None and modal.window() is not self.window:
            modal.raise_()
            modal.activateWindow()

    def enqueue(self, paths):
        if self.window._session_finished:
            return
        existing = []
        for value in paths:
            path = Path(value)
            if path.is_file() and os.path.normcase(str(path.resolve())) not in self.delivering:
                existing.append(str(path.resolve()))
        batch = getattr(self.window, "_external_import_batch", None)
        data = [path for path in existing if Path(path).suffix.lower() != ".fitproj"]
        if batch is not None and batch.accepting:
            batch.add(data)
            existing = [path for path in existing if path not in data]
        for path in existing:
            key = os.path.normcase(path)
            if key not in self.seen:
                self.pending.append(path)
                self.seen.add(key)
        if self.pending:
            self.timer.start(self.delay_ms)

    def flush(self):
        window = self.window
        if window._session_finished:
            self.timer.stop()
            self.pending.clear()
            return
        if not self.pending:
            return
        if (self.busy or window._startup_pending or window._thread is not None
                or window.automation_runner.process is not None
                or QApplication.activeModalWidget() is not None):
            self.timer.start(100)
            return
        paths, self.pending = self.pending, []
        self.seen.clear()
        self.busy = True
        self.delivering = {os.path.normcase(path) for path in paths}
        self.activate()
        try:
            projects = [path for path in paths if Path(path).suffix.lower() == ".fitproj"]
            if projects:
                window.open_project(projects[0])
            data = [path for path in paths if Path(path).suffix.lower() != ".fitproj"]
            if data:
                batch = ExternalImportBatch(data)
                window._external_import_batch = batch
                try:
                    window.import_data(batch.paths)
                finally:
                    batch.accepting = False
                    batch.dialog = None
                    window._external_import_batch = None
        except Exception as exc:
            window._show_error(window.tr("Open files"), exc)
        finally:
            self.busy = False
            self.delivering.clear()
            if self.pending and not window._session_finished:
                self.timer.start(self.delay_ms)
