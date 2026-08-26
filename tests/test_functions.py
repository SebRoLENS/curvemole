from __future__ import annotations

import math

import numpy as np
import pytest

from curvemole.core.errors import ExpressionError
from curvemole.core.expressions import SafeExpression, expression_parameters
from curvemole.core.functions import formula_definition
from curvemole.core.models import Component, Model
from curvemole.core.registry import default_registry


@pytest.mark.parametrize(
    ("identifier", "parameters", "expected_fwhm"),
    [
        ("gaussian", {"area": 2.0, "center": 0.3, "sigma": 0.7}, 2.354820045 * 0.7),
        ("lorentzian", {"area": -2.0, "center": 0.3, "gamma": 0.7}, 1.4),
        ("pseudo_voigt", {"area": 2.0, "center": 0.3, "fwhm": 1.4, "eta": 0.3}, 1.4),
    ],
)
def test_peak_area_and_fwhm(identifier: str, parameters: dict[str, float], expected_fwhm: float) -> None:
    definition = default_registry().get(identifier)
    x = np.linspace(-100, 100, 500_001)
    y = definition.evaluate(x, parameters, {})
    assert np.trapezoid(y, x) == pytest.approx(parameters["area"], rel=5e-3)
    assert definition.derived_values(parameters)["FWHM"] == pytest.approx(expected_fwhm)


def test_voigt_is_area_normalised() -> None:
    definition = default_registry().get("voigt")
    x = np.linspace(-200, 200, 400_001)
    y = definition.evaluate(x, {"area": 4, "center": 1, "sigma": 0.5, "gamma": 0.4}, {})
    assert np.trapezoid(y, x) == pytest.approx(4, rel=2e-3)


def test_intrinsic_bounds() -> None:
    component = Component.create("pseudo_voigt")
    assert component.parameters["fwhm"].minimum > 0
    assert component.parameters["eta"].minimum == 0
    assert component.parameters["eta"].maximum == 1


def test_safe_expression_and_detected_parameters() -> None:
    expression = SafeExpression.compile("where(x < center, area*exp(x), area/2)")
    x = np.array([-1.0, 1.0])
    result = expression.evaluate({"x": x, "center": 0.0, "area": 2.0})
    assert result.tolist() == pytest.approx([2 / math.e, 1])
    assert expression_parameters("area * exp(-((x-center)/sigma)**2)") == (
        "area",
        "center",
        "sigma",
    )


@pytest.mark.parametrize(
    "source",
    ["__import__('os')", "x.__class__", "[x for x in y]", "open('secret')", "lambda x: x"],
)
def test_unsafe_expression_rejected(source: str) -> None:
    with pytest.raises(ExpressionError):
        SafeExpression.compile(source)


def test_formula_uses_same_model_contract() -> None:
    registry = default_registry()
    definition = formula_definition("test_linear", "Test linear", "offset + slope*x")
    registry.register(definition, replace=True)
    component = Component.create(
        "test_linear", registry=registry, initial={"offset": 1, "slope": 2}
    )
    model = Model(components=[component])
    assert model.evaluate(np.array([0.0, 1.0, 2.0]), registry=registry).tolist() == [1, 3, 5]
