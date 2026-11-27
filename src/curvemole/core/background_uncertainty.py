"""Build independent analysis inputs for a recorded background subtraction."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import replace

from curvemole.core.background_status import background_component_ids
from curvemole.core.errors import FitError


def joint_background_components(curve, model):
    """Identify the removed functions and their factors in the current Y units."""
    first = next((i for i, step in enumerate(curve.transformations) if step.is_estimated_background), None)
    if first is None:
        return []
    if any(item.enabled and item.operator not in {"add", "subtract"} for item in model.components):
        raise FitError(f"'{curve.name}' requires manual setup of the joint fit for its model composition.")

    components = {}
    scale = 1.0
    for step in reversed(curve.transformations[first:]):
        if step.operation in {"y_multiply", "y_divide"}:
            scale *= step.target_y_derivative()
            if not math.isfinite(scale) or scale == 0.0:
                raise FitError(f"'{curve.name}' requires a finite, nonzero Y scaling factor for joint fitting.")
            continue
        if step.operation in {"normalize_max", "normalize_area"}:
            raise FitError(f"'{curve.name}' was normalized after subtraction using a factor estimated from its data. "
                           "Analyze before normalization or supply a noise model for it.")
        if not step.is_estimated_background:
            raise FitError(f"'{curve.name}' has a later data operation. Undo the subtraction and set up the joint fit manually.")
        identities = step.parameters.get("component_ids", ())
        if not identities:
            raise FitError(f"The subtracted functions are missing from the history of '{curve.name}'.")
        expected_functions = step.parameters.get("component_functions", {})
        for identity in identities:
            matches = [item for item in model.components if identity in background_component_ids(item)]
            if len(matches) != 1:
                raise FitError(f"A subtracted function on '{curve.name}' is missing or has been replaced.")
            component = matches[0]
            if expected_functions.get(identity, component.function_id) != component.function_id:
                raise FitError(f"The subtracted function '{component.name}' on '{curve.name}' has been replaced.")
            if component.id in components:
                raise FitError(f"'{curve.name}' includes repeated subtractions of '{component.name}'.")
            if component.operator not in {"add", "subtract"}:
                raise FitError(f"'{curve.name}' requires manual setup of the joint fit for its model composition.")
            components[component.id] = (component, scale)
    if not any(parameter.link or parameter.minimum < parameter.maximum
               for component, _ in components.values() for parameter in component.parameters.values()):
        raise FitError(f"The background of '{curve.name}' has no parameter that can vary within its bounds.")
    return list(components.values())


def fit_background_uncertainty(fitter, plan, curves, models, mode, cancellation):
    """Refit copies on either the corrected data or the data before subtraction."""
    if mode not in {"fixed", "joint"}:
        raise FitError("Choose how to handle uncertainty from the subtracted background.")
    source_inputs = {cid: _input_identity(curves[cid], models[cid]) for cid in plan.curve_ids}
    curves = {cid: copy.deepcopy(curves[cid]) for cid in plan.curve_ids}
    models = {cid: models[cid].clone() for cid in plan.curve_ids}
    affected = []
    spline = False
    scaled_backgrounds = {}
    for cid, curve in curves.items():
        if not any(step.is_estimated_background for step in curve.transformations):
            continue
        affected.append(cid)
        if mode == "joint":
            for component, scale in joint_background_components(curve, models[cid]):
                spline |= component.function_id == "cubic_spline"
                component.enabled = True
                component.is_background = True
                component.output_scale *= scale
                if scale != 1.0:
                    scaled_backgrounds.setdefault(cid, {})[component.id] = scale
                for parameter in component.parameters.values():
                    if parameter.minimum < parameter.maximum and (not parameter.link or parameter.link_relation != "equal"):
                        parameter.fixed = False
            curve.transformations = [step for step in curve.transformations if not step.is_estimated_background]
        else:
            curve.transformations = [replace(step, parameters={**step.parameters, "estimated_background": False})
                                     if step.is_estimated_background else step for step in curve.transformations]
        curve._recompute()
    for curve in curves.values():
        if curve.has_correlated_y_errors:
            raise FitError(f"'{curve.name}' still has correlated errors from other data operations.")
    baseline = fitter.fit(plan, curves, models, cancellation=cancellation)
    if not baseline.success:
        raise FitError(baseline.message)
    baseline.provenance["background_uncertainty"] = {
        "mode": mode, "curve_ids": affected, "fixed_spline_positions": spline, "source_inputs": source_inputs,
        "scaled_backgrounds": scaled_backgrounds,
    }
    return baseline, curves, models


def _input_identity(curve, model):
    encoded = json.dumps(model.to_dict(), sort_keys=True, separators=(",", ":"), default=str).encode()
    return [curve.fit_input_hash(), hashlib.sha256(encoded).hexdigest()]


def _identity_matches(curve, model, identity):
    current = _input_identity(curve, model)
    return (current[1] == identity[1]
            and (current[0] == identity[0] or curve.matches_fit_input_hash(identity[0])))


def background_uncertainty_record(baseline):
    if hasattr(baseline, "provenance"):
        provenance = baseline.provenance
    else:
        provenance = baseline.get("provenance", {})
    return provenance.get("background_uncertainty", {})


def background_uncertainty_is_current(project, treatment):
    try:
        return all(_identity_matches(project.dataset.curve(cid), project.models[cid], identity)
                   for cid, identity in treatment["source_inputs"].items())
    except KeyError:
        return False


def background_uncertainty_note(baseline):
    treatment = background_uncertainty_record(baseline)
    if treatment.get("mode") == "fixed":
        return ("Background uncertainty excluded. Intervals from the separate fit are conditional "
                "on the subtracted background.")
    if treatment.get("mode") == "joint":
        note = "Separate joint fit of signal and background on the data before subtraction."
        if treatment.get("fixed_spline_positions"):
            note += " Free spline heights were fitted. Node positions and the choice of nodes were held fixed."
        if treatment.get("scaled_backgrounds"):
            note += (" The fit uses the working Y scale. Parameters of rescaled background functions "
                     "are reported in their units at subtraction.")
        return note
    return None
