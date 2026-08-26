from __future__ import annotations

import numpy as np
import pytest

from curvemole.core.initialization import (
    PeakSuggestion,
    initialise_peak_component,
    initialise_spline_component,
)
from curvemole.core.models import Component
from curvemole.core.registry import default_registry


def test_graphical_peak_initialisation_sets_centre_and_fwhm() -> None:
    component = Component.create("gaussian")
    suggestion = PeakSuggestion(x=7.5, height=3.0, fwhm=2.4, prominence=3.0, sign=1)

    initialise_peak_component(component, suggestion)

    assert component.parameters["center"].value == 7.5
    assert 2.354820045 * component.parameters["sigma"].value == pytest.approx(2.4)
    height = default_registry().get("gaussian").evaluate(
        np.array([7.5]),
        {name: parameter.value for name, parameter in component.parameters.items()},
        component.metadata,
    )[0]
    assert height == pytest.approx(3.0)


def test_graphical_spline_initialisation_sorts_and_interpolates_nodes() -> None:
    component = Component.create("cubic_spline", metadata={"x_nodes": [0.0, 1.0]})
    initialise_spline_component(component, [(2.0, 5.0), (0.0, 1.0), (1.0, 2.0)])

    assert component.metadata["x_nodes"] == [0.0, 1.0, 2.0]
    values = {name: parameter.value for name, parameter in component.parameters.items()}
    result = default_registry().get("cubic_spline").evaluate(
        np.array([0.0, 1.0, 2.0]), values, component.metadata
    )
    assert result.tolist() == pytest.approx([1.0, 2.0, 5.0])
