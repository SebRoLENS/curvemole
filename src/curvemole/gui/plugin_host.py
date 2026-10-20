"""Qt hosting for additive plugins; callbacks never receive the live main window."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFileDialog,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.extensions import extensions
from curvemole.core.plugin_identity import contribution_tooltip
from curvemole.gui.documentation import plugin_manuals, show_markdown_document


def _plugin_recovery_problems(
    installed: dict[str, dict[str, Any]], identifiers: set[str] | None = None
) -> list[str]:
    """Return genuine recovery failures, excluding intentional disablement."""
    return [
        f"{key}: {record.get('error')}"
        for key, record in installed.items()
        if (identifiers is None or key in identifiers)
        and record.get("error") and record.get("error") != "Disabled by user"
    ]


@dataclass
class PluginContext:
    """Detached project snapshot. Mutating commands are committed as one undo step."""
    project: Any
    active_curve_id: str | None
    selected_curve_ids: tuple[str, ...]
    owner: str
    path: str | None = None
    cancellation: Any = None
    services: Any = None
    settings_only: bool = False

    @property
    def data(self) -> dict:
        return self.project.ui_state.setdefault("plugin_data", {}).setdefault(self.owner, {})


class PluginHost:
    def __init__(self, window: Any) -> None:
        self.window = window
        self.actions = []
        self.dialogs: dict[str, QDockWidget] = {}
        self._auto_opened = set()
        self._startup_complete = False
        menus = {action.text().replace("&", ""): action.menu()
                 for action in window.menuBar().actions() if action.menu()}
        locations = {"importers": "File", "exporters": "File", "transformations": "Data",
                     "analysis": "Tools", "actions": "Tools", "workflows": "Tools",
                     "panels": "View", "plot_layers": "View"}
        self.menus = {kind: menus[location].addMenu("Plugins: " + kind.replace("_", " ").title())
                      for kind, location in locations.items()}
        help_menu = getattr(window, "help_menu", menus.get("Help"))
        if help_menu is None:
            help_menu = window.menuBar().addMenu("Help")
        self.help_menu = help_menu.addMenu("Plugin help")
        self.help_menu.aboutToShow.connect(self._refresh_help)
        self.refresh()

    def context(self, owner: str, path: str | None = None, *, with_services: bool = False) -> PluginContext:
        window = self.window
        from curvemole.gui.plugin_services import PluginServices

        return PluginContext(copy.deepcopy(window.project), window.active_curve_id,
                             tuple(window.curve_tree.selected_curve_ids()), owner, path,
                             services=PluginServices(self, owner) if with_services else None)

    def refresh(self) -> None:
        self._refresh_help()
        self._auto_opened.intersection_update(extensions.entries)
        for identifier, dialog in list(self.dialogs.items()):
            entry = extensions.entries.get(identifier)
            if entry is None or entry.owner in self.window.plugin_manager.errors:
                dialog.close()
                dialog.deleteLater()
                self.dialogs.pop(identifier, None)
        if hasattr(self.window, "_refresh_quick_function_selector"):
            self.window._refresh_quick_function_selector()
        for kind, menu in self.menus.items():
            menu.clear()
            menu.setToolTipsVisible(True)
            available = [entry for entry in extensions.values(kind)
                         if entry.owner not in self.window.plugin_manager.errors]
            menu.menuAction().setVisible(bool(available))
            for entry in available:
                action = menu.addAction(entry.label)
                action.setToolTip(contribution_tooltip(entry))
                action.setStatusTip(contribution_tooltip(entry))
                action.triggered.connect(lambda checked=False, item=entry: self.run(item))
        if self._startup_complete:
            self._open_automatic_panels()

    def _refresh_help(self) -> None:
        self.help_menu.clear()
        manager = self.window.plugin_manager
        for identifier, metadata in sorted(manager.loaded.items(),
                                           key=lambda item: manager.plugin_name(item[0]).casefold()):
            if identifier in manager.errors or not manager.installed.get(identifier, {}).get("enabled"):
                continue
            label = f"{manager.symbol(identifier)} {manager.plugin_name(identifier)}"
            manuals = plugin_manuals(metadata.source)
            if not manuals:
                action = self.help_menu.addAction(label + " — manual unavailable")
                action.setEnabled(False)
                continue
            menu = self.help_menu.addMenu(label) if len(manuals) > 1 else self.help_menu
            for path in manuals:
                action = menu.addAction(str(path.relative_to(Path(metadata.source).parent))
                                        if len(manuals) > 1 else label)
                action.setToolTip(str(path))
                action.triggered.connect(
                    lambda checked=False, target=path, title=label:
                    show_markdown_document(self.window, target, title)
                )
        self.help_menu.setEnabled(bool(self.help_menu.actions()))

    def finish_startup(self) -> None:
        """Create automatic docks before MainWindow restores its saved state.

        Deferring them through the event queue left native dock placeholders in
        restored Windows layouts and could crash Qt while attaching the real dock.
        """
        self._startup_complete = True
        self._open_automatic_panels()

    def _open_automatic_panels(self) -> None:
        for entry in extensions.values("panels"):
            if entry.auto_show and entry.identifier not in self._auto_opened:
                self._auto_opened.add(entry.identifier)
                self._open_automatic_panel(entry)

    def _open_automatic_panel(self, entry):
        if extensions.entries.get(entry.identifier) is entry and entry.owner not in self.window.plugin_manager.errors:
            self.run(entry)

    def run(self, entry: Any) -> None:
        window = self.window
        if window._thread is not None and entry.kind != "panels":
            QMessageBox.information(window, "Plugins", "Wait for the running task to finish.")
            return
        mutating = entry.kind in {"importers", "transformations", "actions", "workflows"}
        if mutating and not window._ensure_editable():
            return
        if entry.kind == "panels" and entry.identifier in self.dialogs:
            dialog = self.dialogs[entry.identifier]
            if hasattr(window, "activate_tool_dock"):
                window.activate_tool_dock(dialog)
            else:
                dialog.show()
                dialog.raise_()
            return
        path = None
        if entry.kind in {"importers", "exporters"}:
            chooser = QFileDialog.getOpenFileName if entry.kind == "importers" else QFileDialog.getSaveFileName
            path, _ = chooser(window, entry.label)
            if not path:
                return
        context = self.context(entry.owner, path, with_services=entry.kind in {"panels", "actions"})
        try:
            result = entry.callback(context)
            if mutating and context.settings_only:
                context.services.save_settings(context.data)
            elif mutating:
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
                dialog = QDockWidget(entry.label, window)
                dialog.setObjectName("plugin_panel_" + entry.identifier)
                scroll = QScrollArea(dialog)
                scroll.setWidgetResizable(True)
                scroll.setWidget(result)
                dialog.setWidget(scroll)
                dialog.setToolTip(contribution_tooltip(entry))
                # Runtime-enabled panels may be created after restoreState(); startup
                # panels already exist and are restored by MainWindow itself.
                if not window.restoreDockWidget(dialog):
                    if hasattr(window, "register_tool_dock"):
                        window.register_tool_dock(dialog)
                    else:
                        window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dialog)
                        window.resizeDocks([dialog], [420], Qt.Orientation.Vertical)
                if hasattr(window, "activate_tool_dock"):
                    window.activate_tool_dock(dialog)
                else:
                    dialog.show()
                self.dialogs[entry.identifier] = dialog
                dialog.destroyed.connect(lambda: self.dialogs.pop(entry.identifier, None))
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

    def startup_notice(self, unclean: bool, load_failures: set[str]) -> None:
        problems = _plugin_recovery_problems(
            self.window.plugin_manager.installed,
            None if unclean else load_failures,
        )
        if unclean or problems:
            QTimer.singleShot(0, lambda: QMessageBox.warning(
                self.window, "Plugin recovery", "Some plugins are disabled. CurveMole can be used normally.\n"
                "Open File → Plugin Manager to review, enable or remove them.\n\n" + "\n".join(problems)))
