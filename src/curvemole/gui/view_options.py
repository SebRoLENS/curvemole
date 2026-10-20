"""Scope-aware display options; processing and fit inputs stay in the project."""
from __future__ import annotations

import json
from dataclasses import replace

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolBar,
    QToolButton,
    QWidget,
)

from curvemole.core.display import DisplayOptions, display_curve, operation_keys
from curvemole.core.errors import DataValidationError
from curvemole.gui.main_window import MainWindow, _resource_icon

OPERATION_NAMES = {
    "y_add": "Y addition", "y_subtract": "Y subtraction", "y_multiply": "Y multiplication",
    "y_divide": "Y division", "x_add": "X shift", "x_multiply": "X scaling",
    "normalize_max": "Maximum normalization", "normalize_area": "Area normalization",
    "background_subtract": "Background subtraction", "custom_formula": "Custom formula",
    "column_formula": "Column formula", "replace_y": "Y replacement / correction",
    "curve_add": "Curve addition", "curve_subtract": "Curve subtraction",
    "curve_multiply": "Curve multiplication", "curve_divide": "Curve division",
    "move_points": "Move points", "delete_points": "Delete points",
}


class OptionsMenu(QMenu):
    def mouseReleaseEvent(self, event):
        action = self.actionAt(event.position().toPoint())
        if (event.button() == Qt.MouseButton.LeftButton and action is not None
                and action.isEnabled() and action.isCheckable()):
            action.trigger()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ViewOptionsController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.workspace = window, window.plot_workspace
        self.scope = "current"
        self.options: dict[str, DisplayOptions] = {}
        self._cache = {}
        self._project_id = window.project.id
        self.workspace.view_options_controller = self
        self.menu = OptionsMenu(window)
        self._groups = []
        self.menu.setToolTipsVisible(True)
        self.menu.aboutToShow.connect(self.rebuild_menu)
        self.action = QAction(_resource_icon("view-options.svg"), self.tr("View options"), window)
        self.action.setObjectName("view_options_action")
        self.action.setCheckable(True)
        self.action.setMenu(self.menu)
        self.action.setToolTip(self.tr(
            "View options\nPreview original data, include or exclude recorded operations, "
            "or change background display for the current spectrum or all spectra."
        ))
        window.view_options_action = self.action
        window.view_options_controller = self
        old = window.background_subtracted_view_action
        old.toggled.connect(self._legacy_changed)
        for menu in window.menuBar().findChildren(QMenu):
            if old in menu.actions():
                menu.insertAction(old, self.action)
                menu.removeAction(old)
        toolbar = window.findChild(QToolBar, "Main_toolbar")
        if toolbar is not None:
            toolbar.removeAction(old)
            toolbar.insertAction(self.workspace.mask_action, self.action)
            toolbar.insertSeparator(self.workspace.mask_action)
            button = toolbar.widgetForAction(self.action)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        old.setVisible(False)
        self.bar = QWidget(self.workspace)
        row = QHBoxLayout(self.bar)
        row.setContentsMargins(8, 3, 8, 3)
        self.label = QLabel()
        self.label.setWordWrap(True)
        row.addWidget(self.label, 1)
        reset = QPushButton(self.tr("Reset all views"))
        reset.clicked.connect(lambda: self.apply({c.id: DisplayOptions() for c in window.project.curves}))
        row.addWidget(reset)
        layout = self.workspace.layout()
        layout.insertWidget(layout.indexOf(self.workspace.graphics), self.bar)
        self.bar.hide()
        self.workspace.residual_toggle.toggled.connect(lambda *_: self.sync_ui())
        self.workspace.refresh()

    def for_curve(self, curve_id):
        return self.options.get(curve_id, DisplayOptions())

    def targets(self):
        curves = self.window.project.curves
        return curves if self.scope == "all" else [c for c in curves if c.id == self.window.active_curve_id]

    def prepare(self):
        project = self.workspace._project
        if project is None:
            return
        if project.id != self._project_id:
            self.options.clear()
            self.workspace._background_subtracted_view = False
            self._project_id = project.id
        self._cache.clear()
        self.options = {c.id: replace(self.for_curve(c.id),
                                    excluded=self.for_curve(c.id).excluded.intersection(operation_keys(c)))
                        for c in project.curves if self.for_curve(c.id) != DisplayOptions()}
        self.sync_ui()

    def curve(self, curve):
        if curve.id not in self._cache:
            try:
                self._cache[curve.id] = display_curve(curve, self.for_curve(curve.id))
            except DataValidationError as exc:
                # A subsequent real edit can invalidate an earlier display combination.
                self.options.pop(curve.id, None)
                self._cache[curve.id] = curve
                self.sync_ui()
                self.window.statusBar().showMessage(self.tr("Display reset: ") + str(exc), 10000)
        return self._cache[curve.id]

    def replays(self, curve):
        project = self.workspace._project
        source = project.dataset.curve(curve.id) if project is not None else curve
        return self.for_curve(curve.id).replays(source)

    def sync_ui(self):
        curves = self.workspace.displayed_curves()
        changed = [c for c in curves if self.for_curve(c.id) != DisplayOptions()]
        legacy = bool(getattr(self.workspace, "_background_subtracted_view", False))
        active = bool(changed) or legacy
        self.action.blockSignals(True)
        self.action.setChecked(active)
        self.action.setEnabled(bool(self.window.project.curves))
        self.action.blockSignals(False)
        self.bar.setVisible(active)
        raw = sum(self.for_curve(c.id).original for c in changed)
        replay = any(self.replays(c) for c in changed)
        self.workspace.residual_plot.setVisible(
            self.workspace.residual_toggle.isChecked()
            and (not curves or any(not self.replays(c) for c in curves))
        )
        summary = self.tr("Original data") if raw and raw == len(changed) else self.tr("Custom display")
        if legacy or changed and all(self.for_curve(c.id).background == "subtract" and not self.replays(c) for c in changed):
            summary = self.tr("Fitted background removed")
        self.label.setText(self.tr("Display preview: ") + summary
                           + f" · {len(curves) if legacy else len(changed)}/{len(curves)} "
                           + self.tr("visible spectra")
                           + (self.tr(" · Models and residuals hidden for reconstructed data. "
                                      "Editing or fitting returns to stored data.") if replay else ""))

    def apply(self, updates):
        curves = {c.id: c for c in self.window.project.curves}
        try:
            for key, options in updates.items():
                display_curve(curves[key], options)
        except DataValidationError as exc:
            QMessageBox.warning(self.window, self.tr("View options"), str(exc))
            self._rebuild_later()
            return False
        self.workspace.cancel_placement()
        for session in list(self.workspace._plugin_plot_sessions.values()):
            if session._curve_id in updates and updates[session._curve_id].replays(curves[session._curve_id]):
                session._invalidate()
        if getattr(self.workspace, "_background_subtracted_view", False):
            # Preserve a legacy global background view for spectra outside this edit.
            for curve in curves.values():
                self.options.setdefault(curve.id, DisplayOptions(background="subtract"))
        self.workspace._background_subtracted_view = False
        self.options.update(updates)
        old = self.window.background_subtracted_view_action
        old.blockSignals(True)
        old.setChecked(any(o.background == "subtract" and not o.original for o in self.options.values()))
        old.blockSignals(False)
        self.workspace.refresh()
        if self.workspace.autoscale_toggle.isChecked():
            self.workspace._apply_autoscale()
        self._rebuild_later()
        return True

    def restore_for_editing(self):
        updates = {c.id: DisplayOptions(background="subtract" if self.for_curve(c.id).background == "subtract" else "stored")
                   for c in self.window.project.curves if self.replays(c)}
        if updates:
            self.apply(updates)
            self.window.statusBar().showMessage(self.tr("Stored data restored for editing or fitting."), 5000)

    def _legacy_changed(self, enabled):
        if enabled:
            self.options.clear()
        else:
            self.options = {key: replace(o, background="stored") if o.background == "subtract" else o
                            for key, o in self.options.items()}
        self.workspace.refresh()

    def _rebuild_later(self):
        if self.menu.isVisible():
            QTimer.singleShot(0, self.rebuild_menu)

    def _set_scope(self, scope):
        self.scope = scope
        self._rebuild_later()

    def _preset(self, original):
        self.apply({c.id: DisplayOptions(original=original) for c in self.targets()})

    def _background(self, mode):
        self.apply({c.id: replace(self.for_curve(c.id), original=False, background=mode)
                    for c in self.targets()})

    def _operation(self, pairs, included):
        updates = {}
        for curve, key, item in pairs:
            options = updates.get(curve.id, self.for_curve(curve.id))
            excluded = options.excluded - {key} if included else options.excluded | {key}
            background = "stored" if included and item.operation == "background_subtract" and options.background == "restore" else options.background
            updates[curve.id] = replace(options, original=False, background=background, excluded=frozenset(excluded))
        self.apply(updates)

    def _radio(self, group, text, name, checked, callback, enabled=True):
        action = self.menu.addAction(text)
        action.setObjectName(name)
        action.setCheckable(True)
        action.setChecked(checked)
        action.setEnabled(enabled)
        group.addAction(action)
        action.triggered.connect(callback)
        return action

    def rebuild_menu(self):
        self.menu.clear()
        for group in self._groups:
            group.deleteLater()
        self._groups.clear()
        self.menu.addSection(self.tr("Apply display changes to"))
        scope = QActionGroup(self.menu)
        for name, text in (("current", self.tr("Current spectrum")), ("all", self.tr("All spectra"))):
            self._radio(scope, text, "view_scope_" + name, self.scope == name,
                        lambda checked=False, target=name: self._set_scope(target))
        curves = self.targets()
        options = [self.for_curve(c.id) for c in curves]
        enabled = bool(curves)
        self.menu.addSection(self.tr("Data"))
        presets = QActionGroup(self.menu)
        self._radio(presets, self.tr("Stored data — all operations included"), "view_stored",
                    enabled and all(o == DisplayOptions() for o in options), lambda: self._preset(False), enabled)
        self._radio(presets, self.tr("Original data — no operations or masks"), "view_original",
                    enabled and all(o.original for o in options), lambda: self._preset(True), enabled)
        self.menu.addSection(self.tr("Background"))
        backgrounds = QActionGroup(self.menu)
        self._groups = [scope, presets, backgrounds]
        for mode, text in (("stored", self.tr("As stored")),
                           ("subtract", self.tr("Remove fitted background in this view")),
                           ("restore", self.tr("Show data before background subtraction"))):
            available = enabled and (mode != "restore" or any(
                t.operation == "background_subtract" for c in curves for t in c.transformations))
            self._radio(backgrounds, text, "view_background_" + mode,
                        enabled and all(not o.original and o.background == mode for o in options),
                        lambda checked=False, target=mode: self._background(target), available)
        self.menu.addSection(self.tr("Included operations") + (self.tr(" — by type") if self.scope == "all" else ""))
        if len(set(options)) > 1:
            self.menu.addAction(self.tr("Mixed display settings; changes apply to this scope.")).setEnabled(False)
        pairs = [(c, key, item) for c in curves
                 for key, item in zip(operation_keys(c), c.transformations, strict=True)]
        grouped = {}
        for curve, key, item in pairs:
            name = item.operation if self.scope == "all" else (curve.id, key)
            grouped.setdefault(name, []).append((curve, key, item))
        for index, entries in enumerate(grouped.values()):
            curve, key, item = entries[0]
            included = [self.for_curve(c.id).includes(k, t) for c, k, t in entries]
            label = self.tr(OPERATION_NAMES.get(item.operation, item.operation))
            if self.scope == "all":
                label += f" — {len({c.id for c, _, _ in entries})}/{len(curves)} " + self.tr("spectra")
            else:
                label = f"{index + 1}. " + (item.description or label)
            if any(included) and not all(included):
                label += self.tr(" (mixed)")
            action = self.menu.addAction(label)
            action.setObjectName("view_operation_" + str(index))
            action.setData(item.operation)
            action.setCheckable(True)
            action.setChecked(all(included))
            action.setEnabled(not options or not all(o.original for o in options))
            details = [f"{c.name}: {t.description or t.operation} "
                       + json.dumps(t.parameters, ensure_ascii=False)[:400] for c, _, t in entries]
            action.setToolTip(self.tr("Checked operations are included in the display, in recorded order.\n")
                              + "\n".join(details))
            action.triggered.connect(lambda checked, targets=entries: self._operation(targets, checked))
        if not pairs:
            self.menu.addAction(self.tr("No recorded operations")).setEnabled(False)
        self.menu.addSeparator()
        reset = self.menu.addAction(self.tr("Reset display for this scope"))
        reset.setEnabled(enabled)
        reset.triggered.connect(lambda: self._preset(False))


def _install():
    if getattr(MainWindow, "_curvemole_view_options", False):
        return
    original = MainWindow.__init__

    def init(window, *args, **kwargs):
        original(window, *args, **kwargs)
        ViewOptionsController(window)

    MainWindow.__init__ = init
    MainWindow._curvemole_view_options = True


_install()
