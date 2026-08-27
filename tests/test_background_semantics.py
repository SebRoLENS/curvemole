from __future__ import annotations

import numpy as np
import pytest

from curvemole import Component
from curvemole.core.models import Model
from curvemole.core.registry import default_registry


def test_background_is_a_component_property_and_serialises() -> None:
    component = Component.create("gaussian")
    component.is_background = True
    clone = Component.from_dict(component.to_dict())
    assert clone.is_background is True


def test_any_function_can_be_marked_as_background() -> None:
    registry = default_registry()
    assert registry.get("constant").kind == "generic"
    assert registry.get("linear").kind == "generic"
    assert registry.get("polynomial").kind == "generic"
    assert registry.get("cubic_spline").kind == "generic"

    model = Model()
    gaussian = Component.create(
        "gaussian",
        initial={"area": 2.0, "center": 0.0, "sigma": 1.0},
    )
    gaussian.is_background = True
    model.add(gaussian)
    x = np.array([-1.0, 0.0, 1.0])
    result = model.background(x, curve_id="curve", registry=registry)
    expected = registry.get("gaussian").evaluate(
        x, {name: parameter.value for name, parameter in gaussian.parameters.items()}, {}
    )
    assert result == pytest.approx(expected)


def test_explicit_background_selection_can_designate_unmarked_components() -> None:
    model = Model()
    component = Component.create("constant", initial={"offset": 3.0})
    model.add(component)
    x = np.arange(4.0)
    assert model.background(x, curve_id="curve") == pytest.approx(np.zeros(4))
    assert model.background(
        x, curve_id="curve", component_ids={component.id}
    ) == pytest.approx(np.full(4, 3.0))


def test_background_rejects_non_additive_component_composition() -> None:
    model = Model()
    component = Component.create("constant", initial={"offset": 2.0}, operator="multiply")
    component.is_background = True
    model.add(component)
    with pytest.raises(Exception, match="must use add or subtract"):
        model.background(np.arange(3.0), curve_id="curve")
