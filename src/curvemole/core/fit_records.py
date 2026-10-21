"""Persist the latest usable fit baseline for each spectrum."""

from __future__ import annotations

import copy
from dataclasses import asdict, replace
from typing import Any

import numpy as np

from curvemole.core.fitting import FitMode, FitPlan, FitResult, FitSettings


def plan_to_record(plan: FitPlan) -> dict[str, Any]:
    return dict(curve_ids=list(plan.curve_ids), mode=plan.mode.value,
                settings=asdict(plan.settings), spectrum_weights=dict(plan.spectrum_weights),
                equal_contribution=plan.equal_contribution)


def plan_from_record(value: dict[str, Any]) -> FitPlan:
    return FitPlan(list(value["curve_ids"]), FitMode(value["mode"]),
                   FitSettings(**value["settings"]), dict(value.get("spectrum_weights", {})),
                   bool(value.get("equal_contribution", False)))


def baseline_for_curve(result: FitResult, curve_id: str) -> FitResult:
    """Extract one independent spectrum without losing its covariance block."""
    if curve_id not in result.curve_outputs:
        raise KeyError(curve_id)
    if result.mode == FitMode.GLOBAL:
        return copy.deepcopy(result)  # Coupled parameters require the whole global fit.
    # Select before copying: a batch may contain many large curve arrays and
    # dense covariance matrices, none of which the other baselines need.
    indices = [i for i, path in enumerate(result.free_parameter_paths)
               if path.startswith(curve_id + ".")]
    matrices: dict[str, np.ndarray | None] = {}
    for field in ("covariance", "correlation"):
        matrix = getattr(result, field)
        matrices[field] = None if matrix is None else np.asarray(matrix)[np.ix_(indices, indices)]
    output = copy.deepcopy(result.curve_outputs[curve_id])
    return replace(
        result,
        mode=FitMode.INDEPENDENT,
        parameters=copy.deepcopy({
            path: estimate for path, estimate in result.parameters.items()
            if path.startswith(curve_id + ".")
        }),
        curve_outputs={curve_id: output},
        statistics=copy.deepcopy(output.statistics),
        warnings=copy.deepcopy(result.warnings),
        settings=copy.deepcopy(result.settings),
        free_parameter_paths=[result.free_parameter_paths[i] for i in indices],
        covariance=matrices["covariance"],
        correlation=matrices["correlation"],
    )


def individual_plan(plan: FitPlan, curve_id: str) -> FitPlan:
    if plan.mode == FitMode.GLOBAL:
        return copy.deepcopy(plan)
    return FitPlan([curve_id], FitMode.INDEPENDENT, copy.deepcopy(plan.settings),
                   {curve_id: plan.spectrum_weights.get(curve_id, 1.0)},
                   plan.equal_contribution)
