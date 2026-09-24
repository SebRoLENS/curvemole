"""Desktop entry point."""

from __future__ import annotations

import math
import os
import platform
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QCoreApplication, QEvent, QLocale, QObject, Qt, QTimer
from PySide6.QtGui import QAction, QFileOpenEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMessageBox

from curvemole.core.fitting import FitMode, FitResult
from curvemole.core.models import Component
from curvemole.gui.main_window import MainWindow, _resource_path
from curvemole.gui.manual_points import install_manual_point_support
from curvemole.gui.plot import PlotWorkspace
from curvemole.gui.rendering import _optimise_plot_data_item
from curvemole.gui.updates import UpdateController
from curvemole.version import __version__

PlotViewState = tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
]

_MASK_REGION_Z = -20.0
_MASK_BOUNDARY_Z = -10.0


def _configure_gui_defaults() -> None:
    """Use scientific numeric formatting and single-button plot navigation by default."""
    # CurveMole's numerical parameters are scientific data, not localized prose.
    # Keep decimal input/output stable and portable regardless of the OS locale.
    QLocale.setDefault(QLocale.c())
    # pyqtgraph's RectMode is the context-menu "Mouse Mode -> 1 button" mode.
    pg.setConfigOption("leftButtonPan", False)


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


def _optimise_plot_rendering(workspace: PlotWorkspace) -> None:
    """Apply adaptive rendering to dense Overlay/Waterfall views after each refresh."""
    adaptive = workspace.display_mode.currentIndex() != 0
    for plot in (workspace.plot, workspace.residual_plot):
        for item in plot.listDataItems():
            _optimise_plot_data_item(item, adaptive=adaptive)


def _is_dense_mask_marker(kwargs: dict[str, Any]) -> bool:
    """Identify the legacy per-point mask marker render call."""
    return (
        kwargs.get("pen") is None
        and kwargs.get("symbol") == "o"
        and kwargs.get("symbolSize") == 5
        and kwargs.get("symbolPen") is None
    )


def _render_lightweight_mask_boundaries(workspace: PlotWorkspace) -> None:
    """Replace filled mask overlays with cheap, non-ranging dashed boundary lines."""
    for item in tuple(workspace.plot.items):
        if isinstance(item, pg.LinearRegionItem) and np.isclose(item.zValue(), _MASK_REGION_Z):
            workspace.plot.removeItem(item)

    project = workspace._project
    if project is None or not project.curves:
        return

    mode = workspace.display_mode.currentText()
    curves = workspace.displayed_curves()
    x_step = workspace.x_offset.value() if mode == workspace.tr("Waterfall") else 0.0
    pen = pg.mkPen(105, 105, 105, 155, width=1.0, style=Qt.PenStyle.DashLine)
    positions_seen: set[float] = set()

    for index, curve in enumerate(curves):
        x_offset = index * x_step
        for mask in curve.masks.values():
            for lower, upper in mask.ranges:
                lo, hi = sorted((float(lower), float(upper)))
                positions = (lo + x_offset,) if math.isclose(lo, hi) else (lo + x_offset, hi + x_offset)
                for position in positions:
                    if not np.isfinite(position):
                        continue
                    key = round(position, 12)
                    if key in positions_seen:
                        continue
                    positions_seen.add(key)
                    line = pg.InfiniteLine(
                        pos=position,
                        angle=90,
                        movable=False,
                        pen=pen,
                    )
                    line.setZValue(_MASK_BOUNDARY_Z)
                    line.setToolTip(workspace.tr("Masked / excluded region boundary"))
                    line._curvemole_mask_boundary = True
                    workspace.plot.addItem(line, ignoreBounds=True)


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

        original_plot = workspace.plot.plot

        def lightweight_plot(*plot_args: Any, **plot_kwargs: Any) -> pg.PlotDataItem:
            if _is_dense_mask_marker(plot_kwargs):
                return pg.PlotDataItem()
            return original_plot(*plot_args, **plot_kwargs)

        workspace.plot.plot = lightweight_plot
        try:
            original_refresh(workspace, *args)
        finally:
            workspace.plot.plot = original_plot

        _render_lightweight_mask_boundaries(workspace)
        _optimise_plot_rendering(workspace)
        _restore_plot_view(workspace, state)
        if state is None:
            workspace.auto_range()

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


