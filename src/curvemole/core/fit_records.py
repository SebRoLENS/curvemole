"""Persist the latest usable fit baseline for each spectrum."""

from __future__ import annotations

import copy
from dataclasses import asdict, replace
from typing import Any

import numpy as np

from curvemole.core.fitting import FitMode, FitPlan, FitResult, FitSettings, _global_statistics


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
        matrices[field] = (None if matrix is None else matrix.submatrix(indices)
                           if hasattr(matrix, "submatrix") else np.asarray(matrix)[np.ix_(indices, indices)])
    from curvemole.core.provenance import select_fit_record
    output = copy.deepcopy(result.curve_outputs[curve_id])
    return replace(
        result,
        mode=FitMode.INDEPENDENT,
        parameters=copy.deepcopy({
            path: estimate for path, estimate in result.parameters.items()
            if path.startswith(curve_id + ".")
        }),
        curve_outputs={curve_id: output},
        statistics=(copy.deepcopy(result.statistics) if len(result.curve_outputs) == 1 else
                    _global_statistics({curve_id: output}, len(indices), result.settings.loss)),
        warnings=copy.deepcopy(result.warnings),
        settings=copy.deepcopy(result.settings),
        provenance=select_fit_record(result.provenance, curve_id),
        free_parameter_paths=[result.free_parameter_paths[i] for i in indices],
        covariance=matrices["covariance"],
        correlation=matrices["correlation"],
    )


def fit_model_matches(result: FitResult, curve_id: str, model, values) -> bool:
    """Check the current scientific model against fitted values and saved structure."""
    if any(values.get(path) != estimate.value for path, estimate in result.parameters.items()
           if path.startswith(curve_id + ".")):
        return False
    initial = next(
        (item["initial_models"][curve_id] for item in result.provenance.get("executions", [])
         if curve_id in item.get("initial_models", {})),
        result.provenance.get("initial_models", {}).get(curve_id),
    )
    if initial is None:
        return True

    def structure(snapshot):
        components = {}
        for component in snapshot["components"]:
            parameters = {
                name: {field: float(value) if field in {"minimum", "maximum"} else value
                       for field, value in parameter.items()
                       if field not in {"value", "standard_error", "ci_low", "ci_high", "unit"}}
                for name, parameter in component["parameters"].items()
            }
            components[component["id"]] = (
                component["function_id"], component["enabled"], component["operator"],
                parameters, {k: v for k, v in component.get("metadata", {}).items() if k != "custom_name"},
            )
        return components, snapshot.get("operation_order", [])

    return structure(initial) == structure(model.to_dict())


def individual_plan(plan: FitPlan, curve_id: str) -> FitPlan:
    if plan.mode == FitMode.GLOBAL:
        return copy.deepcopy(plan)
    return FitPlan([curve_id], FitMode.INDEPENDENT, copy.deepcopy(plan.settings),
                   {curve_id: plan.spectrum_weights.get(curve_id, 1.0)},
                   plan.equal_contribution)
