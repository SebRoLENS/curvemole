"""Scientific invariants from the November 2026 audit."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Model, Project
from curvemole.core.calculator import apply_scalar
from curvemole.core.data import CurveState, Transformation
from curvemole.core.errors import FitError
from curvemole.core.fitting import FitPlan, FitSettings
from curvemole.core.functions import formula_definition
from curvemole.core.registry import default_registry
from curvemole.core.uncertainty import UncertaintyAnalyzer


def constant_fit(y, *, settings=None, **kwargs):
    c = Curve("c", np.arange(len(y), dtype=float), y, **kwargs)
    m = Model(components=[Component.create("constant")])
    return c, m, Fitter().fit_single(c, m, settings)


def test_huber_sandwich_matches_location_reference_and_is_solver_independent():
    results = [
        constant_fit(
            [0, 0, 0, 0, 10], settings=FitSettings(solver=solver, loss="huber", f_scale=1)
        )[2]
        for solver in ("local", "powell")
    ]
    for r in results:
        assert r.success
        assert next(iter(r.parameters.values())).value == pytest.approx(0.25)
        assert r.covariance[0, 0] == pytest.approx(0.09765625, rel=1e-5)


@pytest.mark.parametrize("loss", ["soft_l1", "cauchy"])
def test_other_robust_covariances_are_solver_independent(loss):
    results = [
        constant_fit(
            [0, 0.1, -0.1, 0.2, 10],
            settings=FitSettings(solver=solver, loss=loss, f_scale=1, powell_xtol=1e-10),
        )[2]
        for solver in ("local", "powell")
    ]
    assert results[0].covariance == pytest.approx(results[1].covariance, rel=1e-4)


def test_profile_is_invariant_to_measurement_units_when_noise_scale_is_unknown():
    profiles = []
    for factor in (1, 100):
        c, m, result = constant_fit(np.arange(5.0) * factor)
        profile = UncertaintyAnalyzer().profile_parameter(
            result, c, m, next(iter(result.parameters)), lower=factor, upper=3 * factor, points=41
        )
        profiles.append(profile)
    assert profiles[0].delta_chi_square == pytest.approx(profiles[1].delta_chi_square)
    assert profiles[0].interval == pytest.approx(np.asarray(profiles[1].interval) / 100)


def test_profile_known_sigma_uses_chi_square_and_robust_profile_is_rejected():
    c, m, r = constant_fit(np.arange(5.0), sigma_y=np.ones(5))
    p = UncertaintyAnalyzer().profile_parameter(
        r, c, m, next(iter(r.parameters)), lower=1, upper=3, points=3
    )
    assert p.delta_chi_square == pytest.approx([5, 0, 5])
    r.settings.loss = "huber"
    with pytest.raises(FitError, match="robust"):
        UncertaintyAnalyzer().profile_parameter(r, c, m, next(iter(r.parameters)))


def test_profile_convolution_preserves_regular_grid_before_masking():
    x = np.linspace(-5, 5, 101)
    signal = Component.create("gaussian", initial={"area": 2, "center": 0, "sigma": 0.5})
    kernel = Component.create(
        "gaussian", operator="convolve", initial={"area": 1, "center": 0, "sigma": 0.3}
    )
    for comp in (signal, kernel):
        for name, parameter in comp.parameters.items():
            parameter.fixed = not (comp is signal and name == "area")
    model = Model(components=[signal, kernel])
    curve = Curve("conv", x, model.evaluate(x), sigma_y=np.ones(len(x)))
    curve.add_mask("interior").excluded[30] = True
    baseline = Fitter().fit_single(curve, model)
    profile = UncertaintyAnalyzer().profile_parameter(
        baseline,
        curve,
        model,
        next(iter(baseline.free_parameter_paths)),
        lower=1.9,
        upper=2.1,
        points=5,
    )
    assert profile.failed_points == 0
    assert np.isfinite(profile.delta_chi_square).all()


def test_inverse_variance_propagates_like_sigma_for_scalars_and_formulas():
    weighted = Curve("w", [1, 2, 3], [1, 2, 3], weights=[1, 4, 9])
    errors = Curve("s", [1, 2, 3], [1, 2, 3], sigma_y=1 / np.sqrt([1, 4, 9]))
    for c in (weighted, errors):
        apply_scalar(c, "y_multiply", -10)
        c.apply_transformation(Transformation("custom_formula", {"axis": "y", "formula": "y**2"}))
    assert weighted.fit_arrays()[2] == pytest.approx(errors.fit_arrays()[2], rel=1e-5)
    weighted.undo_transformation()
    assert weighted.current_weights == pytest.approx([0.01, 0.04, 0.09])


def test_zero_weight_rows_do_not_change_uncertainty_or_sample_count():
    _, _, a = constant_fit([1, 2, 4], weights=[1, 1, 1])
    _, _, b = constant_fit([1, 2, 4, 9999, -9999], weights=[1, 1, 1, 0, 0])
    assert b.covariance == pytest.approx(a.covariance)
    assert b.statistics["N"] == 3
    assert b.statistics["degrees_of_freedom"] == 2


def test_gaussian_information_criteria_follow_weighted_likelihood():
    c, m, r = constant_fit([10, 1, -1, 2], sigma_y=[100, 0.1, 0.1, 0.1])
    assert r.statistics["negative_twice_log_likelihood"] == pytest.approx(
        r.statistics["chi_square"] + len(c) * np.log(2 * np.pi) + 2 * np.log(c.sigma_y).sum()
    )
    assert r.statistics["likelihood_parameters"] == 1
    assert r.statistics["AIC"] == pytest.approx(r.statistics["negative_twice_log_likelihood"] + 2)
    # Relative weights and sigma with an estimated common scale are equivalent.
    _, _, w = constant_fit(
        c.y, weights=1 / c.sigma_y**2, settings=FitSettings(absolute_sigma=False)
    )
    _, _, e = constant_fit(c.y, sigma_y=c.sigma_y, settings=FitSettings(absolute_sigma=False))
    assert w.statistics["AIC"] == pytest.approx(e.statistics["AIC"])
    assert w.statistics["likelihood_parameters"] == 2


def test_copy_fit_invalidates_transitive_link_dependents():
    p = Project()
    curves = [Curve(str(i), [0, 1], [1, 2]) for i in range(3)]
    comps = [Component.create("constant", initial={"offset": i + 1}) for i in range(3)]
    for c, comp in zip(curves, comps, strict=True):
        p.add_curve(c)
        p.add_component(c.id, comp)
        c.state = CurveState.FITTED
    comps[2].parameters["offset"].link = "${" + f"{curves[1].id}.{comps[1].id}.offset" + "}"
    p.copy_fit(curves[0].id, [curves[1].id], structure=False)
    assert curves[0].state == CurveState.FITTED
    assert curves[1].state == curves[2].state == CurveState.MODIFIED


def test_disabled_formula_has_same_serial_and_parallel_behavior():
    registry = default_registry().copy()
    registry.register(formula_definition("disabled_audit_custom", "disabled", "scale*x"))
    curves = [Curve(str(i), np.arange(5.0), np.arange(5.0) * 0.1 + 2) for i in range(2)]
    models = {}
    for c in curves:
        disabled = Component.create("disabled_audit_custom", registry=registry)
        disabled.enabled = False
        models[c.id] = Model(components=[Component.create("constant"), disabled])
    results = [
        Fitter(registry).fit(
            FitPlan([c.id for c in curves], settings=FitSettings(workers=n)),
            curves,
            copy.deepcopy(models),
        )
        for n in (1, 2)
    ]
    assert all(r.success for r in results)
    assert [p.value for p in results[0].parameters.values()] == pytest.approx(
        [p.value for p in results[1].parameters.values()]
    )


def test_zero_residual_profile_needs_an_explicit_known_noise_scale():
    c, m, r = constant_fit(np.ones(5))
    with pytest.raises(FitError, match="zero-residual"):
        UncertaintyAnalyzer().profile_parameter(r, c, m, next(iter(r.parameters)))


def test_unknown_scale_global_profile_uses_all_uncoupled_curves():
    from curvemole.core.fitting import FitMode

    curves = [Curve(str(i), np.arange(5.0), np.arange(5.0) + i) for i in range(2)]
    models = {c.id: Model(components=[Component.create("constant")]) for c in curves}
    r = Fitter().fit(FitPlan([c.id for c in curves], mode=FitMode.GLOBAL), curves, models)
    c = curves[0]
    path = next(iter(models[c.id].parameter_map(c.id)))
    prof = UncertaintyAnalyzer().profile_parameter(
        r, c, models[c.id], path, lower=1, upper=3, points=3
    )
    assert prof.delta_chi_square == pytest.approx([10 * np.log(25 / 20), 0, 10 * np.log(25 / 20)])


def test_cancellation_before_covariance_restores_model_and_curve_state():
    from curvemole.core.errors import FitCancelled
    from curvemole.core.fitting import CancellationToken

    c = Curve("cancel", np.arange(5.0), [0, 0, 0, 0, 10])
    comp = Component.create("constant", initial={"offset": 7})
    model = Model(components=[comp])
    token = CancellationToken()
    original_state = c.state

    def progress(fraction, text):
        if text.startswith("Evaluation "):
            token.cancel()

    with pytest.raises(FitCancelled):
        Fitter().fit(
            FitPlan([c.id], settings=FitSettings(loss="huber")),
            [c],
            {c.id: model},
            cancellation=token,
            progress=progress,
        )
    assert c.state == original_state
    assert comp.parameters["offset"].value == 7
