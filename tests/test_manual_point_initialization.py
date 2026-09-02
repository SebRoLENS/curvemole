from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from curvemole.core.models import Component
from curvemole.core.registry import default_registry
from curvemole.gui.manual_points import (
    _make_mask_visuals_mouse_transparent,
    initialise_component_from_points,
    manual_points_default,
    minimum_manual_points,
)
from curvemole.gui.plot import PlotWorkspace


def test_manual_point_defaults() -> None:
    registry = default_registry()
    assert manual_points_default(registry.get("linear")) is True
    assert manual_points_default(registry.get("cubic_spline")) is True
    assert manual_points_default(registry.get("gaussian")) is False


def test_linear_from_explicit_points_is_locked() -> None:
    registry = default_registry()
    component = Component.create("linear", registry=registry)
    initialise_component_from_points(
        component,
        [(0.0, 1.0), (2.0, 5.0)],
        registry=registry,
    )

    assert np.isclose(component.parameters["slope"].value, 2.0)
    assert np.isclose(component.parameters["intercept"].value, 1.0)
    assert all(parameter.fixed for parameter in component.parameters.values())


def test_spline_from_explicit_points_is_locked() -> None:
    registry = default_registry()
    component = Component.create(
        "cubic_spline",
        registry=registry,
        metadata={"x_nodes": [0.0, 1.0]},
    )
    initialise_component_from_points(
        component,
        [(0.0, 2.0), (1.0, 3.0), (2.0, 5.0)],
        registry=registry,
    )

    assert component.metadata["x_nodes"] == [0.0, 1.0, 2.0]
    assert [component.parameters[f"y{index}"].value for index in range(3)] == [2.0, 3.0, 5.0]
    assert all(parameter.fixed for parameter in component.parameters.values())


def test_manual_point_minimum_tracks_function_parameters() -> None:
    registry = default_registry()
    assert minimum_manual_points(Component.create("linear", registry=registry)) == 2
    assert minimum_manual_points(Component.create("gaussian", registry=registry)) == 3
    assert minimum_manual_points(Component.create("voigt", registry=registry)) == 4


def test_mask_visuals_do_not_block_manual_point_clicks() -> None:
    app = QApplication.instance() or QApplication([])
    workspace = PlotWorkspace(default_registry())

    region = pg.LinearRegionItem(values=(1.0, 2.0), movable=False)
    region.setZValue(-20)
    workspace.plot.addItem(region)

    masked_points = workspace.plot.plot(
        [1.25, 1.75],
        [2.0, 3.0],
        pen=None,
        symbol="o",
        symbolSize=5,
        symbolBrush=pg.mkBrush(120, 120, 120, 75),
        symbolPen=None,
    )

    boundary = pg.InfiniteLine(pos=1.5, angle=90, movable=False)
    boundary._curvemole_mask_boundary = True
    workspace.plot.addItem(boundary)

    _make_mask_visuals_mouse_transparent(workspace)

    no_button = Qt.MouseButton.NoButton
    assert region.acceptedMouseButtons() == no_button
    assert boundary.acceptedMouseButtons() == no_button
    assert masked_points.acceptedMouseButtons() == no_button
    assert masked_points.scatter.acceptedMouseButtons() == no_button

    workspace.deleteLater()
    assert app is not None
