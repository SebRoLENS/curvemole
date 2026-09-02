from __future__ import annotations

import math

import numpy as np

from curvemole import Component, Curve, Model
from curvemole.core.sequential_fit import (
    SequentialFitPlan,
    _clone_model_for_target,
    _largest_parameter_jump,
)


def _curve(name: str) -> Curve:
    x = np.linspace(-5.0, 5.0, 101)
    return Curve(name, x, np.exp(-0.5 * x**2))


def _configured_model() -> Model:
    component = Component.create(
        "gaussian",
        initial={"area": 2.0, "center": 0.5, "sigma": 0.8},
    )
    component.name = "Tracked peak"
    component.is_background = True
    component.enabled = False
    component.group = "group-a"
    component.operator = "subtract"
    center = component.parameters["center"]
    center.minimum = -1.0
    center.maximum = 2.0
    center.fixed = True
    center.link = "${source_curve.component_anchor.center}"
    return Model(components=[component])


def test_sequential_plan_preserves_model_state_by_default() -> None:
    plan = SequentialFitPlan(["source", "target"])
    assert plan.propagate_bounds is True
    assert plan.propagate_fixed is True
    assert plan.propagate_links is True
    assert plan.propagate_background is True
    assert plan.propagate_enabled is True
    assert plan.propagate_composition is True
    assert plan.ignored_component_ids == ()


def test_default_clone_preserves_constraints_and_component_state() -> None:
    source_curve = _curve("source")
    target_curve = _curve("target")
    model = _configured_model()
    center = model.components[0].parameters["center"]
    center.link = f"${{{source_curve.id}.component_anchor.center}}"

    clone = _clone_model_for_target(model, source_curve.id, target_curve)

    component = clone.components[0]
    copied = component.parameters["center"]
    assert copied.value == center.value
    assert copied.minimum == -1.0
    assert copied.maximum == 2.0
    assert copied.fixed is True
    assert copied.link == f"${{{target_curve.id}.component_anchor.center}}"
    assert component.is_background is True
    assert component.enabled is False
    assert component.operator == "subtract"
    assert component.group == "group-a"


def test_clone_can_drop_selected_propagation_state() -> None:
    source_curve = _curve("source")
    target_curve = _curve("target")
    model = _configured_model()

    clone = _clone_model_for_target(
        model,
        source_curve.id,
        target_curve,
        propagate_bounds=False,
        propagate_fixed=False,
        propagate_links=False,
        propagate_background=False,
        propagate_enabled=False,
        propagate_composition=False,
    )

    component = clone.components[0]
    center = component.parameters["center"]
    assert center.value == 0.5
    assert math.isinf(center.minimum) and center.minimum < 0
    assert math.isinf(center.maximum) and center.maximum > 0
    assert center.fixed is False
    assert center.link is None
    assert component.is_background is False
    assert component.enabled is True
    assert component.operator == "add"
    assert component.group is None


def test_ignored_function_does_not_trigger_parameter_jump_monitor() -> None:
    curve = _curve("target")
    seed = Model(components=[Component.create("gaussian")])
    fitted = seed.clone()
    component_id = fitted.components[0].id
    fitted.components[0].parameters["center"].value = 4.0

    jump, label, *_ = _largest_parameter_jump(seed, fitted, curve)
    assert jump > 0
    assert label is not None

    ignored_jump, ignored_label, *_ = _largest_parameter_jump(
        seed,
        fitted,
        curve,
        {component_id},
    )
    assert ignored_jump == 0.0
    assert ignored_label is None
