"""Persist the latest usable fit baseline for each spectrum."""

from __future__ import annotations

import copy
from dataclasses import asdict
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
    selected = copy.deepcopy(result)
    selected.mode = FitMode.INDEPENDENT
    selected.parameters = {path: estimate for path, estimate in selected.parameters.items()
                           if path.startswith(curve_id + ".")}
    selected.curve_outputs = {curve_id: selected.curve_outputs[curve_id]}
    indices = [i for i, path in enumerate(selected.free_parameter_paths)
               if path.startswith(curve_id + ".")]
    selected.free_parameter_paths = [selected.free_parameter_paths[i] for i in indices]
    for field in ("covariance", "correlation"):
        matrix = getattr(selected, field)
        if matrix is not None:
            setattr(selected, field, np.asarray(matrix)[np.ix_(indices, indices)].copy())
    selected.statistics = dict(selected.curve_outputs[curve_id].statistics)
    return selected


def individual_plan(plan: FitPlan, curve_id: str) -> FitPlan:
    if plan.mode == FitMode.GLOBAL:
        return copy.deepcopy(plan)
    return FitPlan([curve_id], FitMode.INDEPENDENT, copy.deepcopy(plan.settings),
                   {curve_id: plan.spectrum_weights.get(curve_id, 1.0)},
                   plan.equal_contribution)
