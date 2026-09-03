from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

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
    window._fit_finished(object())

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