def _install_continuous_peak_placement() -> None:
    """Keep Quick Peak placement active until the user explicitly finishes it."""
    if getattr(PlotWorkspace, "_curvemole_continuous_peaks", False):
        return

    original_init = PlotWorkspace.__init__
    original_begin_peak = PlotWorkspace.begin_peak_placement
    original_finish_peak = PlotWorkspace._finish_peak_placement
    original_finish_placement = PlotWorkspace.finish_placement
    original_cancel_placement = PlotWorkspace.cancel_placement

    def init(workspace: PlotWorkspace, *args: Any, **kwargs: Any) -> None:
        original_init(workspace, *args, **kwargs)
        workspace._continuous_peak_placement = False
        workspace._continuous_peak_done = False
        workspace._continuous_peak_return = QShortcut(QKeySequence("Return"), workspace)
        workspace._continuous_peak_enter = QShortcut(QKeySequence("Enter"), workspace)
        workspace._continuous_peak_return.activated.connect(
            lambda: workspace.finish_placement()
            if getattr(workspace, "_continuous_peak_placement", False)
            else None
        )
        workspace._continuous_peak_enter.activated.connect(
            lambda: workspace.finish_placement()
            if getattr(workspace, "_continuous_peak_placement", False)
            else None
        )

    def begin_continuous_peak_placement(workspace: PlotWorkspace, name: str) -> None:
        original_begin_peak(workspace, name)
        workspace._continuous_peak_placement = True
        workspace._continuous_peak_done = False
        workspace.finish_placement_button.show()
        workspace.finish_placement_button.setEnabled(True)
        workspace.placement_label.setText(
            workspace.tr("Quick Peak — ")
            + name
            + workspace.tr(
                ": click/drag to add peaks repeatedly. Press Enter, Esc, or Finish when done."
            )
        )

    def finish_peak(workspace: PlotWorkspace, x: float, y: float, fwhm: float) -> None:
        if not getattr(workspace, "_continuous_peak_placement", False):
            original_finish_peak(workspace, x, y, fwhm)
            return
        x, y = workspace._from_display_coordinates(x, y)
        selected_width = fwhm if fwhm > 0 else workspace._default_peak_width()
        workspace._peak_preview = None
        workspace.peakPlacementFinished.emit(x, y, selected_width)
        workspace._render_placement_preview()

    def finish_placement(workspace: PlotWorkspace) -> None:
        if not getattr(workspace, "_continuous_peak_placement", False):
            original_finish_placement(workspace)
            return
        workspace._continuous_peak_placement = False
        workspace._continuous_peak_done = True
        workspace._end_placement()
        workspace.placementCancelled.emit()

    def cancel_placement(workspace: PlotWorkspace) -> None:
        if getattr(workspace, "_continuous_peak_placement", False):
            # In continuous Quick Peak mode Esc means "done", not "discard".
            finish_placement(workspace)
            return
        original_cancel_placement(workspace)

    PlotWorkspace.__init__ = init
    PlotWorkspace.begin_continuous_peak_placement = begin_continuous_peak_placement
    PlotWorkspace._finish_peak_placement = finish_peak
    PlotWorkspace.finish_placement = finish_placement
    PlotWorkspace.cancel_placement = cancel_placement
    PlotWorkspace._curvemole_continuous_peaks = True


_install_view_preserving_refresh()
_install_continuous_peak_placement()
install_manual_point_support()


class NativeFileOpenFilter(QObject):
    """Accept native Finder file-open events without overriding QApplication."""

    def __init__(self) -> None:
        super().__init__()
        self._file_open_handler: Any | None = None
        self._pending_file_opens: list[str] = []

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.FileOpen and isinstance(event, QFileOpenEvent):
            path = event.file()
            if path:
                if self._file_open_handler is None:
                    self._pending_file_opens.append(path)
                else:
                    self._file_open_handler(path)
                return True
        return super().eventFilter(watched, event)

    def set_file_open_handler(self, handler: Any) -> None:
        self._file_open_handler = handler
        pending, self._pending_file_opens = self._pending_file_opens, []
        for path in pending:
            handler(path)


