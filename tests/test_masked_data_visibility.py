from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

import pyqtgraph as pg
from PySide6.QtGui import QPen
from PySide6.QtWidgets import QApplication

from curvemole import Curve, Project
from curvemole.core.registry import default_registry
from curvemole.gui.app import _optimise_plot_rendering
from curvemole.gui.plot import PlotWorkspace


def _dense_workspace() -> tuple[QApplication, PlotWorkspace, Curve]:
    app = QApplication.instance() or QApplication([])
    x = np.linspace(0.0, 100.0, 12000)
    curve = Curve("dense", x, np.sin(x / 3.0))
    project = Project("Masked visibility")
    project.add_curve(curve)
    project.dirty = False
    workspace = PlotWorkspace(default_registry())
    workspace.display_mode.setCurrentIndex(1)  # Overlay: adaptive rendering enabled.
    workspace.set_context(project, curve.id)
    return app, workspace, curve


def test_masked_interval_stays_visible_as_adaptive_grey_trace() -> None:
    app, workspace, curve = _dense_workspace()
    curve.mask_interval(25.0, 50.0)

    workspace.refresh()
    _optimise_plot_rendering(workspace)

    masked_lines = [
        item
        for item in workspace.plot.listDataItems()
        if getattr(item, "_curvemole_masked_data", False) and item.opts.get("pen") is not None
    ]
    assert masked_lines
    item = max(masked_lines, key=lambda candidate: len(candidate.getOriginalDataset()[0]))
    x_data, y_data = item.getOriginalDataset()
    assert x_data is not None and y_data is not None
    assert len(x_data) > 2500
    assert np.all(np.isfinite(y_data))
    assert item.opts["clipToView"] is True
    assert item.opts["autoDownsample"] is True
    assert item.opts["downsampleMethod"] == "peak"

    pen = item.opts["pen"]
    assert isinstance(pen, QPen)
    colour = pen.color()
    assert colour.red() == colour.green() == colour.blue()
    assert colour.alpha() < 255

    # The legacy expensive five-pixel point cloud must stay suppressed.
    assert not any(
        data_item.opts.get("pen") is None
        and data_item.opts.get("symbol") == "o"
        and data_item.opts.get("symbolSize") == 5
        for data_item in workspace.plot.listDataItems()
    )

    workspace.close()
    app.processEvents()


def test_isolated_masked_point_remains_visible_as_small_grey_marker() -> None:
    app, workspace, curve = _dense_workspace()
    masked_index = curve.mask_point(42.0)

    workspace.refresh()

    masked_markers = [
        item
        for item in workspace.plot.listDataItems()
        if getattr(item, "_curvemole_masked_data", False) and item.opts.get("pen") is None
    ]
    assert len(masked_markers) == 1
    marker = masked_markers[0]
    x_data, y_data = marker.getOriginalDataset()
    assert x_data is not None and y_data is not None
    assert len(x_data) == 1
    assert float(x_data[0]) == pytest.approx(float(curve.x[masked_index]))
    assert float(y_data[0]) == pytest.approx(float(curve.y[masked_index]))
    assert marker.opts["symbol"] == "o"
    assert marker.opts["symbolSize"] == pytest.approx(3.5)

    workspace.close()
    app.processEvents()
