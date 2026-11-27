"""Spectrum navigation and background-aware fit display extensions."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu, QStyle, QToolBar, QToolButton, QTreeWidgetItem

from curvemole.gui.background_display import (  # noqa: E402,F401 - compatibility re-exports
    _apply_background_aware_display,
    _background_array,
    _background_cache,
    _displayed_curves,
    _label_position,
    _masked_sample_renderer,
    _shift_selected_peak_handle,
    background_removed,
)
from curvemole.gui.main_window import MainWindow
from curvemole.gui.plot import PlotWorkspace


def _set_background_subtracted_view(workspace: PlotWorkspace, enabled: bool) -> None:
    enabled = bool(enabled)
    if bool(getattr(workspace, "_background_subtracted_view", False)) == enabled:
        return
    workspace._background_subtracted_view = enabled
    workspace.refresh()


def _background_at_x(workspace: PlotWorkspace, component_id: str, x_value: float) -> float:
    if background_removed(workspace, workspace._active_curve_id):
        return 0.0
    project = workspace._project
    curve_id = workspace._active_curve_id
    if project is None or not curve_id:
        return 0.0
    model = project.models.get(curve_id)
    if model is None:
        return 0.0
    try:
        component = model.component(component_id)
    except KeyError:
        return 0.0
    if component.is_background or component.operator != "add":
        return 0.0
    try:
        background = model.background(
            np.asarray([x_value], dtype=float),
            curve_id=curve_id,
            values=project.resolved_parameter_values(),
            registry=workspace.registry,
        )
        value = float(np.asarray(background, dtype=float)[0])
    except Exception:
        return 0.0
    return value if np.isfinite(value) else 0.0


def _install_plot_display() -> None:
    if getattr(PlotWorkspace, "_curvemole_background_aware_display", False):
        return

    original_emit_peak = PlotWorkspace._emit_peak

    def emit_peak(
        workspace: PlotWorkspace,
        component_id: str,
        position: QPointF,
        x_offset: float,
        y_offset: float,
    ) -> None:
        x_value = float(position.x() - x_offset)
        baseline = _background_at_x(workspace, component_id, x_value)
        if baseline:
            position = QPointF(float(position.x()), float(position.y()) - baseline)
        original_emit_peak(workspace, component_id, position, x_offset, y_offset)

    PlotWorkspace._emit_peak = emit_peak
    PlotWorkspace.set_background_subtracted_view = _set_background_subtracted_view
    PlotWorkspace._curvemole_background_aware_display = True


def _visible_curve_items(window: MainWindow) -> list[QTreeWidgetItem]:
    items: list[QTreeWidgetItem] = []
    tree = window.curve_tree
    for top_index in range(tree.topLevelItemCount()):
        parent = tree.topLevelItem(top_index)
        if parent.isHidden():
            continue
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            if child.isHidden():
                continue
            metadata = child.data(1, Qt.ItemDataRole.UserRole)
            if metadata and metadata[0] == "curve":
                items.append(child)
    return items


def _step_active_spectrum(window: MainWindow, delta: int) -> None:
    items = _visible_curve_items(window)
    if not items or delta not in {-1, 1}:
        return
    ids = [str(item.data(1, Qt.ItemDataRole.UserRole)[1]) for item in items]
    try:
        index = ids.index(str(window.active_curve_id))
        start = index + delta
    except ValueError:
        start = 0 if delta > 0 else len(items) - 1
    target = next(
        (index for index in range(start, len(items) if delta > 0 else -1, delta)
         if items[index].checkState(0) == Qt.CheckState.Checked),
        None,
    )
    if target is None:
        return
    item = items[target]
    window.curve_tree.clearSelection()
    item.setSelected(True)
    window.curve_tree.setCurrentItem(item)
    window.curve_tree.scrollToItem(item)


def _restore_component_states(
    model: Any,
    states: dict[str, tuple[bool, bool]],
) -> None:
    for component_id, (marked, enabled) in states.items():
        component = model.component(component_id)
        component.is_background = marked
        component.enabled = enabled


def _subtract_all_backgrounds(window: MainWindow) -> None:
    from curvemole.gui.background_controls_fix import _subtract_all_backgrounds as subtract
    subtract(window)


def _find_menu(window: MainWindow, title: str) -> QMenu | None:
    wanted = window.tr(title)
    for action in window.menuBar().actions():
        menu = action.menu()
        if menu is not None and menu.title().replace("&", "") == wanted:
            return menu
    return None


def _install_window_controls(window: MainWindow) -> None:
    window.subtract_all_backgrounds_action = QAction(
        window.subtract_background_action.icon(),
        window.tr("Subtract backgrounds from all spectra"),
        window,
    )
    window.subtract_all_backgrounds_action.setToolTip(
        window.tr(
            "Subtract every enabled model function marked as background from every spectrum. "
            "This changes the data and can be undone."
        )
    )
    window.subtract_all_backgrounds_action.triggered.connect(window.subtract_all_backgrounds)

    window.background_subtracted_view_action = QAction(
        window.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
        window.tr("Background-subtracted display"),
        window,
        checkable=True,
    )
    window.background_subtracted_view_action.setToolTip(
        window.tr(
            "Visual only: show all spectra and fitted functions with marked backgrounds removed. "
            "Turning it off restores the normal display; data are never changed."
        )
    )
    window.background_subtracted_view_action.toggled.connect(
        window.plot_workspace.set_background_subtracted_view
    )

    data_menu = _find_menu(window, "Data")
    if data_menu is not None:
        data_menu.insertAction(window.calculator_action, window.subtract_all_backgrounds_action)
    view_menu = _find_menu(window, "View")
    if view_menu is not None:
        view_menu.insertAction(window.reset_layout_action, window.background_subtracted_view_action)

    toolbar = window.findChild(QToolBar, "Main_toolbar")
    if toolbar is not None:
        toolbar.insertAction(window._background_toolbar_separator, window.subtract_all_backgrounds_action)
        toolbar.insertAction(window._background_toolbar_separator, window.background_subtracted_view_action)
        for action in (
            window.subtract_all_backgrounds_action,
            window.background_subtracted_view_action,
        ):
            button = toolbar.widgetForAction(action)
            if isinstance(button, QToolButton):
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

    graphics = window.plot_workspace.graphics
    graphics.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    graphics.viewport().setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    with suppress(AttributeError):
        graphics.scene().sigMouseClicked.connect(
            lambda _event, graphics=graphics: graphics.setFocus(Qt.FocusReason.MouseFocusReason)
        )

    window._spectrum_up_shortcut = QShortcut(QKeySequence("Up"), graphics)
    window._spectrum_down_shortcut = QShortcut(QKeySequence("Down"), graphics)
    for shortcut in (window._spectrum_up_shortcut, window._spectrum_down_shortcut):
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    window._spectrum_up_shortcut.activated.connect(lambda: window._step_active_spectrum(-1))
    window._spectrum_down_shortcut.activated.connect(lambda: window._step_active_spectrum(1))


def _install_main_window_extensions() -> None:
    if getattr(MainWindow, "_curvemole_background_navigation", False):
        return
    original_init = MainWindow.__init__

    def init(window: MainWindow, *args: Any, **kwargs: Any) -> None:
        original_init(window, *args, **kwargs)
        _install_window_controls(window)

    MainWindow.__init__ = init
    MainWindow._step_active_spectrum = _step_active_spectrum
    MainWindow.subtract_all_backgrounds = _subtract_all_backgrounds
    MainWindow._curvemole_background_navigation = True


_install_plot_display()
_install_main_window_extensions()
