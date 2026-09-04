"""Keep plot wheel zoom available while a peak is being placed."""

from __future__ import annotations

from curvemole.gui.plot import PlotWorkspace

_ORIGINAL_UPDATE_INTERACTION_STATE = PlotWorkspace._update_interaction_state


def _update_interaction_state(workspace: PlotWorkspace) -> None:
    """Preserve wheel navigation during peak placement.

    Peak placement already consumes left-click and left-drag events inside
    ``MaskViewBox``. Disabling the whole ViewBox therefore blocks more than is
    necessary: pyqtgraph also disables its wheel handler. Keep the ViewBox mouse
    interaction enabled for peak placement so the wheel can zoom normally while
    clicks/drags still create the peak instead of panning the plot.
    """
    if workspace._placement_mode == "peak":
        enabled = not workspace._view_locked and not workspace.view_box.mask_mode
        workspace.plot.setMouseEnabled(x=enabled, y=enabled)
        return
    _ORIGINAL_UPDATE_INTERACTION_STATE(workspace)


def _install() -> None:
    if getattr(PlotWorkspace, "_curvemole_peak_placement_zoom_fix", False):
        return
    PlotWorkspace._update_interaction_state = _update_interaction_state
    PlotWorkspace._curvemole_peak_placement_zoom_fix = True


_install()
