from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

from curvemole import Curve, Project
from curvemole.core.registry import default_registry
from curvemole.gui.app import _MASK_BOUNDARY_Z
from curvemole.gui.plot import PlotWorkspace


def _workspace_with_dense_curve() -> tuple[QApplication, PlotWorkspace, Curve]:
    app = QApplication.instance() or QApplication([])
    x = np.linspace(0.0, 100.0, 12000)
    curve = Curve("dense", x, np.sin(x))
    project = Project("Mask rendering")
    project.add_curve(curve)
    project.dirty = False
    workspace = PlotWorkspace(default_registry())
    workspace.set_context(project, curve.id)
    return app, workspace, curve


def test_interval_mask_uses_only_lightweight_boundary_lines() -> None:
    app, workspace, curve = _workspace_with_dense_curve()
    curve.mask_interval(25.0, 50.0)

    workspace.refresh()

    assert not any(
        isinstance(item, pg.LinearRegionItem) and item.zValue() == pytest.approx(-20.0)
        for item in workspace.plot.items
    )
    assert not any(
        item.opts.get("pen") is None
        and item.opts.get("symbol") == "o"
        and item.opts.get("symbolSize") == 5
        for item in workspace.plot.listDataItems()
    )
    boundaries = [
        item
        for item in workspace.plot.items
        if isinstance(item, pg.InfiniteLine)
        and getattr(item, "_curvemole_mask_boundary", False)
        and item.zValue() == pytest.approx(_MASK_BOUNDARY_Z)
    ]
    assert sorted(float(line.value()) for line in boundaries) == pytest.approx([25.0, 50.0])

    workspace.close()
    app.processEvents()


def test_point_mask_gets_one_boundary_without_point_cloud() -> None:
    app, workspace, curve = _workspace_with_dense_curve()
    index = curve.mask_point(42.0)

    workspace.refresh()

    boundaries = [
        item
        for item in workspace.plot.items
        if isinstance(item, pg.InfiniteLine) and getattr(item, "_curvemole_mask_boundary", False)
    ]
    assert len(boundaries) == 1
    assert float(boundaries[0].value()) == pytest.approx(float(curve.x[index]))
    assert not any(
        item.opts.get("pen") is None
        and item.opts.get("symbol") == "o"
        and item.opts.get("symbolSize") == 5
        for item in workspace.plot.listDataItems()
    )

    workspace.close()
    app.processEvents()
