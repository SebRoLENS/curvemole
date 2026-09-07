from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.gui.app import CurveMoleMainWindow


@pytest.fixture
def plotted():
    app = QApplication.instance() or QApplication([])
    project = Project("view bounds")
    x = np.linspace(100.0, 200.0, 20001)
    y = np.ones_like(x)
    y[123] = 20.0
    curve = Curve("dense descending spectrum", x[::-1], y[::-1])
    project.add_curve(curve)
    project.model_for(curve.id).add(Component.create("constant", initial={"offset": 1e12}))
    window = CurveMoleMainWindow(project)
    app.processEvents()
    yield app, window, curve
    project.dirty = False
    window.close()
    app.processEvents()


def assert_full_data(workspace):
    xr, yr = workspace.view_box.viewRange()
    assert xr[0] < 100 and xr[1] > 200
    assert 0 <= yr[0] < 1 and 20 < yr[1] < 25


def test_initial_view_ignores_model_and_includes_dense_data(plotted):
    _, window, _ = plotted
    assert_full_data(window.plot_workspace)


@pytest.mark.parametrize("entry", ["method", "context", "button", "menu"])
def test_view_all_recovers_full_data_after_clipping(plotted, entry):
    app, window, _ = plotted
    workspace = window.plot_workspace
    workspace.view_box.setRange(xRange=(145, 150), yRange=(0.8, 1.2), padding=0)
    app.processEvents()
    if entry == "method":
        workspace.auto_range()
    elif entry == "context":
        workspace.view_box.getMenu(None).viewAll.trigger()
    elif entry == "button":
        workspace.plot.autoBtn.clicked.emit(workspace.plot.autoBtn)
    else:
        window.auto_axes_action.trigger()
    app.processEvents()
    assert_full_data(workspace)
    workspace.refresh()
    app.processEvents()
    assert_full_data(workspace)


def test_active_excludes_masks_but_all_includes_them(plotted):
    app, window, curve = plotted
    workspace = window.plot_workspace
    mask = curve.add_mask("ends")
    mask.excluded[:] = (curve.x < 130) | (curve.x > 170)
    workspace.refresh()
    workspace.view_active_action.trigger()
    app.processEvents()
    xr, yr = workspace.view_box.viewRange()
    assert 125 < xr[0] < 130 and 170 < xr[1] < 175
    assert yr[1] < 20
    workspace.auto_range()
    assert_full_data(workspace)
    mask.excluded[:] = True
    before = workspace.view_box.viewRange()
    workspace.view_active()
    np.testing.assert_allclose(workspace.view_box.viewRange(), before)


def test_waterfall_includes_offsets_and_only_visible_curves(plotted):
    _, window, _ = plotted
    workspace = window.plot_workspace
    curve = Curve("second", np.array([100., 200.]), np.array([1., 2.]))
    window.project.add_curve(curve)
    workspace.display_mode.setCurrentIndex(2)
    workspace.x_offset.setValue(500)
    workspace.y_offset.setValue(100)
    workspace.auto_range()
    xr, yr = workspace.view_box.viewRange()
    assert xr[0] < 100 and xr[1] > 700
    assert 102 < yr[1] < 120
    curve.visible = False
    workspace.auto_range()
    assert_full_data(workspace)


def test_log_axes_follow_experimental_data(plotted):
    _, window, _ = plotted
    workspace = window.plot_workspace
    workspace.set_log_x(True)
    workspace.set_log_y(True)
    workspace.auto_range()
    xr, yr = workspace.view_box.viewRange()
    assert xr[0] < 2 and xr[1] > np.log10(200)
    assert yr[0] < 0 and np.log10(20) < yr[1] < 2
