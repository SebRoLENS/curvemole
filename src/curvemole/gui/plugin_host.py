"""Qt hosting for additive plugins; callbacks never receive the live main window."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.extensions import extensions


@dataclass
class PluginContext:
    """Detached project snapshot. Mutating commands are committed as one undo step."""
    project: Any
    active_curve_id: str | None
    selected_curve_ids: tuple[str, ...]
    owner: str
    path: str | None = None
    cancellation: Any = None

    @property
    def data(self) -> dict:
        return self.project.ui_state.setdefault("plugin_data", {}).setdefault(self.owner, {})


class PluginHost:
    def __init__(self, window: Any) -> None:
        self.window = window
        self.actions = []
        self.dialogs: dict[str, QDialog] = {}
        menus = {action.text().replace("&", ""): action.menu()
                 for action in window.menuBar().actions() if action.menu()}
        locations = {"importers": "File", "exporters": "File", "transformations": "Data",
                     "analysis": "Tools", "actions": "Tools", "workflows": "Tools",
                     "panels": "View", "plot_layers": "View"}
        self.menus = {kind: menus[location].addMenu("◆ " + kind.replace("_", " ").title())
                      for kind, location in locations.items()}
        self.refresh()

    def context(self, owner: str, path: str | None = None) -> PluginContext:
        window = self.window
        return PluginContext(copy.deepcopy(window.project), window.active_curve_id,
                             tuple(window.curve_tree.selected_curve_ids()), owner, path)

    def refresh(self) -> None:
        if hasattr(self.window, "_refresh_quick_function_selector"):
            self.window._refresh_quick_function_selector()
        for kind, menu in self.menus.items():
            menu.clear()
            available = [entry for entry in extensions.values(kind)
                         if entry.owner not in self.window.plugin_manager.errors]
            menu.menuAction().setVisible(bool(available))
            for entry in available:
                action = menu.addAction(entry.label)
                action.setToolTip(f"Plugin: {entry.owner}\n{entry.description}")
                action.triggered.connect(lambda checked=False, item=entry: self.run(item))

    def run(self, entry: Any) -> None:
        window = self.window
        if window._thread is not None:
            QMessageBox.information(window, "Plugins", "Wait for the running task to finish.")
            return
        mutating = entry.kind in {"importers", "transformations", "actions", "workflows"}
        if mutating and not window._ensure_editable():
            return
        path = None
        if entry.kind in {"importers", "exporters"}:
            chooser = QFileDialog.getOpenFileName if entry.kind == "importers" else QFileDialog.getSaveFileName
            path, _ = chooser(window, entry.label)
            if not path:
                return
        context = self.context(entry.owner, path)
        try:
            result = entry.callback(context)
            if mutating:
                # Fail before changing the live project if persisted plugin state is not JSON.
                json.dumps(context.project.ui_state.get("plugin_data", {}), allow_nan=False)
                context.project.dataset.validate_unique_ids()
                for curve in context.project.curves:
                    curve.__post_init__()  # Revalidate arrays, masks and transformation replay.
                context.project.resolved_parameter_values()
                before = copy.deepcopy(window.project)
                after = copy.deepcopy(context.project)
                after.id, after.path, after.read_only = before.id, before.path, before.read_only
                from curvemole.core.data import CurveState
                for curve in after.curves:
                    if curve.state == CurveState.FITTED:
                        curve.state = CurveState.MODIFIED
                def restore(project: Any) -> None:
                    window.project = copy.deepcopy(project)
                    ids = {curve.id for curve in window.project.curves}
                    if window.active_curve_id not in ids:
                        window.active_curve_id = next(iter(ids), None)
                window._push_change(entry.label, lambda: restore(after), lambda: restore(before),
                                    modified_curve_ids=set())
            elif entry.kind == "plot_layers":
                self.show_layer(entry, result)
            elif entry.kind == "panels":
                if not isinstance(result, QWidget):
                    raise TypeError("A panel callback must return a QWidget.")
                dialog = QDialog(window)
                dialog.setWindowTitle(entry.label)
                QVBoxLayout(dialog).addWidget(result)
                dialog.resize(640, 480)
                dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                dialog.show()
                self.dialogs[entry.identifier] = dialog
            elif result is not None:
                dialog = QDialog(window)
                dialog.setWindowTitle(entry.label)
                text = QPlainTextEdit(str(result))
                text.setReadOnly(True)
                QVBoxLayout(dialog).addWidget(text)
                dialog.resize(720, 480)
                dialog.exec()
            window._notify(entry.label + " completed")
        except Exception as exc:
            window.plugin_manager.errors[entry.owner] = str(exc)
            record = window.plugin_manager.installed.get(entry.owner)
            if record:
                record.update(enabled=False, error=str(exc))
                window.plugin_manager._save()
            self.refresh()
            QMessageBox.critical(window, "Plugin disabled", f"{entry.owner}\n\n{exc}")

    def show_layer(self, entry: Any, result: Any) -> None:
        import numpy as np
        import pyqtgraph as pg
        items = []
        for line in result:
            x, y = np.asarray(line["x"], dtype=float), np.asarray(line["y"], dtype=float)
            if x.ndim != 1 or x.shape != y.shape or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
                raise ValueError("Plot layers require matching finite one-dimensional x/y arrays.")
            items.append(pg.PlotDataItem(x, y, pen=pg.mkPen(line.get("colour", "#cc79a7")),
                                         name=entry.label))
        for item in items:
            self.window.plot_workspace.plot.addItem(item, ignoreBounds=True)

    def emit(self, event: str) -> None:
        for entry in extensions.values("hooks"):
            if entry.owner in self.window.plugin_manager.errors:
                continue
            try:
                entry.callback(event, self.context(entry.owner))
            except Exception as exc:
                self.window._log(str(exc))
                self.refresh()

    def startup_notice(self, unclean: bool) -> None:
        problems = [f"{key}: {record.get('error')}" for key, record in
                    self.window.plugin_manager.installed.items() if record.get("error")]
        if unclean or problems:
            QTimer.singleShot(0, lambda: QMessageBox.warning(
                self.window, "Plugin recovery", "Some plugins are disabled. CurveMole can be used normally.\n"
                "Open File → Plugin Manager to review, enable or remove them.\n\n" + "\n".join(problems)))
