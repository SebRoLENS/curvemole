from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from curvemole.core.registry import default_registry
from curvemole.gui import app as gui_app  # noqa: F401 - installs GUI compatibility patches
from curvemole.gui.plot import PlotWorkspace


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_mouse_wheel_zooms_during_continuous_quick_peak_placement() -> None:
    app = _app()
    workspace = PlotWorkspace(default_registry())
    workspace.resize(900, 600)
    workspace.show()
    app.processEvents()

    x = np.linspace(-5.0, 5.0, 101)
    workspace.plot.plot(x, np.exp(-x**2))
    workspace.view_box.setRange(xRange=(-4.0, 4.0), yRange=(-0.5, 1.5), padding=0)
    workspace.begin_continuous_peak_placement("Gaussian")
    app.processEvents()

    # Peak placement must keep the ViewBox mouse engine enabled. Left-click and
    # left-drag are still intercepted by MaskViewBox for peak creation, while the
    # inherited pyqtgraph wheel handler remains available for navigation.
    assert all(workspace.view_box.state["mouseEnabled"])
    assert workspace._continuous_peak_placement is True

    before = workspace.view_box.viewRange()
    viewport = workspace.graphics.viewport()
    scene_center = workspace.view_box.sceneBoundingRect().center()
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

    after = workspace.view_box.viewRange()
    assert event.isAccepted()
    assert after[0][1] - after[0][0] < before[0][1] - before[0][0]
    assert after[1][1] - after[1][0] < before[1][1] - before[1][0]
    assert workspace._continuous_peak_placement is True

    workspace.finish_placement()
    workspace.close()
    app.processEvents()
