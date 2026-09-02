from __future__ import annotations

import numpy as np

from curvemole.core.models import Component
from curvemole.core.registry import default_registry
from curvemole.gui.manual_points import (
    initialise_component_from_points,
    manual_points_default,
    minimum_manual_points,
)


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
