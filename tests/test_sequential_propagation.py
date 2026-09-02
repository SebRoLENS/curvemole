from __future__ import annotations

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Model
from curvemole.core import SequentialFitPlan
from curvemole.core.fitting import FitMode


def _gaussian_curve(name: str, center: float, area: float = 3.0, sigma: float = 0.8) -> Curve:
    x = np.linspace(-5.0, 5.0, 401)
    y = area * np.exp(-0.5 * ((x - center) / sigma) ** 2) / (sigma * np.sqrt(2 * np.pi))
    return Curve(name, x, y)


def _source_model(center: float = 0.4) -> Model:
    return Model(
        components=[
            Component.create(
                "gaussian",
                initial={"area": 3.0, "center": center, "sigma": 0.8},
            )
        ]
    )


def test_sequential_fit_propagates_model_into_empty_targets() -> None:
    curves = [
        _gaussian_curve("source", 0.4),
        _gaussian_curve("second", 0.5, area=3.1),
        _gaussian_curve("third", 0.6, area=3.2),
    ]
    source = _source_model(0.4)
    source_center_before = source.components[0].parameters["center"].value
    models = {
        curves[0].id: source,
        curves[1].id: Model(),
        curves[2].id: Model(),
    }
    plan = SequentialFitPlan(
        [curve.id for curve in curves],
        FitMode.SEQUENTIAL,
        monitor_residuals=False,
        monitor_parameters=False,
    )

    result = Fitter().fit(plan, curves, models)

    assert result.success
    assert source.components[0].parameters["center"].value == source_center_before
    assert len(models[curves[1].id].components) == 1
    assert len(models[curves[2].id].components) == 1
    assert models[curves[1].id].components[0].parameters["center"].value == pytest.approx(0.5, abs=1e-4)
    assert models[curves[2].id].components[0].parameters["center"].value == pytest.approx(0.6, abs=1e-4)
    assert curves[1].id in result.curve_outputs
    assert curves[2].id in result.curve_outputs
    assert curves[0].id not in result.curve_outputs


def test_sequential_fit_pauses_on_large_parameter_jump_after_successful_fit() -> None:
    curves = [
        _gaussian_curve("source", 0.0),
        _gaussian_curve("suspicious", 3.0),
    ]
    models = {curves[0].id: _source_model(0.0), curves[1].id: Model()}
    plan = SequentialFitPlan(
        [curve.id for curve in curves],
        FitMode.SEQUENTIAL,
        monitor_residuals=False,
        monitor_parameters=True,
        parameter_change_limit=0.20,
    )

    result = Fitter().fit(plan, curves, models)

    assert not result.success
    assert result.paused_curve_id == curves[1].id
    assert "parameter" in result.message
    assert curves[1].id in result.curve_outputs
    assert models[curves[1].id].components[0].parameters["center"].value == pytest.approx(3.0, abs=1e-4)


def test_resumed_sequence_uses_manually_approved_paused_spectrum_as_new_source() -> None:
    paused = _gaussian_curve("paused", 1.0)
    following = _gaussian_curve("following", 1.1)
    approved_model = _source_model(1.0)
    models = {paused.id: approved_model, following.id: Model()}
    plan = SequentialFitPlan(
        [paused.id, following.id],
        FitMode.SEQUENTIAL,
        monitor_residuals=False,
        monitor_parameters=False,
    )

    result = Fitter().fit(plan, [paused, following], models)

    assert result.success
    assert approved_model.components[0].parameters["center"].value == 1.0
    assert models[following.id].components[0].parameters["center"].value == pytest.approx(1.1, abs=1e-4)
