from __future__ import annotations

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Model
from curvemole.core.fitting import FitMode, FitPlan, FitSettings


def test_gaussian_fit_recovers_parameters(gaussian_curve: Curve) -> None:
    model = Model()
    model.add(Component.create("constant", initial={"offset": 0.1}))
    peak = Component.create("gaussian", initial={"area": 2.5, "center": 0.4, "sigma": 1.1})
    model.add(peak)
    result = Fitter().fit_single(gaussian_curve, model)
    assert result.success
    assert peak.parameters["area"].value == pytest.approx(3, rel=0.01)
    assert peak.parameters["center"].value == pytest.approx(0.7, abs=0.01)
    assert peak.parameters["sigma"].value == pytest.approx(0.8, rel=0.01)
    assert result.covariance is not None
    assert result.correlation is not None
    assert result.statistics["AIC"] is not None


def test_fixed_and_bound_parameter_states(gaussian_curve: Curve) -> None:
    peak = Component.create("gaussian", initial={"area": 2.5, "center": 0.7, "sigma": 1.0})
    peak.parameters["center"].fixed = True
    peak.parameters["sigma"].minimum = 0.75
    peak.parameters["sigma"].maximum = 0.85
    peak.parameters["sigma"].value = 0.8
    model = Model(components=[peak])
    result = Fitter().fit_single(gaussian_curve, model)
    center_path = model.parameter_path(gaussian_curve.id, peak.id, "center")
    assert result.parameters[center_path].status == "fixed"
    assert result.parameters[center_path].standard_error is None
    assert 0.75 <= peak.parameters["sigma"].value <= 0.85


def test_global_cross_spectrum_link() -> None:
    x = np.linspace(-5, 5, 301)
    curves = [
        Curve("a", x, np.exp(-0.5 * ((x - 0.4) / 0.7) ** 2)),
        Curve("b", x, 2 * np.exp(-0.5 * ((x - 0.4) / 0.9) ** 2)),
    ]
    models = {}
    for curve in curves:
        model = Model()
        model.add(Component.create("gaussian", initial={"area": 2, "center": 0, "sigma": 1}))
        models[curve.id] = model
    source = models[curves[0].id].components[0]
    target = models[curves[1].id].components[0]
    source_path = models[curves[0].id].parameter_path(curves[0].id, source.id, "center")
    target.parameters["center"].link = "${" + source_path + "}"
    result = Fitter().fit(FitPlan([curve.id for curve in curves], FitMode.GLOBAL), curves, models)
    assert result.success
    assert source.parameters["center"].value == pytest.approx(0.4, abs=1e-6)
    assert target.parameters["center"].value == pytest.approx(0.4, abs=1e-6)
    target_path = models[curves[1].id].parameter_path(curves[1].id, target.id, "center")
    assert result.parameters[target_path].status == "linked"
    assert result.parameters[target_path].standard_error is not None


def test_differential_evolution_requires_explicit_finite_bounds(gaussian_curve: Curve) -> None:
    model = Model(components=[Component.create("gaussian")])
    with pytest.raises(Exception, match="finite user bounds"):
        Fitter().fit_single(
            gaussian_curve,
            model,
            FitSettings(solver="differential_evolution", de_maxiter=2),
        )


def test_robust_loss_does_not_report_information_criteria(gaussian_curve: Curve) -> None:
    model = Model(components=[Component.create("gaussian", initial={"area": 3, "center": 0.6, "sigma": 0.9})])
    result = Fitter().fit_single(gaussian_curve, model, FitSettings(loss="soft_l1"))
    assert result.success
    assert result.statistics["AIC"] is None
    assert any("sandwich" in warning for warning in result.warnings)


def test_nonconverged_fit_restores_the_last_valid_parameters(gaussian_curve: Curve) -> None:
    peak = Component.create(
        "gaussian", initial={"area": 0.1, "center": -3.0, "sigma": 3.0}
    )
    model = Model(components=[peak])
    before = {name: parameter.value for name, parameter in peak.parameters.items()}

    result = Fitter().fit_single(gaussian_curve, model, FitSettings(max_nfev=1))

    assert not result.success
    assert {name: parameter.value for name, parameter in peak.parameters.items()} == before
