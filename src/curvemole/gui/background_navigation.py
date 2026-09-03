"""Spectrum navigation and background-aware fit display extensions."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu, QStyle, QToolBar, QToolButton, QTreeWidgetItem

from curvemole.core.calculator import apply_background_subtraction
from curvemole.core.data import Curve, CurveState
from curvemole.gui import mask_display as _mask_display
from curvemole.gui.main_window import CallbackCommand, MainWindow
from curvemole.gui.plot import PlotWorkspace


def _displayed_curves(workspace: PlotWorkspace) -> tuple[list[Curve], float, float]:
    project = workspace._project
    if project is None or not project.curves:
        return [], 0.0, 0.0
    mode = workspace.display_mode.currentText()
    if mode == workspace.tr("Single"):
        curves = (
            [project.dataset.curve(workspace._active_curve_id)]
            if workspace._active_curve_id
            else []
        )
    else:
        curves = [curve for curve in project.curves if curve.visible]
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
        resolved = values if values is not None else project.resolved_parameter_values()
        background = np.asarray(
            model.background(
                curve.x,
                curve_id=curve.id,
                values=resolved,
                registry=workspace.registry,
            ),
            dtype=float,
        )
    except Exception:
        return np.zeros_like(curve.y, dtype=float)
    usable = np.isfinite(curve.x) & np.isfinite(curve.y)
    if background.shape != curve.y.shape or np.any(usable & ~np.isfinite(background)):
        return np.zeros_like(curve.y, dtype=float)
    return background


def _background_cache(workspace: PlotWorkspace) -> dict[str, np.ndarray]:
    project = workspace._project
    curves, _, _ = _displayed_curves(workspace)
    if project is None:
        return {}
    try:
        values = project.resolved_parameter_values()
    except Exception:
        values = None
    return {curve.id: _background_array(workspace, curve, values) for curve in curves}


def _masked_sample_renderer(workspace: PlotWorkspace) -> None:
    """Render excluded samples in the same visual baseline mode as the main data."""
    curves, x_step, y_step = _displayed_curves(workspace)
    if not curves:
        return
    subtract = bool(getattr(workspace, "_background_subtracted_view", False))
    cache = getattr(workspace, "_curvemole_background_cache", {})
    line_pen = pg.mkPen(125, 125, 125, 190, width=1.0)
    marker_brush = pg.mkBrush(125, 125, 125, 190)

    for index, curve in enumerate(curves):
        x = np.asarray(curve.x, dtype=float) + index * x_step
        y = np.asarray(curve.y, dtype=float)
        if subtract:
            y = y - np.asarray(cache.get(curve.id, np.zeros_like(y)), dtype=float)
        y = y + index * y_step
        masked = np.asarray(curve.effective_mask, dtype=bool) & np.isfinite(x) & np.isfinite(y)
        isolated_x: list[float] = []
        isolated_y: list[float] = []

        for run in _mask_display._true_runs(masked):
            if run.size == 1:
                point = int(run[0])
                isolated_x.append(float(x[point]))
                isolated_y.append(float(y[point]))
                continue
            item = workspace.plot.plot(x[run], y[run], pen=line_pen)
            item._curvemole_masked_data = True
            item.curve_id = curve.id
            item.setZValue(4.0)

        if isolated_x:
            item = workspace.plot.plot(
                np.asarray(isolated_x, dtype=float),
                np.asarray(isolated_y, dtype=float),
                pen=None,
                symbol="o",
                symbolSize=3.5,
                symbolBrush=marker_brush,
                symbolPen=None,
            )
            item._curvemole_masked_data = True
            item.curve_id = curve.id
            item.setZValue(4.0)


def _item_name(item: pg.PlotDataItem) -> str:
    try:
        return str(item.name() or "")
    except Exception:
        return str(item.opts.get("name") or "")


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
    if bool(getattr(workspace, "_background_subtracted_view", False)):
        return
    project = workspace._project
    curve_id = workspace._active_curve_id
    component_id = workspace._selected_component_id
    if project is None or not curve_id or not component_id:
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
    subtract = bool(getattr(workspace, "_background_subtracted_view", False))

    # Data traces.
    for index, curve in enumerate(curves):
        item = workspace._data_items.get(curve.id)
        if item is None:
            continue
        background = backgrounds.get(curve.id, np.zeros_like(curve.y, dtype=float))
        unmasked = ~curve.effective_mask
        display_y = np.asarray(curve.y, dtype=float)
        if subtract:
            display_y = display_y - background
        item.setData(
            np.asarray(curve.x, dtype=float)[unmasked] + index * x_step,
            display_y[unmasked] + index * y_step,
        )

    # Model sums are named but not otherwise retained by PlotWorkspace.
    data_item_ids = {id(item) for item in workspace._data_items.values()}
    component_item_ids = {id(item) for item in workspace._component_items.values()}
    sum_candidates = [
        item
        for item in workspace.plot.listDataItems()
        if id(item) not in data_item_ids
        and id(item) not in component_item_ids
        and _item_name(item).endswith(" Model sum")
    ]
    used_sum_items: set[int] = set()
    for curve in curves:
        model = project.models.get(curve.id)
        if model is None or not model.components:
            continue
        wanted = f"{curve.name} Model sum"
        sum_item = next(
            (
                item
                for item in sum_candidates
                if id(item) not in used_sum_items and _item_name(item) == wanted
            ),
            None,
        )
        if sum_item is None:
            continue
        used_sum_items.add(id(sum_item))
        sum_item.curve_id = curve.id
        if subtract:
            x_data, y_data = sum_item.getOriginalDataset()
            background = backgrounds.get(curve.id)
            if (
                x_data is not None
                and y_data is not None
                and background is not None
                and len(y_data) == len(background)
            ):
                sum_item.setData(np.asarray(x_data), np.asarray(y_data) - background)

    # Individual model functions: normal view sits additive peaks on their
    # background baseline; visual subtraction returns them to zero baseline.
    for index, curve in enumerate(curves):
        model = project.models.get(curve.id)
        if model is None:
            continue
        background = backgrounds.get(curve.id, np.zeros_like(curve.y, dtype=float))
        y_offset = index * y_step
        for component in model.components:
            item = workspace._component_items.get(component.id)
            if not component.enabled or item is None:
                continue
            x_data, y_data = item.getOriginalDataset()
            if x_data is None or y_data is None:
                continue
            raw = np.asarray(y_data, dtype=float) - y_offset
            if subtract and component.is_background:
                item.setVisible(False)
                continue
            item.setVisible(True)
            if subtract or component.is_background:
                display = raw
            elif component.operator == "add":
                display = background + raw
            elif component.operator == "subtract":
                display = background - raw
            else:
                display = raw
            item.setData(np.asarray(x_data), display + y_offset)

    # Re-anchor component labels after moving the dashed curves.
    if workspace._show_component_labels and workspace._component_labels:
        label_index = 0
        specs: list[tuple[Any, float, float]] = []
        for curve in curves:
            model = project.models.get(curve.id)
            if model is None:
                continue
            for component in model.components:
                if not component.enabled or component.id not in workspace._component_items:
                    continue
                if label_index >= len(workspace._component_labels):
                    break
                label = workspace._component_labels[label_index]
                label_index += 1
                item = workspace._component_items[component.id]
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
    if bool(getattr(workspace, "_background_subtracted_view", False)):
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

    # The existing masked-sample wrapper resolves this global at runtime.
    _mask_display._render_masked_samples = _masked_sample_renderer

    original_refresh = PlotWorkspace.refresh
    original_emit_peak = PlotWorkspace._emit_peak

    def refresh(workspace: PlotWorkspace, *args: Any) -> None:
        backgrounds = _background_cache(workspace)
        workspace._curvemole_background_cache = backgrounds
        try:
            original_refresh(workspace, *args)
            _apply_background_aware_display(workspace, backgrounds)
        finally:
            if hasattr(workspace, "_curvemole_background_cache"):
                delattr(workspace, "_curvemole_background_cache")

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

    PlotWorkspace.refresh = refresh
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
        target = max(0, min(len(items) - 1, index + delta))
        if target == index:
            return
    except ValueError:
        target = 0 if delta > 0 else len(items) - 1
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
    if not window._ensure_editable():
        return

    try:
        global_values = window.project.resolved_parameter_values()
    except Exception as exc:
        window._show_error(window.tr("Subtract all backgrounds"), exc)
        return

    prepared: list[tuple[Curve, Any, list[Any], np.ndarray]] = []
    for curve in window.project.curves:
        model = window.project.models.get(curve.id)
        if model is None:
            continue
        marked = [
            component
            for component in model.components
            if component.enabled and component.is_background
        ]
        if not marked:
            continue
        try:
            background = np.asarray(
                model.background(
                    curve.x,
                    curve_id=curve.id,
                    values=global_values,
                    registry=window.registry,
                ),
                dtype=float,
            )
        except Exception as exc:
            window._show_error(window.tr("Subtract all backgrounds"), exc)
            return
        usable = np.isfinite(curve.x) & np.isfinite(curve.y)
        if background.shape != curve.y.shape or np.any(usable & ~np.isfinite(background)):
            window._notify(
                window.tr("A marked background contains invalid values; no spectrum was changed."),
                warning=True,
            )
            return
        prepared.append((curve, model, marked, background))

    if not prepared:
        window._notify(
            window.tr("No enabled function marked as background was found."),
            warning=True,
        )
        return

    records: list[
        tuple[
            Curve,
            Any,
            Any,
            dict[str, tuple[bool, bool]],
            dict[str, tuple[bool, bool]],
            CurveState,
        ]
    ] = []
    try:
        for curve, model, marked, background in prepared:
            component_ids = [component.id for component in marked]
            transformation = apply_background_subtraction(
                curve,
                background,
                method="model_components_global",
                description=window.tr("Subtract marked model background (all spectra)"),
                parameters={
                    "component_ids": component_ids,
                    "component_names": [component.name for component in marked],
                },
            )
            curve.undo_transformation()
            before = {
                component.id: (component.is_background, component.enabled)
                for component in marked
            }
            after = {component.id: (True, False) for component in marked}
            records.append((curve, model, transformation, before, after, curve.state))
    except Exception as exc:
        window._show_error(window.tr("Subtract all backgrounds"), exc)
        return

    def redo() -> None:
        for curve, model, transformation, _before, after, state_before in records:
            if curve.redo_transformations and curve.redo_transformations[-1] is transformation:
                curve.redo_transformation()
            elif transformation not in curve.transformations:
                curve.apply_transformation(transformation)
            _restore_component_states(model, after)
            if state_before == CurveState.FITTED:
                curve.state = CurveState.MODIFIED

    def undo() -> None:
        for curve, model, transformation, before, _after, state_before in reversed(records):
            if curve.transformations and curve.transformations[-1] is transformation:
                curve.undo_transformation()
            _restore_component_states(model, before)
            curve.state = state_before

    def wrapped(operation: Callable[[], None]) -> None:
        operation()
        try:
            window.project.touch()
        except PermissionError as exc:
            window._show_error(window.tr("Read-only project"), exc)
        window.refresh_all()

    window.undo_stack.push(
        CallbackCommand(
            window.tr("Subtract backgrounds from all spectra"),
            lambda: wrapped(redo),
            lambda: wrapped(undo),
        )
    )
    window._notify(
        window.tr("Background subtracted from ")
        + str(len(records))
        + window.tr(" spectrum/spectra. Marked background functions were disabled.")
    )


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
        toolbar.insertAction(window.add_component_action, window.subtract_all_backgrounds_action)
        toolbar.insertAction(window.add_component_action, window.background_subtracted_view_action)
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
