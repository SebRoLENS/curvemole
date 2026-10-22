"""Small shared viewport operations for interactive fits."""
from __future__ import annotations


def _capture_view_range(window) -> tuple[tuple[float, float], tuple[float, float]]:
    ranges = window.plot_workspace.view_box.viewRange()
    return (
        (float(ranges[0][0]), float(ranges[0][1])),
        (float(ranges[1][0]), float(ranges[1][1])),
    )


def _restore_view_range(
    window,
    ranges: tuple[tuple[float, float], tuple[float, float]],
) -> None:
    window.plot_workspace.view_box.setRange(
        xRange=ranges[0],
        yRange=ranges[1],
        padding=0,
        disableAutoRange=True,
    )
