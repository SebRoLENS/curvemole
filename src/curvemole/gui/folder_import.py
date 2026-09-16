"""Opt-in, asynchronous folder import with detached plugin processing."""

from __future__ import annotations

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from curvemole.core.data import Series
from curvemole.core.extensions import extensions
from curvemole.core.fitting import CancellationToken
from curvemole.core.folder_import import FolderScan
from curvemole.core.importers import ColumnMapping, import_file
from curvemole.core.project import Project
from curvemole.gui.plugin_host import PluginContext


def prepare_file(path, signature, x_column, y_column, entry, settings, cancellation):
    """Worker owns only a fresh acquisition project, never the GUI/live project."""
    if signature[0] > 256 * 1024 * 1024:
        raise ValueError("File exceeds the 256 MiB automatic import limit.")
    cancellation.raise_if_cancelled()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    curves = import_file(path, ColumnMapping(x=x_column, y=[y_column]))
    acquisition = Project("Automatic import")
    series = Series(path.name, curves)
    acquisition.add_series(series)
    for curve in curves:
        curve.name = path.name if len(curves) == 1 else f"{path.name}: {curve.name}"
        curve.metadata["automatic_import"] = {"sha256": digest, "file_name": path.name}
    summary = None
    if entry is not None:
        acquisition.ui_state["plugin_data"] = {entry.owner: copy.deepcopy(settings)}
        context = PluginContext(
            acquisition,
            curves[-1].id,
            tuple(c.id for c in curves),
            entry.owner,
            str(path),
            cancellation=cancellation,
        )
        summary = entry.callback(context)
        acquisition = context.project
    cancellation.raise_if_cancelled()
    stat = path.stat()
    if (stat.st_size, stat.st_mtime_ns) != signature:
        raise ValueError("File changed during import; it will be retried after settling.")
    acquisition.dataset.validate_unique_ids()
    for curve in acquisition.curves:
        curve.__post_init__()
    acquisition.resolved_parameter_values()
    json.dumps(acquisition.ui_state.get("plugin_data", {}), allow_nan=False)
    return acquisition, digest, str(summary or f"Imported {path.name}")


