"""Refresh the live fit view at deterministic evaluation intervals."""

from __future__ import annotations

import re
from typing import Any

from curvemole.core.live_fit_progress import LIVE_REFRESH_EVERY
from curvemole.gui.main_window import MainWindow

_ORIGINAL_TASK_PROGRESS = MainWindow._task_progress
_EVALUATION_RE = re.compile(r"^Evaluation\s+(\d+)$")


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


def _evaluation_number(text: str) -> int | None:
    match = _EVALUATION_RE.fullmatch(text.strip())
    return int(match.group(1)) if match else None


def _task_progress(window: MainWindow, value: float | None, text: str) -> None:
    _ORIGINAL_TASK_PROGRESS(window, value, text)
    evaluation = _evaluation_number(text)
    if evaluation is None or evaluation % LIVE_REFRESH_EVERY != 0:
        return

    ranges = _capture_view_range(window)
    try:
        # The worker updates the shared fit parameters as the solver advances;
        # redrawing here lets the GUI display that current model state safely on
        # the main Qt thread.
        window.plot_workspace.refresh()
    finally:
        _restore_view_range(window, ranges)


def _install() -> None:
    if getattr(MainWindow, "_curvemole_live_fit_refresh", False):
        return
    MainWindow._task_progress = _task_progress
    MainWindow._curvemole_live_fit_refresh = True


_install()