def _open_paths(window: MainWindow, values: Sequence[str]) -> None:
    """Open one project or import file paths supplied by the operating system."""
    paths = [Path(value) for value in values if value and Path(value).exists()]
    projects = [path for path in paths if path.suffix.lower() == ".fitproj"]
    if projects:
        window.open_project(projects[0])
    data = [str(path) for path in paths if path.suffix.lower() != ".fitproj"]
    if data:
        window.import_data(data)


class CurveMoleMainWindow(MainWindow):
    """Main window with stable navigation and continuous quick peak placement."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._continuous_quick_peak_function_id: str | None = None
        super().__init__(*args, **kwargs)
        self.desktop_integration_action: QAction | None = None
        if platform.system() == "Linux":
            from curvemole.gui.desktop_integration import (
                current_appimage,
                linux_integration_is_current,
            )

            if current_appimage() is not None:
                self.desktop_integration_action = QAction(
                    self.tr("Integrate CurveMole with the desktop…"), self
                )
                self.desktop_integration_action.triggered.connect(
                    lambda checked=False: self.integrate_linux_desktop()
                )
                self.tools_menu.addSeparator()
                self.tools_menu.addAction(self.desktop_integration_action)
                already_prompted = self.settings.value(
                    "desktop/linux_integration_prompted_v2", False, type=bool
                )
                if (
                    not linux_integration_is_current()
                    and not already_prompted
                    and os.environ.get("CURVEMOLE_SMOKE_TEST") != "1"
                ):
                    QTimer.singleShot(750, self._offer_linux_desktop_integration)
        self.quick_peak_action.setToolTip(
            self.tr(
                "Quick Add Function\nUse the function selected in the adjacent list. "
                "Press Enter, Esc, or Finish to stop."
            )
        )

    def _offer_linux_desktop_integration(self) -> None:
        """Offer AppImage integration once, while keeping the menu action available."""
        box = QMessageBox(self)
        box.setWindowTitle(self.tr("Desktop integration"))
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(
            self.tr(
                "Would you like to add CurveMole to the application menu and register it for .fitproj files?"
            )
        )
        integrate_button = box.addButton(
            self.tr("Integrate CurveMole"), QMessageBox.ButtonRole.AcceptRole
        )
        box.addButton(self.tr("Not now"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        self.settings.setValue("desktop/linux_integration_prompted_v2", True)
        if box.clickedButton() is integrate_button:
            self.integrate_linux_desktop()

    def integrate_linux_desktop(self) -> None:
        """Install or update the per-user AppImage launcher and file association."""
        from curvemole.gui.desktop_integration import integrate_linux_desktop

        icon = _resource_path("curvemole.png")
        try:
            if icon is None:
                raise RuntimeError(self.tr("The bundled CurveMole icon could not be found."))
            result = integrate_linux_desktop(icon_source=icon)
        except Exception as exc:
            self._log(f"Desktop integration failed: {exc}")
            QMessageBox.warning(
                self,
                self.tr("Desktop integration"),
                self.tr("CurveMole could not update the desktop integration:\n") + str(exc),
            )
            return
        detail = (
            self.tr("The existing launcher was adopted and updated.")
            if result.adopted_existing_launcher
            else self.tr("The AppImage was copied to a stable per-user application folder.")
        )
        QMessageBox.information(
            self,
            self.tr("Desktop integration"),
            self.tr(
                "CurveMole is now available from the application menu and registered for .fitproj files.\n\n"
            )
            + detail,
        )

    def _fit_finished(self, result: FitResult) -> None:
        view_state = _capture_plot_view(self.plot_workspace)
        _normalise_fit_result_mode(result)
        self.plot_workspace._suppress_automatic_auto_range = True
        try:
            super()._fit_finished(result)
        finally:
            self.plot_workspace._suppress_automatic_auto_range = False
            _restore_plot_view(self.plot_workspace, view_state)

    def quick_peak(self) -> None:
        if not self._ensure_editable():
            return
        if not self.active_curve_id:
            self._notify(self.tr("Activate a curve first."), warning=True)
            return

        self.plot_workspace.cancel_placement()
        from curvemole.gui.quick_function_library import _selected_quick_function

        definition = self.registry.get(_selected_quick_function(self))
        if definition.kind != "peak":
            self._continuous_quick_peak_function_id = None
            super().quick_peak()
            return
        self._remember_quick_function(definition.identifier)
        self._continuous_quick_peak_function_id = definition.identifier
        self._prepare_next_quick_peak()
        self.plot_workspace.begin_continuous_peak_placement(definition.display_name)
        self._notify(
            self.tr(
                "Quick Peak is active: add peaks repeatedly, then press Enter, Esc, or Finish."
            )
        )

    def _prepare_next_quick_peak(self) -> None:
        function_id = self._continuous_quick_peak_function_id
        if not function_id or not self.active_curve_id:
            return
        self._pending_component = Component.create(function_id, registry=self.registry)
        self._pending_component_curve_id = self.active_curve_id

    def _graphical_peak_placed(self, centre: float, height: float, fwhm: float) -> None:
        continuous = bool(
            self._continuous_quick_peak_function_id
            and getattr(self.plot_workspace, "_continuous_peak_placement", False)
        )
        super()._graphical_peak_placed(centre, height, fwhm)
        if continuous and getattr(self.plot_workspace, "_continuous_peak_placement", False):
            self._prepare_next_quick_peak()

    def _graphical_placement_cancelled(self) -> None:
        if getattr(self.plot_workspace, "_continuous_peak_done", False):
            self.plot_workspace._continuous_peak_done = False
            self._pending_component = None
            self._pending_component_curve_id = None
            self._continuous_quick_peak_function_id = None
            self._notify(self.tr("Quick Peak finished."))
            return
        self._continuous_quick_peak_function_id = None
        super()._graphical_placement_cancelled()


def _missing_toolbar_icons(window: MainWindow) -> list[str]:
    """Return bundled toolbar resources that failed to load."""
    actions = {
        "open-project.svg": window.open_action,
        "save-project.svg": window.save_action,
        "calculator.png": window.calculator_action,
        "subtract-background.png": window.subtract_background_action,
        "add-peak.svg": window.add_component_action,
        "quick-add-peak.svg": window.quick_peak_action,
        "fit.svg": window.fit_action,
        "quick-fit.svg": window.quick_fit_action,
    }
    return [name for name, action in actions.items() if action.icon().isNull()]


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv
    if len(arguments) == 3 and arguments[1] == "--run-automation-job":
        from curvemole.core.automation_job import run_job
        return run_job(arguments[2])
    _configure_gui_defaults()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(arguments)
    file_open_filter: NativeFileOpenFilter | None = None
    if platform.system() == "Darwin":
        file_open_filter = NativeFileOpenFilter()
        app.installEventFilter(file_open_filter)
    QCoreApplication.setOrganizationName("CurveMole")
    QCoreApplication.setApplicationName("CurveMole")
    QCoreApplication.setApplicationVersion(__version__)
    window = CurveMoleMainWindow()
    window._release_update_controller = UpdateController(window)
    from curvemole.gui.plugin_updates import PluginUpdateController
    window.plugin_update_controller = PluginUpdateController(window)
    window.show()
    if file_open_filter is not None:
        file_open_filter.set_file_open_handler(lambda path: _open_paths(window, [path]))
    if os.environ.get("CURVEMOLE_SMOKE_TEST") == "1":
        missing_icons = _missing_toolbar_icons(window)
        if missing_icons:
            raise RuntimeError(f"Missing bundled toolbar icons: {', '.join(missing_icons)}")
        QTimer.singleShot(0, app.quit)
    if len(arguments) > 1:
        _open_paths(window, arguments[1:])
    if os.environ.get("CURVEMOLE_SMOKE_TEST") != "1":
        from curvemole.gui.recovery_session import RecoverySession

        try:
            window._recovery_session = RecoverySession(window.recovery.directory)
            window._crashed_recovery_projects = window._recovery_session.crashed_projects
        except OSError as exc:
            window._log(f"Recovery session tracking failed: {exc}")
        QTimer.singleShot(0, lambda: window.show_recovery_sessions(startup=True))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