class FolderImportDialog(QDialog):
    def __init__(self, controller):
        super().__init__(controller.window)
        self.controller = controller
        self.setWindowTitle("Automatic folder import / Importazione automatica")
        self.resize(660, 550)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.folder = QLineEdit(
            str(controller.window.settings.value("folder_import/path", "") or "")
        )
        browse = QPushButton("Choose folder…")
        browse.clicked.connect(self.choose_folder)
        row = QHBoxLayout()
        row.addWidget(self.folder)
        row.addWidget(browse)
        form.addRow("Folder / Cartella", row)
        self.contains = QLineEdit()
        self.contains.setPlaceholderText("e.g. ruby → ruby.0, ruby_0.spe, test_ruby_47.spe")
        form.addRow("Filename contains (case insensitive)", self.contains)
        self.processor = QComboBox()
        self.processor.addItem("Import only / Solo importazione", None)
        for entry in extensions.values("import_processors"):
            if entry.owner not in controller.window.plugin_manager.errors:
                self.processor.addItem(entry.label, entry.identifier)
        self.processor.currentIndexChanged.connect(self.processor_changed)
        form.addRow("Automatic workflow", self.processor)
        self.x_column = QSpinBox()
        self.x_column.setRange(1, 10000)
        self.y_column = QSpinBox()
        self.y_column.setRange(1, 10000)
        self.y_column.setValue(2)
        columns = QHBoxLayout()
        columns.addWidget(QLabel("X"))
        columns.addWidget(self.x_column)
        columns.addWidget(QLabel("Y"))
        columns.addWidget(self.y_column)
        form.addRow("Columns (1-based; SPE: wavelength, intensity)", columns)
        self.settle = QDoubleSpinBox()
        self.settle.setRange(0.5, 60)
        self.settle.setValue(2)
        self.settle.setSuffix(" s")
        form.addRow("Wait for stable file", self.settle)
        self.existing = QCheckBox("Also import matching files already in the folder")
        self.modified = QCheckBox("Import changed files again as NEW spectra (keep previous data)")
        self.follow = QCheckBox("Show newest imported spectrum")
        self.follow.setChecked(True)
        self.follow.toggled.connect(self.change_follow)
        layout.addLayout(form)
        for widget in (self.existing, self.modified, self.follow):
            layout.addWidget(widget)
        self.status = QLabel("Stopped — starts only when you press Start.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        layout.addWidget(self.log)
        buttons = QHBoxLayout()
        self.start_button = QPushButton("Start / Avvia")
        self.start_button.clicked.connect(self.start)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(controller.stop)
        retry = QPushButton("Retry failed files")
        retry.clicked.connect(controller.retry)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.hide)
        for widget in (self.start_button, self.stop_button, retry, close):
            buttons.addWidget(widget)
        layout.addLayout(buttons)
        layout.addWidget(
            QLabel("Closing this panel keeps import running. Use Stop to end the session.")
        )

    def change_follow(self, follow):
        if self.controller.scan is not None:
            self.controller.follow = follow

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Choose acquisition folder", self.folder.text()
        )
        if path:
            self.folder.setText(path)

    def processor_changed(self):
        entry = extensions.entries.get(self.processor.currentData())
        if entry:
            data = self.controller.window.project.ui_state.get("plugin_data", {}).get(
                entry.owner, {}
            )
            if data.get("filename_contains"):
                self.contains.setText(data["filename_contains"])

    def start(self):
        try:
            self.controller.start(
                self.folder.text(),
                self.contains.text(),
                include_existing=self.existing.isChecked(),
                modified=self.modified.isChecked(),
                settle=self.settle.value(),
                processor=self.processor.currentData(),
                x=self.x_column.value() - 1,
                y=self.y_column.value() - 1,
                follow=self.follow.isChecked(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Automatic import", str(exc))

    def set_running(self, running):
        for widget in (
            self.folder,
            self.contains,
            self.processor,
            self.x_column,
            self.y_column,
            self.settle,
            self.existing,
            self.modified,
            self.start_button,
        ):
            widget.setEnabled(not running)
        self.stop_button.setEnabled(running)


class FolderImportController:
    def __init__(self, window):
        self.window = window
        self.scan = None
        self.dialog = None
        self.future = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="curvemole-import")
        self.timer = QTimer(window)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.token = CancellationToken()
        self.generation = 0
        self.digests = {}
        self.action = QAction("Automatic folder import…", window)
        self.action.triggered.connect(self.show)
        self.stop_action = QAction("Stop automatic import", window)
        self.stop_action.setEnabled(False)
        self.stop_action.triggered.connect(self.stop)
        file_menu = window.import_action.associatedObjects()
        # Locate by action identity, independent of translations.
        for obj in file_menu:
            if (
                hasattr(obj, "insertAction")
                and hasattr(obj, "actions")
                and window.open_action in obj.actions()
            ):
                obj.insertAction(window.import_action, self.action)
                obj.insertAction(window.import_action, self.stop_action)
                break

    def show(self):
        if self.dialog is None:
            self.dialog = FolderImportDialog(self)
        if self.scan is None:
            combo = self.dialog.processor
            selected = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Import only / Solo importazione", None)
            for entry in extensions.values("import_processors"):
                if entry.owner not in self.window.plugin_manager.errors:
                    combo.addItem(entry.label, entry.identifier)
            index = combo.findData(selected)
            combo.setCurrentIndex(max(0, index))
            combo.blockSignals(False)
        if self.scan is not None:
            self.dialog.folder.setText(str(self.scan.folder))
            self.dialog.contains.setText(self.scan.contains)
            self.dialog.processor.blockSignals(True)
            self.dialog.processor.setCurrentIndex(self.dialog.processor.findData(self.processor_id))
            self.dialog.processor.blockSignals(False)
            self.dialog.x_column.setValue(self.x + 1)
            self.dialog.y_column.setValue(self.y + 1)
            self.dialog.settle.setValue(self.scan.settle)
            self.dialog.modified.setChecked(self.scan.modified)
            self.dialog.follow.setChecked(self.follow)
            self.dialog.status.setText(f"Running: {self.scan.folder} | contains: {self.scan.contains or '(all)'}")
        self.dialog.set_running(self.scan is not None)
        self.dialog.show()
        self.dialog.raise_()

    def log(self, message):
        if self.dialog is not None:
            self.dialog.log.appendPlainText(str(message))
        self.window._log(str(message))

    def start(
        self,
        folder,
        contains="",
        *,
        include_existing=False,
        modified=False,
        settle=2.0,
        processor=None,
        x=0,
        y=1,
        follow=True,
    ):
        if self.scan is not None or self.future is not None:
            raise ValueError("Stop the current session and wait for its task to finish.")
        if self.window.project.read_only:
            raise ValueError("The current project is read-only.")
        self.scan = FolderScan(
            folder, contains, include_existing=include_existing, modified=modified, settle=settle
        )
        self.project_id = self.window.project.id
        self.processor_id = processor
        self.x = x
        self.y = y
        self.follow = follow
        self.token = CancellationToken()
        self.generation += 1
        self.digests = {}
        self.window.settings.setValue("folder_import/path", str(self.scan.folder))
        self.timer.start()
        self.stop_action.setEnabled(True)
        if self.dialog is not None:
            self.dialog.set_running(True)
            self.dialog.status.setText(
                f"Running: {self.scan.folder} | contains: {contains or '(all)'}"
            )
        self.log("Automatic import started. Existing data are never overwritten.")

    def stop(self):
        self.scan = None
        self.generation += 1
        self.token.cancel()
        self.stop_action.setEnabled(False)
        if self.future is None:
            self.timer.stop()
        if self.dialog is not None:
            self.dialog.set_running(False)
            self.dialog.status.setText("Stopped")

    def retry(self):
        if self.scan is not None:
            self.scan.failed.clear()

    def busy(self):
        modal = QApplication.activeModalWidget()
        return (
            self.window._thread is not None
            or self.window.automation_runner.process is not None
            or modal is not None
        )

    def tick(self):
        try:
            self._tick()
        except Exception as exc:
            self.log(f"Automatic import stopped: {exc}")
            self.stop()

    def _tick(self):
        if self.scan is not None and (
            self.project_id != self.window.project.id or self.window.project.read_only
        ):
            self.stop()
            self.log("Stopped because the project changed or became read-only.")
        if self.future is not None:
            if not self.future.done() or self.busy():
                return
            future, self.future = self.future, None
            path, signature, generation, processor_id = self.pending
            if self.scan is None or generation != self.generation:
                self.timer.stop()
                return
            try:
                acquisition, digest, summary = future.result()
                if processor_id and (
                    processor_id not in extensions.entries
                    or extensions.entries[processor_id].owner in self.window.plugin_manager.errors
                ):
                    raise ValueError("Selected processor has been disabled or unloaded.")
                if self.digests.get(path) != digest:
                    self.commit(acquisition)
                    self.digests[path] = digest
                    self.log(summary)
                self.scan.consumed[path] = signature
            except Exception as exc:
                self.scan.failed[path] = signature
                self.log(f"{path.name}: {exc} — retry after correcting the file/settings.")
            return
        if self.scan is None or self.busy():
            return
        ready = self.scan.ready()
        if not ready:
            return
        path, signature = ready[0]
        entry = extensions.entries.get(self.processor_id) if self.processor_id else None
        if self.processor_id and (
            entry is None or entry.owner in self.window.plugin_manager.errors
        ):
            self.stop()
            self.log("Selected workflow is unavailable.")
            return
        data = (
            self.window.project.ui_state.get("plugin_data", {}).get(entry.owner, {})
            if entry
            else {}
        )
        self.pending = path, signature, self.generation, self.processor_id
        self.future = self.executor.submit(
            prepare_file, path, signature, self.x, self.y, entry, copy.deepcopy(data), self.token
        )

    def commit(self, acquisition):
        window = self.window
        series = copy.deepcopy(acquisition.dataset.series)
        ids = {c.id for s in series for c in s.curves}
        if not ids:
            raise ValueError("Workflow returned no spectra.")
        if ids & {c.id for c in window.project.curves}:
            raise ValueError("Duplicate curve identifiers.")
        models = copy.deepcopy(acquisition.models)
        results = copy.deepcopy(acquisition.results)
        if not set(models) <= ids:
            raise ValueError("Processor returned models outside the imported acquisition.")
        previous_results = {
            key: copy.deepcopy(window.project.results[key])
            for key in results
            if key in window.project.results
        }
        follow = self.follow
        active_before = window.active_curve_id

        def redo():
            for item in series:
                window.project.add_series(copy.deepcopy(item))
            window.project.models.update(copy.deepcopy(models))
            window.project.results.update(copy.deepcopy(results))
            if follow:
                window.active_curve_id = series[-1].curves[-1].id

        def undo():
            window.project.dataset.series[:] = [
                s for s in window.project.dataset.series if s.id not in {v.id for v in series}
            ]
            for curve_id in ids:
                window.project.models.pop(curve_id, None)
            for key in results:
                window.project.results.pop(key, None)
            window.project.results.update(copy.deepcopy(previous_results))
            window.active_curve_id = (
                active_before if active_before in {c.id for c in window.project.curves} else None
            )

        window._push_change("Automatic import", redo, undo, modified_curve_ids=set())
        if self.follow:
            window.curve_filter.clear()
            tree = window.curve_tree
            for i in range(tree.topLevelItemCount()):
                parent = tree.topLevelItem(i)
                for j in range(parent.childCount()):
                    child = parent.child(j)
                    if child.data(1, Qt.ItemDataRole.UserRole) == ("curve", window.active_curve_id):
                        tree.setCurrentItem(
                            child, 1, QItemSelectionModel.SelectionFlag.ClearAndSelect
                        )
                        tree.scrollToItem(child)
            window.plot_workspace.auto_range()

    def shutdown(self):
        self.stop()
        self.timer.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
