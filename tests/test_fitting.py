from __future__ import annotations

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Model
from curvemole.core.data import CurveState
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


def test_independent_fits_use_multiple_processes_and_commit_results() -> None:
    x = np.linspace(-4, 4, 121)
    curves = [Curve(f"spectrum {i}", x, np.exp(-0.5 * ((x - center) / 0.7) ** 2))
              for i, center in enumerate((-0.8, 0.2, 1.1))]
    models = {
        curve.id: Model(components=[Component.create(
            "gaussian", initial={"area": 1.5, "center": 0.0, "sigma": 1.0})])
        for curve in curves
    }
    progress = []
    completed = []
    result = Fitter().fit(
        FitPlan([curve.id for curve in curves], FitMode.INDEPENDENT,
                FitSettings(workers=2)), curves, models,
        progress=lambda fraction, _: progress.append(fraction),
        on_curve_result=lambda curve_id, fit: completed.append((curve_id, fit.success)),
    )

    assert result.success
    assert len(result.curve_outputs) == 3
    assert set(completed) == {(curve.id, True) for curve in curves}
    assert progress[-1] == 1.0
    for curve, center in zip(curves, (-0.8, 0.2, 1.1), strict=True):
        assert models[curve.id].components[0].parameters["center"].value == pytest.approx(center, abs=0.01)


@pytest.mark.parametrize("workers", [1, 2])
def test_failed_spectrum_is_marked_failed_without_aborting_other_fits(workers: int) -> None:
    x = np.linspace(-3, 3, 81)
    good = Curve("good", x, np.exp(-x ** 2))
    bad = Curve("bad", x, np.exp(-x ** 2))
    bad.state = CurveState.FITTED  # A failed refit must clear the previous tick.
    models = {
        good.id: Model(components=[Component.create("gaussian")]),
        bad.id: Model(),  # No free parameters raises FitError inside the fit.
    }
    result = Fitter().fit(
        FitPlan([good.id, bad.id], FitMode.INDEPENDENT, FitSettings(workers=workers)),
        [good, bad], models,
    )
    assert not result.success
    assert set(result.curve_outputs) == {good.id}
    assert good.state == CurveState.FITTED
    assert bad.state == CurveState.FAILED
    assert "1 failed" in result.message
    assert any("no free parameters" in warning for warning in result.warnings)


def test_all_failed_independent_fits_keep_failed_state() -> None:
    x = np.linspace(-2, 2, 21)
    curves = [Curve(f"bad {i}", x, np.zeros_like(x)) for i in range(2)]
    for curve in curves:
        curve.state = CurveState.FITTED
    result = Fitter().fit(
        FitPlan([curve.id for curve in curves], FitMode.INDEPENDENT, FitSettings(workers=2)),
        curves, {curve.id: Model() for curve in curves},
    )
    assert not result.success
    assert not result.curve_outputs
    assert all(curve.state == CurveState.FAILED for curve in curves)


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


def test_differential_evolution_creates_bounds_without_changing_user_limits(gaussian_curve: Curve) -> None:
    peak = Component.create("gaussian", initial={"area": 3, "center": 0, "sigma": 0.8})
    peak.parameters["sigma"].maximum = 1.0
    model = Model(components=[peak])
    result = Fitter().fit_single(
        gaussian_curve, model,
        FitSettings(solver="differential_evolution", de_lower_percent=50,
                    de_upper_percent=100, de_maxiter=30),
    )
    assert result.success
    assert peak.parameters["center"].value == pytest.approx(0.7, abs=0.05)
    assert np.isneginf(peak.parameters["center"].minimum)
    assert peak.parameters["sigma"].maximum == 1.0


@pytest.mark.parametrize("solver", ["nelder_mead", "powell", "lbfgsb", "trf", "dogbox"])
def test_additional_solvers_fit_bounded_peak(gaussian_curve: Curve, solver: str) -> None:
    peak = Component.create("gaussian", initial={"area": 2.8, "center": 0.5, "sigma": 0.9})
    model = Model(components=[peak])
    result = Fitter().fit_single(gaussian_curve, model, FitSettings(solver=solver))
    assert result.success
    assert peak.parameters["center"].value == pytest.approx(0.7, abs=0.05)


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
