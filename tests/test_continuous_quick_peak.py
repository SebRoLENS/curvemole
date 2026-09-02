from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from curvemole.core.registry import default_registry
from curvemole.gui import app as gui_app  # noqa: F401 - installs GUI compatibility patches
from curvemole.gui.plot import PlotWorkspace


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_continuous_peak_placement_stays_active_until_finish() -> None:
    _app()
    workspace = PlotWorkspace(default_registry())
    placed: list[tuple[float, float, float]] = []
    finished: list[bool] = []
    workspace.peakPlacementFinished.connect(
        lambda x, y, width: placed.append((float(x), float(y), float(width)))
    )
    workspace.placementCancelled.connect(lambda: finished.append(True))

    workspace.begin_continuous_peak_placement("Gaussian")
    assert workspace._continuous_peak_placement is True
    assert workspace.finish_placement_button.isVisible() is True

    workspace._finish_peak_placement(2.0, 3.0, 0.8)
    assert len(placed) == 1
    assert workspace._continuous_peak_placement is True
    assert finished == []

    workspace._finish_peak_placement(4.0, 5.0, 1.2)
    assert len(placed) == 2
    assert workspace._continuous_peak_placement is True

    workspace.finish_placement()
    assert workspace._continuous_peak_placement is False
    assert workspace._continuous_peak_done is True
    assert finished == [True]


def test_escape_semantics_finish_continuous_peak_mode() -> None:
    _app()
    workspace = PlotWorkspace(default_registry())
    finished: list[bool] = []
    workspace.placementCancelled.connect(lambda: finished.append(True))

    workspace.begin_continuous_peak_placement("Lorentzian")
    workspace.cancel_placement()

    assert workspace._continuous_peak_placement is False
    assert workspace._continuous_peak_done is True
    assert finished == [True]
