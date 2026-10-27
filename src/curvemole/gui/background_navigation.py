"""Spectrum navigation and background-aware fit display extensions."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu, QStyle, QToolBar, QToolButton, QTreeWidgetItem

from curvemole.core.data import Curve
from curvemole.core.errors import DataValidationError
from curvemole.core.parameters import resolve_parameter_values
from curvemole.gui import mask_display as _mask_display
from curvemole.gui.main_window import MainWindow
from curvemole.gui.plot import PlotWorkspace
from curvemole.gui.plot_appearance import (
    colour_with_opacity,
    marker_for_curve,
    plot_mode_flags,
    qt_pen_style,
)


def background_removed(workspace: PlotWorkspace, curve_id: str | None) -> bool:
    controller = getattr(workspace, "view_options_controller", None)
    if controller is not None:
        options = controller.for_curve(curve_id)
        if options.original:
            return False
        if options.background != "stored":
            return options.background == "subtract"
    return bool(getattr(workspace, "_background_subtracted_view", False))


def _displayed_curves(workspace: PlotWorkspace) -> tuple[list[Curve], float, float]:
    project = workspace._project
    if project is None or not project.curves:
        return [], 0.0, 0.0
    mode = workspace.display_mode.currentText()
    curves = [workspace.curve_for_display(curve) for curve in workspace.displayed_curves()]
    x_step = workspace.x_offset.value() if mode == workspace.tr("Waterfall") else 0.0
    y_step = workspace.y_offset.value() if mode == workspace.tr("Waterfall") else 0.0
    return curves, x_step, y_step


def _background_array(
    workspace: PlotWorkspace,
    curve: Curve,
    values: dict[str, float] | None = None,
) -> np.ndarray:
    project = workspace._project
    if project is None:
        return np.zeros_like(curve.y, dtype=float)
    model = project.models.get(curve.id)
    if model is None or not any(
        component.enabled and component.is_background for component in model.components
    ):
        return np.zeros_like(curve.y, dtype=float)
    try:
        resolved = values if values is not None else resolve_parameter_values(
            project.parameter_map(), paths=model.parameter_map(curve.id))
        background = np.asarray(
            model.background(
                curve.x,
                curve_id=curve.id,
                values=resolved,
                registry=workspace.registry,
            ),
            dtype=float,
        )
        usable = np.isfinite(curve.x) & np.isfinite(curve.y)
        if background.shape != curve.y.shape or np.any(usable & ~np.isfinite(background)):
            raise DataValidationError("The background returned invalid values.")
        return background
    except Exception as exc:
        controller = getattr(workspace, "render_controller", None)
        if controller is not None:
            controller.evaluation_failed(curve, exc)
        return np.zeros_like(curve.y, dtype=float)


def _background_cache(workspace: PlotWorkspace) -> dict[str, np.ndarray]:
    project = workspace._project
    curves, _, _ = _displayed_curves(workspace)
    if project is None:
        return {}
    values = getattr(workspace, "_live_parameter_values", None)
    if values is None:
        try:
            values = project.resolved_parameter_values()
        except Exception:
            values = None
    workspace._render_values = values
    workspace._render_models = {}
    backgrounds = {}
    for curve in curves:
        model = project.models.get(curve.id)
        try:
            if model is not None and model.components:
                scoped_values = values if values is not None else resolve_parameter_values(
                    project.parameter_map(), paths=model.parameter_map(curve.id))
                total, components = model.evaluate(curve.x, curve_id=curve.id, values=scoped_values,
                                                    registry=workspace.registry, components=True)
                workspace._render_models[curve.id] = (total, components)
                backgrounds[curve.id] = model.background(curve.x, curve_id=curve.id, values=scoped_values,
                    registry=workspace.registry, evaluated_components=components)
                usable = np.isfinite(curve.x) & np.isfinite(curve.y)
                if np.any(usable & (~np.isfinite(total) | ~np.isfinite(backgrounds[curve.id]))):
                    raise DataValidationError("The model or background returned non-finite values.")
            else:
                backgrounds[curve.id] = np.zeros_like(curve.y)
            controller = getattr(workspace, "render_controller", None)
            if controller is not None:
                controller.errors.pop(curve.id, None)
                controller.notified.pop(curve.id, None)
        except Exception as exc:
            controller = getattr(workspace, "render_controller", None)
            if controller is not None:
                controller.evaluation_failed(curve, exc)
            backgrounds[curve.id] = np.zeros_like(curve.y)
    return backgrounds


def _masked_sample_renderer(workspace: PlotWorkspace) -> None:
    # Render excluded samples using the current project appearance settings.
    curves, x_step, y_step = _displayed_curves(workspace)
    if not curves:
        return
    cache = getattr(workspace, "_curvemole_background_cache", {})
    appearance = workspace.plot_appearance()
    draw_lines, draw_points = plot_mode_flags(str(appearance["data_style"]))

    for index, curve in enumerate(curves):
        subtract = background_removed(workspace, curve.id)
        x = np.asarray(curve.x, dtype=float) + index * x_step
        y = np.asarray(curve.y, dtype=float)
        if subtract:
            y = y - np.asarray(cache.get(curve.id, np.zeros_like(y)), dtype=float)
        y = y + index * y_step
        masked = (
            np.asarray(curve.effective_mask, dtype=bool)
            & np.isfinite(x)
            & np.isfinite(y)
        )
        if not np.any(masked):
            continue
        # Masked samples keep their established neutral-grey visual identity.
        # Size and opacity remain customizable, but spectrum colours never leak into masks.
        colour = colour_with_opacity(
            "#777777",
            int(appearance["masked_opacity"]),
        )
        line_pen = pg.mkPen(
            colour,
            width=float(appearance["data_line_width"]),
            style=qt_pen_style(str(appearance["data_line_style"])),
        )
        symbol = marker_for_curve(appearance, index)
        isolated_x: list[float] = []
        isolated_y: list[float] = []
        runs = _mask_display._true_runs(masked)
        for run in runs:
            if run.size == 1:
                point = int(run[0])
                isolated_x.append(float(x[point]))
                isolated_y.append(float(y[point]))

        if draw_lines:
            for run in runs:
                if run.size == 1:
                    continue
                item = workspace.plot.plot(x[run], y[run], pen=line_pen)
                item._curvemole_masked_data = True
                item.curve_id = curve.id
                item.setZValue(4.0)

        # A single masked sample has no line segment, so it is always rendered
        # as a marker even when the experimental-data mode is Lines.
        if isolated_x and not draw_points:
            item = workspace.plot.plot(
                np.asarray(isolated_x, dtype=float),
                np.asarray(isolated_y, dtype=float),
                pen=None,
                symbol=symbol,
                symbolSize=float(appearance["masked_point_size"]),
                symbolBrush=pg.mkBrush(colour),
                symbolPen=None,
            )
            item._curvemole_masked_data = True
            item.curve_id = curve.id
            item.setZValue(4.0)

        if draw_points:
            item = workspace.plot.plot(
                x[masked],
                y[masked],
                pen=None,
                symbol=symbol,
                symbolSize=float(appearance["masked_point_size"]),
                symbolBrush=pg.mkBrush(colour),
                symbolPen=None,
            )
            item._curvemole_masked_data = True
            item.curve_id = curve.id
            item.setZValue(4.0)


def _label_position(x: np.ndarray, y: np.ndarray) -> tuple[float, float] | None:
    finite = np.isfinite(x) & np.isfinite(y)
    if not np.any(finite):
        return None
    finite_indices = np.flatnonzero(finite)
    values = y[finite]
    maximum = float(np.nanmax(values))
    tolerance = max(abs(maximum) * 1e-10, np.finfo(float).eps)
    maxima = finite_indices[np.isclose(values, maximum, rtol=1e-10, atol=tolerance)]
    index = (
        int(maxima[len(maxima) // 2])
        if len(maxima)
        else int(finite_indices[np.nanargmax(values)])
    )
    return float(x[index]), float(y[index])


def _shift_selected_peak_handle(
    workspace: PlotWorkspace,
    backgrounds: dict[str, np.ndarray],
    y_step: float,
) -> None:
    if background_removed(workspace, workspace._active_curve_id):
        return
    project = workspace._project
    curve_id = workspace._active_curve_id
    component_id = workspace._selected_component_id
    if project is None or not curve_id or not component_id:
        return
    if workspace.display_replays(project.dataset.curve(curve_id)):
        return
    model = project.models.get(curve_id)
    if model is None:
        return
    try:
        component = model.component(component_id)
        curve = project.dataset.curve(curve_id)
    except KeyError:
        return
    if component.is_background or component.operator != "add" or "center" not in component.parameters:
        return
    background = backgrounds.get(curve_id)
    if background is None or not np.any(background):
        return
    centre = float(component.parameters["center"].value)
    finite = np.isfinite(curve.x) & np.isfinite(background)
    if not np.any(finite):
        return
    indices = np.flatnonzero(finite)
    index = int(indices[np.argmin(np.abs(curve.x[finite] - centre))])
    baseline = float(background[index])
    if not np.isfinite(baseline) or baseline == 0.0:
        return
    for handle in workspace._handles:
        if isinstance(handle, pg.TargetItem):
            position = handle.pos()
            handle.setPos(float(position.x()), float(position.y()) + baseline)
            break


def _apply_background_aware_display(
    workspace: PlotWorkspace,
    backgrounds: dict[str, np.ndarray],
) -> None:
    project = workspace._project
    curves, x_step, y_step = _displayed_curves(workspace)
    if project is None or not curves:
        return

    # Data traces.
    # Re-anchor component labels after moving the dashed curves.
    if workspace._show_component_labels and workspace._component_labels:
        specs: list[tuple[Any, float, float]] = []
        for curve in curves:
            subtract = background_removed(workspace, curve.id)
            model = project.models.get(curve.id)
            if model is None:
                continue
            for component in model.components:
                key = (curve.id, component.id)
                if not component.enabled or key not in workspace._component_items:
                    continue
                label = workspace._component_labels_by_key.get(key)
                if label is None:
                    continue
                item = workspace._component_items[key]
                if subtract and component.is_background:
                    label.hide()
                    continue
                label.show()
                x_data, y_data = item.getOriginalDataset()
                if x_data is None or y_data is None:
                    continue
                position = _label_position(np.asarray(x_data), np.asarray(y_data))
                if position is None:
                    continue
                label.setPos(*position)
                specs.append((label, position[0], position[1]))
        workspace._component_label_specs = specs
        workspace._layout_component_labels()

    _shift_selected_peak_handle(workspace, backgrounds, y_step)


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
