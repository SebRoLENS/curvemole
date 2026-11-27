"""Drawing the plot scene: data, model, components, residuals, labels and handles.

SceneRenderer rebuilds the scene of a PlotWorkspace on refresh, reusing scene
items where possible, and lays out component labels. PlotWorkspace keeps
delegating methods with the historical names.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject

from curvemole.core.errors import CurveMoleError
from curvemole.core.models import component_height
from curvemole.core.parameters import resolve_parameter_values
from curvemole.gui.plot_appearance import (
    colour_with_opacity,
    marker_for_curve,
)


def _label_offset(placed, left, top, right, bottom, step, limit):
    """Smallest whole number of upward steps that clears every placed label.

    A placed rectangle forbids the open offset interval (top - its bottom,
    bottom - its top). Merging those intervals finds the answer in one sweep
    instead of re-testing every label at every trial step.
    """
    forbidden = sorted((top - b, bottom - t) for lo, t, r, b in placed if lo < right and left < r)
    merged: list[list[float]] = []
    for low, high in forbidden:
        if merged and low < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], high)
        else:
            merged.append([low, high])
    steps = 0
    for low, high in merged:
        offset = steps * step
        if high <= offset:
            continue
        if low >= offset:
            break
        steps = math.ceil(high / step - 1e-9)
        if steps >= limit:
            return limit * step
    return steps * step


class SceneRenderer(QObject):
    def __init__(self, workspace: Any) -> None:
        super().__init__(workspace)
        self.workspace = workspace

    def _refresh_scene(self, *_: Any) -> None:
        workspace = self.workspace
        initial_view = not workspace._data_items
        # Placement may span many refreshes; do not retain removed scene items
        # (and their complete data arrays) in the mouse-state snapshot.
        workspace._restore_placement_mouse_targets()
        previous = workspace._render_items
        workspace._render_items = {}
        # Hide old labels and keep them in the scene for reuse: removing,
        # destroying and recreating thousands of text items dominated Overlay
        # refreshes. Unused labels simply stay hidden.
        pool = getattr(workspace, "_label_pool", [])
        pool.extend(workspace._component_labels)
        for label in pool:
            label.setVisible(False)
        workspace._label_pool = pool
        retained = {item for _, item in previous.values()} | set(pool)
        for plot in (workspace.plot, workspace.residual_plot):
            for item in tuple(plot.items):
                if item not in retained:
                    plot.removeItem(item)
        workspace.plot.setToolTip("")

        def draw(key, plot, *data, **options):
            entry = previous.pop(key, None)
            if entry is not None and entry[0] is plot and entry[1] in plot.items:
                item = entry[1]
                item.setData(*data, **options)
                item.setVisible(True)
            else:
                item = plot.plot(*data, **options)
            workspace._render_items[key] = (plot, item)
            return item

        def remove_unused():
            for plot, item in previous.values():
                plot.removeItem(item)
        workspace._data_items.clear()
        workspace._error_items.clear()
        workspace._component_items.clear()
        workspace._sum_items.clear()
        workspace._component_labels.clear()
        workspace._component_labels_by_key.clear()
        workspace._component_label_specs.clear()
        workspace._handles.clear()
        workspace._placement_items.clear()
        project = workspace._project
        if project is None or not project.curves:
            remove_unused()
            for session in list(workspace._plugin_plot_sessions.values()):
                session._invalidate()
            workspace.plot.setTitle(workspace.tr("Import data to begin"))
            return
        appearance = workspace._plot_appearance
        mode = workspace.display_mode.currentText()
        curves = [workspace.curve_for_display(curve) for curve in workspace.displayed_curves()]
        x_step = workspace.x_offset.value() if mode == workspace.tr("Waterfall") else 0.0
        y_step = workspace.y_offset.value() if mode == workspace.tr("Waterfall") else 0.0
        try:
            global_values = getattr(workspace, "_render_values", None)
            if global_values is None:
                global_values = getattr(workspace, "_live_parameter_values", None)
            if global_values is None:
                global_values = project.resolved_parameter_values()
        except CurveMoleError:
            # An invalid link in one model must not erase measured data or
            # prevent independent models from being displayed.
            global_values = None
        for index, curve in enumerate(curves):
            x = curve.x + index * x_step
            y = curve.y + index * y_step
            from curvemole.gui.background_display import background_removed
            subtract = background_removed(workspace, curve.id)
            background = getattr(workspace, "_curvemole_background_cache", {}).get(curve.id)
            if background is None:
                background = np.zeros_like(curve.y)
            data_y = y - background if subtract else y
            unmasked = ~curve.effective_mask
            symbol = marker_for_curve(appearance, index)
            data_width = float(appearance["data_line_width"]) * (
                1.35 if curve.id == workspace._active_curve_id else 1.0
            )
            item = draw(("data", curve.id), workspace.plot,
                x[unmasked],
                data_y[unmasked],
                name=curve.name,
                **workspace._plot_options(
                    str(appearance["data_style"]),
                    curve.colour,
                    data_width,
                    str(appearance["data_line_style"]),
                    int(appearance["data_opacity"]),
                    float(appearance["data_point_size"]),
                    symbol,
                ),
            )
            item.curve_id = curve.id
            workspace._data_items[curve.id] = item
            if workspace.error_bars_toggle.isChecked():
                from curvemole.gui.background_display import (
                    background_removed,
                )
                from curvemole.gui.data_errors import error_bar_item
                bar_y = y
                if background_removed(workspace, curve.id):
                    bar_y = y - background
                errors = error_bar_item(curve, x, bar_y, unmasked,
                    colour_with_opacity(curve.colour, int(appearance["data_opacity"])))
                if errors is not None:
                    workspace.plot.addItem(errors)
                    workspace._error_items[curve.id] = errors
            for mask in (() if getattr(workspace, "_lightweight_masks", False) else curve.masks.values()):
                for lower, upper in mask.effective_ranges(curve.x):
                    if math.isclose(lower, upper):
                        continue
                    region = pg.LinearRegionItem(
                        values=(lower + index * x_step, upper + index * x_step),
                        movable=False,
                        brush=pg.mkBrush(120, 120, 120, 38),
                        pen=pg.mkPen(120, 120, 120, 70),
                    )
                    region.setZValue(-20)
                    workspace.plot.addItem(region)
            model = None if workspace.display_replays(curve) else project.models.get(curve.id)
            if model and model.components:
                try:
                    errors = getattr(getattr(workspace, "render_controller", None), "errors", {})
                    if curve.id in errors:
                        raise CurveMoleError(errors[curve.id])
                    values = global_values
                    if values is None:
                        values = resolve_parameter_values(
                            project.parameter_map(), paths=model.parameter_map(curve.id),
                        )
                    cached = (getattr(workspace, "_render_models", None) or {}).get(curve.id)
                    if cached is None:
                        cached = model.evaluate(curve.x, curve_id=curve.id, values=values,
                                                registry=workspace.registry, components=True)
                    total, component_arrays = cached
                except CurveMoleError as exc:
                    workspace.plot.setToolTip(
                        f"Model unavailable: {exc}. Review function operators, parameter links, "
                        "or File → Plugin Manager."
                    )
                    continue
                total = total + index * y_step
                sum_item = draw(("sum", curve.id), workspace.plot,
                    x,
                    total - background if subtract else total,
                    name=f"{curve.name} Model sum",
                    **workspace._plot_options(
                        str(appearance["function_style"]),
                        str(appearance["model_sum_colour"]),
                        float(appearance["function_sum_line_width"]),
                        str(appearance["function_sum_line_style"]),
                        int(appearance["function_opacity"]),
                        float(appearance["function_point_size"]),
                        symbol,
                    ),
                )
                sum_item.curve_id = curve.id
                workspace._sum_items[curve.id] = sum_item
                residual = curve.y - (total - index * y_step)
                draw(("residual", curve.id), workspace.residual_plot,
                    x[unmasked],
                    residual[unmasked],
                    **workspace._plot_options(
                        str(appearance["residual_style"]),
                        curve.colour,
                        float(appearance["residual_line_width"]),
                        str(appearance["residual_line_style"]),
                        int(appearance["residual_opacity"]),
                        float(appearance["residual_point_size"]),
                        symbol,
                    ),
                )
                for component in model.components:
                    if not component.enabled or component.id not in component_arrays:
                        continue
                    component_y = component_arrays[component.id] + index * y_step
                    if not subtract and not component.is_background:
                        if component.operator == "add":
                            component_y = background + component_y
                        elif component.operator == "subtract":
                            component_y = background - component_arrays[component.id] + index * y_step
                    selected = (
                        component.id == workspace._selected_component_id
                        and curve.id == workspace._active_curve_id
                    )
                    colour = (
                        str(appearance["selected_component_colour"])
                        if selected
                        else str(appearance["component_colour"])
                    )
                    width = (
                        float(appearance["function_selected_line_width"])
                        if selected
                        else float(appearance["function_component_line_width"])
                    )
                    component_item = draw(("component", curve.id, component.id), workspace.plot,
                        x,
                        component_y,
                        **workspace._plot_options(
                            str(appearance["function_style"]),
                            colour,
                            width,
                            str(appearance["function_component_line_style"]),
                            int(appearance["function_opacity"]),
                            float(appearance["function_point_size"]),
                            symbol,
                        ),
                    )
                    component_item.setVisible(not (subtract and component.is_background))
                    component_item.component_id = component.id
                    component_item.curve_id = curve.id
                    component_item.curve.setClickable(
                        True,
                        width=max(
                            8.0,
                            float(appearance["function_point_size"]) + 4.0,
                        ),
                    )
                    if not getattr(component_item, "_curvemole_selection_connected", False):
                        component_item.sigClicked.connect(
                            lambda item, event, curve_id=curve.id, component_id=component.id: (
                                workspace.componentOnCurveSelected.emit(curve_id, component_id)
                            )
                        )
                        component_item._curvemole_selection_connected = True
                    key = (curve.id, component.id)
                    workspace._component_items[key] = component_item
                    if workspace._show_component_labels:
                        label = workspace._add_component_label(component.name, x, component_y)
                        if label is not None:
                            workspace._component_labels_by_key[key] = label
                if curve.id == workspace._active_curve_id and workspace._selected_component_id:
                    workspace._add_component_handles(
                        curve,
                        model,
                        index * x_step,
                        index * y_step,
                    )
        remove_unused()
        if curves:
            first = curves[0]
            workspace.plot.setLabel("bottom", first.x_label, units=first.x_unit or None)
            workspace.plot.setLabel("left", first.y_label, units=first.y_unit or None)
            workspace.residual_plot.setLabel(
                "bottom",
                first.x_label,
                units=first.x_unit or None,
            )
        workspace._apply_grid_appearance()
        workspace._layout_component_labels()
        workspace._render_placement_preview()
        workspace.point_editor.refresh()
        for session in list(workspace._plugin_plot_sessions.values()):
            session.refresh()
        workspace._sync_placement_mouse_targets()
        workspace.plot.setTitle("")
        if initial_view:
            workspace.auto_range()

    def _add_component_label(self, name: str, x: np.ndarray, y: np.ndarray) -> pg.TextItem | None:
        workspace = self.workspace
        finite = np.isfinite(x) & np.isfinite(y)
        if not np.any(finite):
            return
        finite_indices = np.flatnonzero(finite)
        values = y[finite]
        maximum = float(np.nanmax(values))
        tolerance = max(abs(maximum) * 1e-10, np.finfo(float).eps)
        maxima = finite_indices[np.isclose(values, maximum, rtol=1e-10, atol=tolerance)]
        index = int(maxima[len(maxima) // 2]) if len(maxima) else int(finite_indices[np.nanargmax(values)])
        x_position = float(x[index])
        y_position = float(y[index])
        pool = getattr(workspace, "_label_pool", None)
        if pool:
            label = pool.pop()
            label.setText(name)
            label.setVisible(True)
        else:
            label = pg.TextItem(
                text=name,
                color="#202020",
                anchor=(0.5, 1.0),
                border=pg.mkPen(100, 100, 100, 150),
                fill=pg.mkBrush(255, 255, 255, 220),
            )
            label.setZValue(70)
        if label.scene() is None:
            workspace.plot.addItem(label)
        label.setPos(x_position, y_position)
        workspace._component_labels.append(label)
        workspace._component_label_specs.append((label, x_position, y_position))
        return label

    def _layout_component_labels(self, *_: Any) -> None:
        workspace = self.workspace
        if workspace._laying_out_labels or not workspace._component_label_specs:
            return
        workspace._laying_out_labels = True
        try:
            _, y_per_pixel = workspace.view_box.viewPixelSize()
            step_scale = abs(float(y_per_pixel)) if math.isfinite(float(y_per_pixel)) else 0.0
            if step_scale == 0.0:
                return
            direction = -1.0 if bool(workspace.view_box.state.get("yInverted", False)) else 1.0
            limit = len(workspace._component_label_specs) + 3
            # Scene rectangles as (left, top, right, bottom). Labels move up the
            # screen in whole steps until they clear every earlier label. Only
            # one Qt geometry query per label: the layout runs on every refresh
            # and view change, and overlays can carry thousands of labels.
            placed: list[tuple[float, float, float, float]] = []
            view_top = workspace.view_box.sceneBoundingRect().top()
            for label, base_x, base_y in sorted(workspace._component_label_specs, key=lambda item: item[1]):
                label.setPos(base_x, base_y)
                rect = label.sceneBoundingRect().adjusted(-3.0, -2.0, 3.0, 2.0)
                left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
                step = max(16.0, rect.height() + 4.0)
                offset = _label_offset(placed, left, top, right, bottom, step, limit)
                if top - offset < view_top:
                    # Keep the label inside the plot instead of cutting it off at
                    # the top edge (a negative offset moves it down over its peak).
                    offset = top - view_top
                if offset:
                    label.setPos(base_x, base_y + direction * offset * step_scale)
                placed.append((left, top - offset, right, bottom - offset))
        finally:
            workspace._laying_out_labels = False

    def _add_component_handles(
        self, curve: Any, model: Any, x_offset: float, y_offset: float
    ) -> None:
        workspace = self.workspace
        try:
            component = model.component(workspace._selected_component_id)
        except KeyError:
            return
        if component.function_id not in workspace.registry.identifiers():
            return
        definition = workspace.registry.get(component.function_id)
        if component.function_id == "cubic_spline":
            for index, x_node in enumerate(component.metadata.get("x_nodes", [])):
                parameter = component.parameters.get(f"y{index}")
                if parameter is None:
                    continue
                target = pg.TargetItem(
                    pos=(float(x_node) + x_offset, parameter.value + y_offset),
                    size=10,
                    movable=True,
                    pen=pg.mkPen("#009E73", width=2),
                    brush=pg.mkBrush(255, 255, 255, 180),
                )
                target.setToolTip(
                    workspace.tr(
                        "Drag an unlocked spline y node. Fixed nodes stay locked unless Ctrl is held; "
                        "the x position always remains fixed."
                    )
                )
                workspace.plot.addItem(target)
                target.sigPositionChangeFinished.connect(
                    lambda item, component_id=component.id, node=index, xo=float(x_node)
                    + x_offset, yo=y_offset: workspace._emit_spline_node(
                        item, component_id, node, xo, yo
                    )
                )
                workspace._handles.append(target)
            return
        if definition.kind != "peak" or "center" not in component.parameters:
            return
        height = component_height(component, registry=workspace.registry)
        if height is None:
            return
        centre = component.parameters["center"].value
        target = pg.TargetItem(
            pos=(centre + x_offset, height + y_offset),
            size=12,
            movable=True,
            pen=pg.mkPen("#009E73", width=2),
            brush=pg.mkBrush(255, 255, 255, 180),
        )
        target.setToolTip(workspace.tr("Drag peak centre/height. Hold Ctrl to change a fixed value."))
        workspace.plot.addItem(target)
        target.sigPositionChangeFinished.connect(
            lambda item: workspace._emit_peak(component.id, item.pos(), x_offset, y_offset)
        )
        workspace._handles.append(target)
        derived = definition.derived_values(
            {name: parameter.value for name, parameter in component.parameters.items()}, component.metadata
        )
        fwhm = derived.get("FWHM")
        if fwhm and fwhm > 0:
            for side in (-1, 1):
                line = pg.InfiniteLine(
                    pos=centre + x_offset + side * fwhm / 2,
                    angle=90,
                    movable=True,
                    pen=pg.mkPen("#009E73", width=1.2),
                    hoverPen=pg.mkPen("#E69F00", width=2),
                )
                line.setToolTip(workspace.tr("Drag to change FWHM. Hold Ctrl for a fixed width."))
                workspace.plot.addItem(line)
                line.sigPositionChangeFinished.connect(
                    lambda item, component_id=component.id, c=centre + x_offset: workspace._emit_width(
                        component_id, 2 * abs(float(item.value()) - c)
                    )
                )
                workspace._handles.append(line)
