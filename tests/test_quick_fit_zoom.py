from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.gui import quick_fit_zoom_fix
from curvemole.gui.main_window import MainWindow


def _window() -> tuple[QApplication, MainWindow]:
    app = QApplication.instance() or QApplication([])
    project = Project("quick-fit-zoom")
    x = np.linspace(-5.0, 5.0, 101)
    curve = Curve("spectrum", x, np.exp(-x**2))
    project.add_curve(curve)
    project.model_for(curve.id).add(Component.create("gaussian"))
    project.dirty = False
    return app, MainWindow(project)


def test_quick_fit_completion_preserves_current_plot_range(monkeypatch: pytest.MonkeyPatch) -> None:
    app, window = _window()
    view_box = window.plot_workspace.view_box
    view_box.setRange(xRange=(-1.5, 2.5), yRange=(-0.2, 1.2), padding=0)
    expected = quick_fit_zoom_fix._capture_view_range(window)

    def fake_finished(instance: MainWindow, _result: object) -> None:
        # Reproduce the range-changing redraw/auto-range done by normal fit completion.
        instance.plot_workspace.view_box.setRange(
            xRange=(-10.0, 10.0), yRange=(-5.0, 5.0), padding=0
        )

    monkeypatch.setattr(quick_fit_zoom_fix, "_ORIGINAL_FIT_FINISHED", fake_finished)
    window._curvemole_quick_fit_running = True

    # Exercise the Quick Fit wrapper directly. MainWindow._fit_finished is wrapped
    # again by the sequential-fit UI after this module is installed, and those
    # wrappers correctly require a real FitResult (with mode/success fields).
    # This unit test is specifically for the zoom-preservation wrapper itself.
    quick_fit_zoom_fix._fit_finished(window, object())

    actual = quick_fit_zoom_fix._capture_view_range(window)
    assert actual[0] == pytest.approx(expected[0])
    assert actual[1] == pytest.approx(expected[1])
    assert not window._curvemole_quick_fit_running

    window.project.dirty = False
    window.close()
    app.processEvents()


def test_quick_fit_marks_only_a_started_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    app, window = _window()
    worker_marker = object()

    def fake_quick_fit(instance: MainWindow) -> None:
        instance._thread = worker_marker  # type: ignore[assignment]

    monkeypatch.setattr(quick_fit_zoom_fix, "_ORIGINAL_QUICK_FIT", fake_quick_fit)
    window._thread = None
    window.quick_fit()
    assert window._curvemole_quick_fit_running is True

    window._thread = None
    window._curvemole_quick_fit_running = False
    window.project.dirty = False
    window.close()
    app.processEvents()


def test_quick_fit_disables_linked_autorange_so_wheel_zoom_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, window = _window()
    worker_marker = object()
    main_view = window.plot_workspace.view_box
    residual_view = window.plot_workspace.residual_plot.getViewBox()

    main_view.enableAutoRange()
    residual_view.enableAutoRange()
    main_view.setRange(xRange=(-4.0, 4.0), yRange=(-0.5, 1.5), padding=0)

    def fake_quick_fit(instance: MainWindow) -> None:
        instance._thread = worker_marker  # type: ignore[assignment]

    monkeypatch.setattr(quick_fit_zoom_fix, "_ORIGINAL_QUICK_FIT", fake_quick_fit)
    window._thread = None
    window.quick_fit()

    assert not any(main_view.autoRangeEnabled())
    assert not any(residual_view.autoRangeEnabled())

    before = quick_fit_zoom_fix._capture_view_range(window)
    main_view.scaleBy((0.5, 0.5))
    app.processEvents()
    zoomed = quick_fit_zoom_fix._capture_view_range(window)

    assert zoomed[0][1] - zoomed[0][0] < before[0][1] - before[0][0]
    assert zoomed[1][1] - zoomed[1][0] < before[1][1] - before[1][0]

    # Replacing residual data must not re-enable linked auto-ranging and undo the
    # user's manual zoom while the Quick Fit worker is still active.
    window.plot_workspace.residual_plot.clear()
    window.plot_workspace.residual_plot.plot(
        np.linspace(-50.0, 50.0, 101), np.linspace(-1.0, 1.0, 101)
    )
    app.processEvents()
    after_redraw = quick_fit_zoom_fix._capture_view_range(window)
    assert after_redraw[0] == pytest.approx(zoomed[0])
    assert after_redraw[1] == pytest.approx(zoomed[1])

    window._thread = None
    window._curvemole_quick_fit_running = False
    window.project.dirty = False
    window.close()
    app.processEvents()


def test_real_wheel_event_zooms_main_canvas_while_quick_fit_is_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, window = _window()
    worker_marker = object()
    workspace = window.plot_workspace
    main_view = workspace.view_box

    def fake_quick_fit(instance: MainWindow) -> None:
        instance._thread = worker_marker  # type: ignore[assignment]

    monkeypatch.setattr(quick_fit_zoom_fix, "_ORIGINAL_QUICK_FIT", fake_quick_fit)
    window.show()
    app.processEvents()
    main_view.setRange(xRange=(-4.0, 4.0), yRange=(-0.5, 1.5), padding=0)
    window._thread = None
    window.quick_fit()

    before = quick_fit_zoom_fix._capture_view_range(window)
    # Simulate the stale pyqtgraph mouse-disable state that used to make the wheel
    # appear to affect only axes/scales. The Quick Fit viewport filter must still
    # consume the physical wheel event and zoom the plot canvas itself.
    main_view.setMouseEnabled(x=False, y=False)
    viewport = workspace.graphics.viewport()
    scene_center = main_view.sceneBoundingRect().center()
    viewport_pos = workspace.graphics.mapFromScene(scene_center)
    global_pos = viewport.mapToGlobal(viewport_pos)
    event = QWheelEvent(
        QPointF(viewport_pos),
        QPointF(global_pos),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(viewport, event)
    app.processEvents()

    after = quick_fit_zoom_fix._capture_view_range(window)
    assert event.isAccepted()
    assert after[0][1] - after[0][0] < before[0][1] - before[0][0]
    assert after[1][1] - after[1][0] < before[1][1] - before[1][0]

    window._thread = None
    window._curvemole_quick_fit_running = False
    window.project.dirty = False
    window.close()
    app.processEvents()
