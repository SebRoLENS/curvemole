"""General manual-point initialization for every registered model function."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any, Iterable

import numpy as np
import pyqtgraph as pg
from scipy.optimize import least_squares
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QMessageBox

from curvemole.core.initialization import PeakSuggestion, initialise_peak_component, initialise_spline_component
from curvemole.core.models import Component
from curvemole.gui.dialogs import AddComponentDialog
from curvemole.gui.main_window import MainWindow
from curvemole.gui.panels import FunctionBuilderPanel
from curvemole.gui.plot import PlotWorkspace


def manual_points_default(definition: Any) -> bool:
    """Return the function's preferred creation mode.

    Linear and cubic-spline functions are manual-point-first by default. Custom
    functions can override this through ``custom_metadata`` in Function Builder.
    """
    marker = definition.custom_metadata.get("manual_points_default")
    if marker is not None:
        return bool(marker)
    return definition.identifier in {"linear", "cubic_spline"}


def minimum_manual_points(component: Component) -> int:
    """Require enough explicit points to determine the component sensibly."""
    if component.function_id == "cubic_spline":
        return 2
    return max(2, len(component.parameters))


def initialise_component_from_points(
    component: Component,
    points: Iterable[tuple[float, float]],
    *,
    registry: Any,
) -> Component:
    """Initialize any function from explicit graph points and lock its parameters."""
    selected = sorted((float(x), float(y)) for x, y in points)
    if not selected:
        raise ValueError("At least one manual point is required.")
    if any(not math.isfinite(value) for point in selected for value in point):
        raise ValueError("Manual points must be finite.")

    required = minimum_manual_points(component)
    if len(selected) < required:
        raise ValueError(f"This function needs at least {required} manual points.")

    if component.function_id == "cubic_spline":
        initialise_spline_component(component, selected, registry=registry)
        return component

    x = np.asarray([point[0] for point in selected], dtype=float)
    y = np.asarray([point[1] for point in selected], dtype=float)
    definition = registry.get(component.function_id)

    # Give common functions a physically meaningful starting estimate before
    # the generic least-squares refinement.
    if component.function_id == "linear":
        slope, intercept = np.polyfit(x, y, 1)
        component.parameters["slope"].value = float(slope)
        component.parameters["intercept"].value = float(intercept)
    elif component.function_id == "constant":
        component.parameters["offset"].value = float(np.mean(y))
    elif definition.kind == "peak":
        baseline = float(np.min(y))
        peak_index = int(np.argmax(np.abs(y - baseline)))
        span = max(float(np.ptp(x)), np.finfo(float).eps)
        suggestion = PeakSuggestion(
            x=float(x[peak_index]),
            height=float(y[peak_index] - baseline),
            fwhm=max(span / 2.0, np.finfo(float).eps),
            prominence=float(abs(y[peak_index] - baseline)),
            sign=1,
        )
        initialise_peak_component(component, suggestion, registry=registry)

    names = list(component.parameters)
    initial = np.asarray([component.parameters[name].value for name in names], dtype=float)
    lower = np.asarray([component.parameters[name].minimum for name in names], dtype=float)
    upper = np.asarray([component.parameters[name].maximum for name in names], dtype=float)
    initial = np.minimum(np.maximum(initial, lower), upper)

    scale = max(float(np.ptp(y)), float(np.max(np.abs(y))), 1.0)

    def residual(values: np.ndarray) -> np.ndarray:
        mapping = {name: float(value) for name, value in zip(names, values, strict=True)}
        try:
            calculated = definition.evaluate(x, mapping, component.metadata)
        except Exception:
            return np.full(len(x), 1e12, dtype=float)
        result = (np.asarray(calculated, dtype=float) - y) / scale
        if not np.all(np.isfinite(result)):
            return np.full(len(x), 1e12, dtype=float)
        return result

    if names:
        fitted = least_squares(residual, initial, bounds=(lower, upper), max_nfev=5000)
        if fitted.success and np.all(np.isfinite(fitted.x)):
            for name, value in zip(names, fitted.x, strict=True):
                component.parameters[name].value = float(value)

    for parameter in component.parameters.values():
        parameter.fixed = True
        parameter.validate()
    return component


def _install_add_component_dialog() -> None:
    if getattr(AddComponentDialog, "_curvemole_manual_points", False):
        return
    original_init = AddComponentDialog.__init__

    def init(dialog: AddComponentDialog, *args: Any, **kwargs: Any) -> None:
        original_init(dialog, *args, **kwargs)
        dialog.manual_points = QCheckBox(
            dialog.tr("Initialize from manually selected points on the graph")
        )
        dialog.manual_points.setToolTip(
            dialog.tr(
                "When enabled, click explicit graph points to initialize the function. "
                "Parameters created from those points are locked by default."
            )
        )
        # Place the option immediately above the description / dialog buttons.
        layout = dialog.layout()
        layout.insertWidget(max(0, layout.count() - 2), dialog.manual_points)

        def sync_default() -> None:
            definition = dialog.registry.get(dialog.function.currentData())
            dialog.manual_points.setChecked(manual_points_default(definition))

        dialog.function.currentIndexChanged.connect(lambda *_: sync_default())
        sync_default()

    def use_manual_points(dialog: AddComponentDialog) -> bool:
        return bool(dialog.manual_points.isChecked())

    AddComponentDialog.__init__ = init
    AddComponentDialog.use_manual_points = use_manual_points
    AddComponentDialog._curvemole_manual_points = True


def _install_function_builder() -> None:
    if getattr(FunctionBuilderPanel, "_curvemole_manual_points", False):
        return
    original_init = FunctionBuilderPanel.__init__
    original_add = FunctionBuilderPanel._add

    def init(panel: FunctionBuilderPanel, *args: Any, **kwargs: Any) -> None:
        original_init(panel, *args, **kwargs)
        panel.manual_points_default = QCheckBox(
            panel.tr("Use manual-point initialization by default")
        )
        panel.manual_points_default.setToolTip(
            panel.tr(
                "Users can still override this in Add component. Manual-point initialization "
                "locks the resulting parameters by default."
            )
        )
        panel.layout().insertRow(3, panel.tr("Default insertion"), panel.manual_points_default)

    def add(panel: FunctionBuilderPanel) -> None:
        identifier = re.sub(
            r"[^a-z0-9_]+", "_", panel.identifier.text().strip().lower()
        ).strip("_")
        original_add(panel)
        if not identifier:
            return
        try:
            definition = panel.registry.get(identifier)
        except Exception:
            return
        enabled = bool(panel.manual_points_default.isChecked())
        definition.custom_metadata["manual_points_default"] = enabled
        if panel.project is not None:
            for value in panel.project.custom_functions:
                if value.get("identifier") == identifier:
                    value["manual_points_default"] = enabled
            panel.project.touch()

    FunctionBuilderPanel.__init__ = init
    FunctionBuilderPanel._add = add
    FunctionBuilderPanel._curvemole_manual_points = True


def _install_plot_workspace() -> None:
    if getattr(PlotWorkspace, "_curvemole_general_manual_points", False):
        return
    original_begin_spline = PlotWorkspace.begin_spline_placement
    original_update_instruction = PlotWorkspace._update_spline_instruction
    original_render = PlotWorkspace._render_placement_preview
    original_finish = PlotWorkspace.finish_placement
    original_cancel = PlotWorkspace.cancel_placement

    def begin_manual_point_placement(
        workspace: PlotWorkspace,
        name: str,
        function_id: str,
        minimum_points: int,
    ) -> None:
        original_begin_spline(workspace, name)
        workspace._manual_points_active = True
        workspace._manual_points_function_id = function_id
        workspace._manual_points_minimum = max(1, int(minimum_points))
        workspace._update_spline_instruction()

    def update_instruction(workspace: PlotWorkspace) -> None:
        if not getattr(workspace, "_manual_points_active", False):
            original_update_instruction(workspace)
            return
        count = len(workspace._spline_points)
        required = int(getattr(workspace, "_manual_points_minimum", 2))
        workspace.placement_label.setText(
            workspace.tr("Place explicit points for ")
            + workspace._placement_name
            + workspace.tr(
                ": left-click adds a point, right-click removes the nearest point, "
                "left-drag pans, and the mouse wheel zooms. "
            )
            + f"{count}/{required} "
            + workspace.tr("minimum points. Press Finish when done; Esc cancels.")
        )
        workspace.undo_point_button.setEnabled(count > 0)
        workspace.finish_placement_button.setEnabled(count >= required)

    def render(workspace: PlotWorkspace) -> None:
        if not getattr(workspace, "_manual_points_active", False):
            original_render(workspace)
            return
        workspace._clear_placement_items()
        if workspace._project is None or not workspace._active_curve_id or not workspace._spline_points:
            return
        x_offset, y_offset = workspace._active_display_offsets()
        ordered = sorted(workspace._spline_points)
        node_x = np.asarray([point[0] for point in ordered], dtype=float)
        node_y = np.asarray([point[1] for point in ordered], dtype=float)
        markers = workspace.plot.plot(
            node_x + x_offset,
            node_y + y_offset,
            pen=pg.mkPen("#009E73", width=1, style=Qt.PenStyle.DashLine),
            symbol="o",
            symbolSize=9,
            symbolBrush=pg.mkBrush("#009E73"),
            symbolPen=pg.mkPen("#ffffff", width=1),
        )
        workspace._placement_items.append(markers)

    def finish(workspace: PlotWorkspace) -> None:
        if not getattr(workspace, "_manual_points_active", False):
            original_finish(workspace)
            return
        required = int(getattr(workspace, "_manual_points_minimum", 2))
        if len(workspace._spline_points) < required:
            workspace._update_spline_instruction()
            return
        points = sorted(workspace._spline_points)
        workspace._manual_points_active = False
        workspace._end_placement()
        workspace.splinePlacementFinished.emit(points)

    def cancel(workspace: PlotWorkspace) -> None:
        workspace._manual_points_active = False
        original_cancel(workspace)

    PlotWorkspace.begin_manual_point_placement = begin_manual_point_placement
    PlotWorkspace._update_spline_instruction = update_instruction
    PlotWorkspace._render_placement_preview = render
    PlotWorkspace.finish_placement = finish
    PlotWorkspace.cancel_placement = cancel
    PlotWorkspace._curvemole_general_manual_points = True


def _install_main_window() -> None:
    if getattr(MainWindow, "_curvemole_general_manual_points", False):
        return
    original_load_custom_functions = MainWindow._load_custom_functions
    original_graphical_spline_placed = MainWindow._graphical_spline_placed

    def load_custom_functions(window: MainWindow) -> None:
        original_load_custom_functions(window)
        for value in window.project.custom_functions:
            identifier = str(value.get("identifier", ""))
            if not identifier:
                continue
            try:
                definition = window.registry.get(identifier)
            except Exception:
                continue
            if "manual_points_default" in value:
                definition.custom_metadata["manual_points_default"] = bool(
                    value["manual_points_default"]
                )

    def add_component(window: MainWindow) -> None:
        if not window._ensure_editable():
            return
        if not window.active_curve_id:
            window._notify(window.tr("Activate a curve first."), warning=True)
            return
        curve = window.project.dataset.curve(window.active_curve_id)
        window.plot_workspace.cancel_placement()
        dialog = AddComponentDialog(window.registry, curve, window)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            component = dialog.component()
            definition = window.registry.get(component.function_id)
            use_points = bool(dialog.use_manual_points())

            if definition.kind == "peak":
                window.last_peak_function_id = component.function_id
                window.settings.setValue("last_peak_function", component.function_id)

            if use_points:
                window._pending_component = component
                window._pending_component_curve_id = window.active_curve_id
                window._pending_manual_points = True
                required = minimum_manual_points(component)
                window.plot_workspace.begin_manual_point_placement(
                    definition.display_name,
                    component.function_id,
                    required,
                )
                window._notify(
                    window.tr("Select explicit graph points, then press Finish. ")
                    + window.tr("The resulting parameters will be locked by default.")
                )
                return

            window._pending_manual_points = False
            if definition.kind == "peak":
                window._pending_component = component
                window._pending_component_curve_id = window.active_curve_id
                window.plot_workspace.begin_peak_placement(definition.display_name)
                window._notify(
                    window.tr("Click the peak centre and drag horizontally to set its initial FWHM.")
                )
                return

            if component.function_id == "cubic_spline":
                # Free-mode spline: initialize the dialog's default x nodes from
                # the active curve, but leave y parameters free for fitting.
                nodes = np.asarray(component.metadata.get("x_nodes", []), dtype=float)
                finite = np.isfinite(curve.x) & np.isfinite(curve.y)
                if len(nodes) >= 2 and np.any(finite):
                    order = np.argsort(curve.x[finite])
                    xs = curve.x[finite][order]
                    ys = curve.y[finite][order]
                    for index, node in enumerate(nodes):
                        parameter = component.parameters.get(f"y{index}")
                        if parameter is not None:
                            parameter.value = float(np.interp(node, xs, ys))
                            parameter.fixed = False
            window._commit_component(component, window.active_curve_id)
        except Exception as exc:
            window._show_error(window.tr("Add component"), exc)

    def graphical_points_placed(window: MainWindow, points: object) -> None:
        if not bool(getattr(window, "_pending_manual_points", False)):
            original_graphical_spline_placed(window, points)
            return
        selected = [(float(x), float(y)) for x, y in list(points)]
        component = window._pending_component
        curve_id = window._pending_component_curve_id
        window._pending_component = None
        window._pending_component_curve_id = None
        window._pending_manual_points = False
        if component is None or curve_id is None:
            return
        try:
            initialise_component_from_points(component, selected, registry=window.registry)
            window._commit_component(component, curve_id)
        except Exception as exc:
            window._show_error(window.tr("Manual-point initialization"), exc)

    MainWindow._load_custom_functions = load_custom_functions
    MainWindow.add_component = add_component
    MainWindow._graphical_spline_placed = graphical_points_placed
    MainWindow._curvemole_general_manual_points = True


def install_manual_point_support() -> None:
    """Install the generalized manual-point UI before the main window is built."""
    _install_add_component_dialog()
    _install_function_builder()
    _install_plot_workspace()
    _install_main_window()
