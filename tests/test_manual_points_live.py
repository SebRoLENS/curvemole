from __future__ import annotations

import numpy as np

from curvemole.core.models import Component
from curvemole.core.registry import default_registry
from curvemole.gui.manual_points import initialise_component_from_points
from curvemole.gui.manual_points_live import (
    _MANUAL_POINTS_KEY,
    _fit_after_generic_point_drag,
    _fit_after_spline_point_drag,
    _set_stored_points,
    _stored_points,
    preview_component_from_points,
)


def test_linear_preview_recalculates_best_line_for_every_point_set() -> None:
    registry = default_registry()
    component = Component.create("linear", registry=registry)
    points = [(0.0, 1.0), (1.0, 3.0), (2.0, 5.2)]

    preview = preview_component_from_points(component, points, registry=registry)

    assert preview is not None
    expected_slope, expected_intercept = np.polyfit(
        np.asarray([0.0, 1.0, 2.0]),
        np.asarray([1.0, 3.0, 5.2]),
        1,
    )
    assert np.isclose(preview.parameters["slope"].value, expected_slope)
    assert np.isclose(preview.parameters["intercept"].value, expected_intercept)
    assert preview.metadata[_MANUAL_POINTS_KEY] == [[0.0, 1.0], [1.0, 3.0], [2.0, 5.2]]


def test_generic_preview_exists_before_minimum_point_count() -> None:
    registry = default_registry()
    component = Component.create("gaussian", registry=registry)

    preview = preview_component_from_points(
        component,
        [(4.0, 2.5)],
        registry=registry,
    )

    assert preview is not None
    values = {name: parameter.value for name, parameter in preview.parameters.items()}
    evaluated = registry.get("gaussian").evaluate(
        np.asarray([3.5, 4.0, 4.5]),
        values,
        preview.metadata,
    )
    assert np.all(np.isfinite(evaluated))


def test_unlocked_generic_manual_point_drag_refits_function() -> None:
    registry = default_registry()
    component = Component.create("linear", registry=registry)
    initialise_component_from_points(
        component,
        [(0.0, 1.0), (2.0, 5.0)],
        registry=registry,
    )
    _set_stored_points(component, [(0.0, 1.0), (2.0, 5.0)])
    for parameter in component.parameters.values():
        parameter.fixed = False

    fitted = _fit_after_generic_point_drag(
        component,
        [(0.0, 1.0), (2.0, 7.0)],
        registry=registry,
    )

    assert np.isclose(fitted.parameters["slope"].value, 3.0)
    assert np.isclose(fitted.parameters["intercept"].value, 1.0)
    assert _stored_points(fitted) == [(0.0, 1.0), (2.0, 7.0)]


def test_spline_manual_point_drag_changes_x_and_y_when_unlocked() -> None:
    registry = default_registry()
    component = Component.create(
        "cubic_spline",
        registry=registry,
        metadata={"x_nodes": [0.0, 1.0, 2.0]},
    )
    initialise_component_from_points(
        component,
        [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)],
        registry=registry,
    )
    _set_stored_points(component, [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)])
    for parameter in component.parameters.values():
        parameter.fixed = False

    fitted, points = _fit_after_spline_point_drag(
        component,
        _stored_points(component),
        1,
        (1.5, 4.0),
        registry=registry,
    )

    assert points == [(0.0, 1.0), (1.5, 4.0), (2.0, 3.0)]
    assert fitted.metadata["x_nodes"] == [0.0, 1.5, 2.0]
    assert np.isclose(fitted.parameters["y1"].value, 4.0)
    assert all(not parameter.fixed for parameter in fitted.parameters.values())
