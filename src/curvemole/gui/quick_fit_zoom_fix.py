"""Preserve interactive plot zoom while Quick Fit is running and completes."""

from __future__ import annotations

from typing import Any

from curvemole.gui.main_window import MainWindow

_ORIGINAL_QUICK_FIT = MainWindow.quick_fit
_ORIGINAL_FIT_FINISHED = MainWindow._fit_finished
_ORIGINAL_TASK_DONE = MainWindow._task_done


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


def _prepare_interactive_quick_fit_view(window: MainWindow) -> None:
    """Stop linked auto-ranging from overriding mouse-wheel zoom during Quick Fit."""
    ranges = _capture_view_range(window)
    main_view = window.plot_workspace.view_box
    residual_view = window.plot_workspace.residual_plot.getViewBox()

    # The residual panel is X-linked to the main spectrum panel. If either view
    # keeps auto-ranging while live fit redraws replace their plotted data, that
    # auto-range can immediately override a manual wheel zoom on the other view.
    # Freeze both ranges before the worker starts producing live redraws.
    main_view.disableAutoRange()
    residual_view.disableAutoRange()
    _restore_view_range(window, ranges)


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
