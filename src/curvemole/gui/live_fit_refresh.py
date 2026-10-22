"""Apply worker snapshots to a transient GUI display, preserving saved project state."""
from __future__ import annotations

from curvemole.gui.plot_view import _capture_view_range, _restore_view_range


def refresh_snapshot(window, values):
    ranges = _capture_view_range(window)
    window.plot_workspace._live_parameter_values = dict(values)
    try:
        window.plot_workspace.refresh()
    finally:
        _restore_view_range(window, ranges)
