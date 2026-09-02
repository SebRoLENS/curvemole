"""Desktop entry point."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QPen
from PySide6.QtWidgets import QApplication

from curvemole.core.fitting import FitMode, FitResult
from curvemole.gui.main_window import MainWindow
from curvemole.gui.plot import PlotWorkspace
from curvemole.gui.updates import UpdateController
from curvemole.version import __version__

PlotViewState = tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
]

_ADAPTIVE_RENDER_MIN_POINTS = 1500


def _normalise_fit_result_mode(result: FitResult) -> None:
    """Keep GUI-created fit results safe for enum-based snapshot serialisation."""
    result.mode = FitMode(result.mode)


def _capture_plot_view(workspace: PlotWorkspace) -> PlotViewState | None:
    """Capture the current main X/Y and residual Y ranges when a plot is visible."""
    if not workspace._data_items:
        return None
    main_range = workspace.view_box.viewRange()
    residual_range = workspace.residual_plot.getViewBox().viewRange()
    return (
        (float(main_range[0][0]), float(main_range[0][1])),
        (float(main_range[1][0]), float(main_range[1][1])),
        (float(residual_range[1][0]), float(residual_range[1][1])),
    )


def _restore_plot_view(workspace: PlotWorkspace, state: PlotViewState | None) -> None:
    """Restore a previously captured viewport without re-enabling auto range."""
    if state is None:
        return
    x_range, y_range, residual_y_range = state
    workspace.view_box.setRange(
        xRange=list(x_range),
        yRange=list(y_range),
        padding=0,
    )
    workspace.residual_plot.getViewBox().setRange(
        yRange=list(residual_y_range),
        padding=0,
    )


def _normalise_display_x(item: pg.PlotDataItem) -> bool:
    """Ensure monotonic display X data is ascending so clip-to-view is safe."""
    x_data, y_data = item.getOriginalDataset()
    if x_data is None or y_data is None or len(x_data) < 2:
        return False
    x = np.asarray(x_data)
    if not np.all(np.isfinite(x)):
        return False
    delta = np.diff(x)
    if np.all(delta >= 0) and np.any(delta > 0):
        return True
    if np.all(delta <= 0) and np.any(delta < 0):
        item.setData(x=x[::-1], y=np.asarray(y_data)[::-1])
        return True
    return False


def _optimise_plot_data_item(item: pg.PlotDataItem, *, adaptive: bool) -> None:
    """Configure one line item for pixel-aware rendering without changing source data."""
    if item.opts.get("pen") is None:
        return
    x_data, _ = item.getOriginalDataset()
    if x_data is None:
        return
    monotonic = _normalise_display_x(item)
    item.setClipToView(monotonic)
    use_downsampling = adaptive and monotonic and len(x_data) >= _ADAPTIVE_RENDER_MIN_POINTS
    item.setDownsampling(
        ds=None if use_downsampling else 1,
        auto=use_downsampling,
        method="peak",
    )
    if adaptive:
        pen = item.opts.get("pen")
        if isinstance(pen, QPen) and not np.isclose(pen.widthF(), 1.0):
            fast_pen = QPen(pen)
            fast_pen.setWidthF(1.0)
            item.setPen(fast_pen)


def _optimise_plot_rendering(workspace: PlotWorkspace) -> None:
    """Apply adaptive rendering to dense Overlay/Waterfall views after each refresh."""
    adaptive = workspace.display_mode.currentIndex() != 0
    for plot in (workspace.plot, workspace.residual_plot):
        for item in plot.listDataItems():
            _optimise_plot_data_item(item, adaptive=adaptive)


def _install_view_preserving_refresh() -> None:
    """Make redraws preserve navigation while retaining explicit View all behaviour."""
    if getattr(PlotWorkspace, "_curvemole_preserves_view", False):
        return

    original_refresh = PlotWorkspace.refresh
    original_set_context = PlotWorkspace.set_context
    original_auto_range = PlotWorkspace.auto_range

    def refresh(workspace: PlotWorkspace, *args: Any) -> None:
        preserve = bool(getattr(workspace, "_preserve_view_on_refresh", True))
        if hasattr(workspace, "_preserve_view_on_refresh"):
            delattr(workspace, "_preserve_view_on_refresh")
        state = _capture_plot_view(workspace) if preserve else None
        original_refresh(workspace, *args)
        _optimise_plot_rendering(workspace)
        _restore_plot_view(workspace, state)

    def set_context(
        workspace: PlotWorkspace,
        project: Any,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        # A different Project means opening/creating a new document: allow the
        # normal initial fit-to-data. Updates inside the same project preserve
        # the user's current zoom and pan position.
        workspace._preserve_view_on_refresh = project is workspace._project
        original_set_context(workspace, project, *args, **kwargs)

    def auto_range(workspace: PlotWorkspace) -> None:
        # Fit finalisation historically called auto_range unconditionally. The
        # GUI boundary can suppress that one automatic call while the explicit
        # View all command continues to work normally.
        if bool(getattr(workspace, "_suppress_automatic_auto_range", False)):
            return
        original_auto_range(workspace)

    PlotWorkspace.refresh = refresh
    PlotWorkspace.set_context = set_context
    PlotWorkspace.auto_range = auto_range
    PlotWorkspace._curvemole_preserves_view = True


_install_view_preserving_refresh()


class CurveMoleMainWindow(MainWindow):
    """Main window with defensive fit normalisation and stable plot navigation."""

    def _fit_finished(self, result: FitResult) -> None:
        view_state = _capture_plot_view(self.plot_workspace)
        _normalise_fit_result_mode(result)
        self.plot_workspace._suppress_automatic_auto_range = True
        try:
            super()._fit_finished(result)
        finally:
            self.plot_workspace._suppress_automatic_auto_range = False
            _restore_plot_view(self.plot_workspace, view_state)


def _missing_toolbar_icons(window: MainWindow) -> list[str]:
    """Return bundled toolbar resources that failed to load."""
    actions = {
        "open-project.svg": window.open_action,
        "save-project.svg": window.save_action,
        "calculator.png": window.calculator_action,
        "subtract-background.png": window.subtract_background_action,
        "add-peak.png": window.add_component_action,
        "quick-add-peak.png": window.quick_peak_action,
        "fit.png": window.fit_action,
        "quick-fit.png": window.quick_fit_action,
    }
    return [name for name, action in actions.items() if action.icon().isNull()]


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(arguments)
    QCoreApplication.setOrganizationName("CurveMole")
    QCoreApplication.setApplicationName("CurveMole")
    QCoreApplication.setApplicationVersion(__version__)
    window = CurveMoleMainWindow()
    window._release_update_controller = UpdateController(window)
    window.show()
    if os.environ.get("CURVEMOLE_SMOKE_TEST") == "1":
        from PySide6.QtCore import QTimer

        missing_icons = _missing_toolbar_icons(window)
        if missing_icons:
            raise RuntimeError(f"Missing bundled toolbar icons: {', '.join(missing_icons)}")
        QTimer.singleShot(0, app.quit)
    if len(arguments) > 1:
        path = Path(arguments[1])
        if path.suffix.lower() == ".fitproj" and path.exists():
            window.open_project(path)
        elif path.exists():
            window.import_data([str(path)])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
