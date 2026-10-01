from __future__ import annotations

import copy

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Model, Project
from curvemole.core.export import parameter_dataframe
from curvemole.core.fitting import FitPlan
from curvemole.core.uncertainty import UncertaintyAnalyzer
from curvemole.core.uncertainty_summary import summarize


def test_marginal_monte_carlo_interval_is_not_compared_with_a_frozen_source_neighborhood():
    rng = np.random.default_rng(17)
    x = np.linspace(-1, 1, 31)
    curve = Curve("Moving source", x, 1 + x + rng.normal(0, .2, len(x)),
                  sigma_y=np.full(len(x), .2))
    component = Component.create("linear", initial={"slope": 1, "intercept": 1})
    for parameter in component.parameters.values():
        parameter.minimum = -10
        parameter.maximum = 10
    target = component.parameters["intercept"]
    target.link = f"${{{curve.id}.{component.id}.slope}}"
    target.link_relation = "similar"
    target.link_tolerance = 1e-4
    model = Model(components=[component])
    project = Project()
    project.add_curve(curve)
    project.models[curve.id] = model
    fitter = Fitter()
    baseline = fitter.fit_single(curve, model)
    assert baseline.success
    target_path = f"{curve.id}.{component.id}.intercept"
    estimate = baseline.parameters[target_path]
    analysis = UncertaintyAnalyzer(fitter).parametric_monte_carlo(
        baseline, FitPlan([curve.id]), [curve], project.models, replicates=20, seed=3,
    )
    assert analysis.completed == 20
    low, high = analysis.intervals[target_path]
    assert high - low > 20 * (estimate.maximum - estimate.minimum)
    row = next(item for item in summarize(project, baseline, analysis, "parametric_monte_carlo")
               if item["path"] == target_path)
    assert "80%" not in row["reasons"]
    assert "allowed range" not in row["reasons"]
    legacy = copy.deepcopy(baseline.to_dict())
    legacy["parameters"][target_path].pop("global_minimum")
    legacy["parameters"][target_path].pop("global_maximum")
    legacy_row = next(item for item in summarize(project, legacy, analysis, "parametric_monte_carlo")
                      if item["path"] == target_path)
    assert "80%" in legacy_row["reasons"]
    exported = parameter_dataframe(project, baseline)
    exported_row = exported.loc[exported["parameter_path"] == target_path].iloc[0]
    assert exported_row["effective_minimum"] == estimate.minimum
    assert exported_row["effective_maximum"] == estimate.maximum
    assert exported_row["global_minimum"] == estimate.global_minimum == -10
    assert exported_row["global_maximum"] == estimate.global_maximum == 10
    assert exported_row["confidence_interval_low"] == estimate.ci_low
    assert exported_row["confidence_interval_high"] == estimate.ci_high
    assert exported_row["confidence_interval_high"] - exported_row["confidence_interval_low"] > (
        exported_row["effective_maximum"] - exported_row["effective_minimum"]
    )


@pytest.mark.parametrize("metadata", [{}, {"global_minimum": None, "global_maximum": None}])
def test_legacy_and_unrecorded_global_domains_keep_static_bound_diagnostics(metadata):
    curve = Curve("Legacy", [0., 1., 2.], [0., 1., 0.])
    component = Component.create("constant", initial={"offset": .5})
    project = Project()
    project.add_curve(curve)
    project.models[curve.id] = Model(components=[component])
    path = f"{curve.id}.{component.id}.offset"
    baseline = {
        "success": True, "settings": {}, "parameters": {
            path: {"value": .5, "minimum": 0, "maximum": 1, "ci_low": 0, "ci_high": 1,
                   "status": "bounded", **metadata},
        },
    }
    row = summarize(project, baseline, {}, "covariance")[0]
    assert row["status"] == "Critical"
    assert "80%" in row["reasons"]
