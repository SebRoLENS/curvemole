"""Preserve interactive plot zoom while Quick Fit is running and completes."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QObject

from curvemole.gui.main_window import MainWindow

_ORIGINAL_QUICK_FIT = MainWindow.quick_fit
_ORIGINAL_FIT_FINISHED = MainWindow._fit_finished
_ORIGINAL_TASK_DONE = MainWindow._task_done


class _QuickFitWheelZoomFilter(QObject):
    """Guarantee wheel zoom on the main plot while Quick Fit is active."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self.window = window

    def eventFilter(self, watched: QObject, event: Any) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.Wheel:
            return False
        window = self.window
        if not getattr(window, "_curvemole_quick_fit_running", False):
            return False
        workspace = window.plot_workspace
        if getattr(workspace, "_view_locked", False):
            return False
        viewport = workspace.graphics.viewport()
        if watched is not viewport:
            return False
        delta = event.angleDelta().y()
        if delta == 0:
            return False

        scene_pos = workspace.graphics.mapToScene(event.position().toPoint())
        main_view = workspace.view_box
        if not main_view.sceneBoundingRect().contains(scene_pos):
            return False

        centre = main_view.mapSceneToView(scene_pos)
        # One ordinary wheel notch zooms by 15%; fractional/high-resolution wheel
        # deltas scale smoothly using the same exponential rule.
        factor = 0.85 ** (delta / 120.0)
        main_view.disableAutoRange()
        main_view.scaleBy((factor, factor), center=centre)
        event.accept()
        return True


def _capture_view_range(window: MainWindow) -> tuple[tuple[float, float], tuple[float, float]]:
    ranges = window.plot_workspace.view_box.viewRange()
    return (
        (float(ranges[0][0]), float(ranges[0][1])),
        (float(ranges[1][0]), float(ranges[1][1])),
    )


def _restore_view_range(
    window: MainWindow,
    ranges: tuple[tuple[float, float], tuple[float, float]],
) -> None:
    window.plot_workspace.view_box.setRange(
        xRange=ranges[0],
        yRange=ranges[1],
        padding=0,
        disableAutoRange=True,
    )


def _ensure_wheel_filter(window: MainWindow) -> None:
    if getattr(window, "_curvemole_quick_fit_wheel_filter", None) is not None:
        return
    event_filter = _QuickFitWheelZoomFilter(window)
    window.plot_workspace.graphics.viewport().installEventFilter(event_filter)
    window._curvemole_quick_fit_wheel_filter = event_filter


def _prepare_interactive_quick_fit_view(window: MainWindow) -> None:
    """Make Quick Fit redraws unable to suppress manual wheel navigation."""
    ranges = _capture_view_range(window)
    workspace = window.plot_workspace
    main_view = workspace.view_box
    residual_view = workspace.residual_plot.getViewBox()

    # Re-apply the normal interaction state in case a previous redraw left the
    # pyqtgraph ViewBox mouse flags stale, then freeze linked auto-ranging.
    workspace._update_interaction_state()
    main_view.disableAutoRange()
    residual_view.disableAutoRange()
    _restore_view_range(window, ranges)
    _ensure_wheel_filter(window)


def _quick_fit(window: MainWindow) -> None:
    previous_thread = window._thread
    _ORIGINAL_QUICK_FIT(window)
    # A new worker means Quick Fit really started. Do not mark early-return paths.
    if previous_thread is None and window._thread is not None:
        window._curvemole_quick_fit_running = True
        _prepare_interactive_quick_fit_view(window)


def _fit_finished(window: MainWindow, result: Any) -> None:
    preserve_view = bool(getattr(window, "_curvemole_quick_fit_running", False))
    ranges = _capture_view_range(window) if preserve_view else None
    try:
        _ORIGINAL_FIT_FINISHED(window, result)
    finally:
        if ranges is not None:
            # _fit_finished intentionally auto-ranges normal fits. Quick Fit instead
            # keeps the range the user reached with the mouse wheel while it ran.
            _restore_view_range(window, ranges)
        window._curvemole_quick_fit_running = False


def _task_done(window: MainWindow, *args: Any) -> None:
    try:
        _ORIGINAL_TASK_DONE(window, *args)
    finally:
        # Also clear the marker on cancellation/failure, where _fit_finished is not called.
        window._curvemole_quick_fit_running = False


def _install() -> None:
    if getattr(MainWindow, "_curvemole_quick_fit_zoom_fix", False):
        return
    MainWindow.quick_fit = _quick_fit
    MainWindow._fit_finished = _fit_finished
    MainWindow._task_done = _task_done
    MainWindow._curvemole_quick_fit_zoom_fix = True


_install()
