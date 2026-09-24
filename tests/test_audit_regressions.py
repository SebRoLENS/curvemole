from __future__ import annotations

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Model, Project
from curvemole.core.data import Transformation
from curvemole.core.fitting import FitPlan, FitSettings
from curvemole.core.uncertainty import UncertaintyAnalyzer


def line():
    x = np.linspace(0, 1, 20)
    return Curve("line", x, 1 + 2*x + .01*np.sin(15*x), sigma_y=np.full(20, .1))


def test_disabled_parameters_do_not_change_statistics_but_link_dependencies_remain():
    c = line()
    m = Model(components=[Component.create("linear")])
    baseline = Fitter().fit_single(c, m)
    disabled = Component.create("gaussian")
    disabled.enabled = False
    m.add(disabled)
    result = Fitter().fit_single(c, m)
    assert result.statistics["k"] == 2
    assert result.statistics["degrees_of_freedom"] == 18
    assert result.statistics["AIC"] == pytest.approx(baseline.statistics["AIC"])
    assert not any("rank-deficient" in w for w in result.warnings)
    # A disabled component can still supply a genuinely used linked parameter.
    m.components[0].parameters["intercept"].link = "${" + m.parameter_path(c.id, disabled.id, "center") + "}"
    result = Fitter().fit_single(c, m)
    assert result.success and result.statistics["k"] == 2
    assert disabled.parameters["center"].value == pytest.approx(1, abs=.01)


def test_masked_block_bootstrap_and_current_sigma_are_preserved():
    c = line()
    c.apply_transformation(Transformation("y_multiply", {"value": 10}))
    c.mask_interval(.4, .5)
    m = Model(components=[Component.create("linear")])
    plan = FitPlan([c.id])
    baseline = Fitter().fit(plan, [c], {c.id: m})

    class CheckedFitter(Fitter):
        def fit(self, plan, curves, models, **kwargs):
            trial = curves[c.id]
            np.testing.assert_array_equal(trial.current_sigma_y, c.current_sigma_y)
            np.testing.assert_array_equal(trial.effective_mask, c.effective_mask)
            assert not trial.transformations
            return super().fit(plan, curves, models, **kwargs)

    analyzer = UncertaintyAnalyzer(CheckedFitter())
    for method in (analyzer.block_bootstrap, analyzer.parametric_monte_carlo, analyzer.residual_bootstrap):
        result = method(baseline, plan, [c], {c.id: m}, replicates=3, seed=42)
        assert result.completed == 3
    assert len(c.transformations) == 1


def test_copy_value_uses_new_not_old_bounds():
    p = Project()
    a, b = line(), line()
    p.add_curve(a)
    p.add_curve(b)
    source = Component.create("constant", initial={"offset": 8})
    target = Component.create("constant", initial={"offset": .5})
    source.parameters["offset"].set_bounds(0, 10)
    target.parameters["offset"].set_bounds(0, 1)
    p.models[a.id] = Model(components=[source])
    p.models[b.id] = Model(components=[target])
    p.copy_fit(a.id, [b.id], structure=False)
    assert target.parameters["offset"].value == 8
    assert target.parameters["offset"].maximum == 10


def test_linked_uncertainty_at_exact_upper_bound():
    c = line()
    m = Model(components=[Component.create("linear")])
    q = m.components[0]
    q.parameters["slope"].value = .5
    q.parameters["slope"].maximum = 1
    q.parameters["intercept"].link = "${" + m.parameter_path(c.id, q.id, "slope") + "}"
    result = Fitter().fit_single(c, m, FitSettings(solver="nelder_mead"))
    assert result.success
    assert q.parameters["slope"].value == 1
    assert q.parameters["slope"].standard_error > 0
    assert q.parameters["intercept"].standard_error == pytest.approx(q.parameters["slope"].standard_error)


def test_one_parameter_profile_matches_direct_chi_square_and_preserves_state():
    c = line()
    m = Model(components=[Component.create("constant")])
    baseline = Fitter().fit_single(c, m)
    state = c.state
    path = next(iter(baseline.parameters))
    result = UncertaintyAnalyzer().profile_parameter(baseline, c, m, path, points=5)
    assert result.failed_points == 0
    expected = [np.sum(((c.y - v)/c.current_sigma_y)**2) - baseline.statistics["chi_square"] for v in result.values]
    np.testing.assert_allclose(result.delta_chi_square, np.maximum(expected, 0), atol=1e-10)
    assert c.state == state


def test_fast_mask_transfer_matches_brute_force_with_unsorted_and_duplicate_x():
    rng = np.random.default_rng(7)
    a = Curve("source", rng.integers(0, 100, 500), np.ones(500))
    b = Curve("target", rng.integers(0, 100, 600), np.ones(600))
    a.masks[a.active_mask].excluded[::3] = True
    values = a.x[a.masks[a.active_mask].excluded]
    expected = np.any(np.abs(b.x[:, None] - values) <= .5, axis=1)
    b.transfer_mask_from(a, tolerance=.5)
    np.testing.assert_array_equal(b.masks[b.active_mask].excluded, expected)
    p = Project()
    p.add_curve(a)
    p.add_curve(b)
    p.ui_state["mask_transfer_tolerance"] = .5
    extra = Curve("extra", b.x, b.y)
    p.add_curve(extra)
    p.copy_fit(a.id, [b.id, extra.id], masks=True)
    np.testing.assert_array_equal(b.effective_mask, extra.effective_mask)
    expected[:] = False
    for value in values:
        i = np.argmin(abs(b.x - value))
        if abs(b.x[i] - value) <= .5:
            expected[i] = True
    np.testing.assert_array_equal(b.masks[b.active_mask].excluded, expected)
