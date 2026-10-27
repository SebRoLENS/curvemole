"""Recompute recorded model backgrounds after editing their control points."""
from __future__ import annotations

import copy

import numpy as np

from curvemole.core.background_status import background_component_ids
from curvemole.core.errors import DataValidationError


def updated_background_history(curve, model, component, *, values, registry):
    """Return a detached, replay-validated history, or None if not subtracted.

    Replace the existing subtraction in place, including grouped backgrounds,
    rather than appending a second subtraction to already processed data.
    """
    if not component.is_background:
        return None
    identities = background_component_ids(component)
    indices = [i for i, item in enumerate(curve.transformations)
               if item.operation == "background_subtract"
               and identities.intersection(item.parameters.get("component_ids", ()))]
    if not indices:
        return None
    history = copy.deepcopy(curve.transformations)
    stage = copy.deepcopy(curve)
    for index in indices:
        item = history[index]
        requested = set(item.parameters["component_ids"])
        selected = []
        for identity in requested:
            matches = [c for c in model.components if identity in background_component_ids(c)]
            if len(matches) != 1:
                raise DataValidationError("Cannot identify all functions in this recorded background subtraction.")
            selected.append(matches[0].id)
        stage.transformations = history[:index]
        stage._recompute()
        # Control points are expressed on the current X axis. Later deletion is
        # safe, but a changed coordinate system needs an explicit new subtraction.
        positions = np.searchsorted(stage.row_indices, curve.row_indices)
        if (np.any(positions >= len(stage))
                or not np.array_equal(stage.row_indices[positions], curve.row_indices)
                or not np.allclose(stage.x[positions], curve.x, rtol=1e-12, atol=1e-12, equal_nan=True)):
            raise DataValidationError(
                "The X axis changed after background subtraction. Revert the subtraction before editing its points.")
        evaluation_model = model.clone()
        for identity in selected:
            evaluation_model.component(identity).enabled = True
        background = evaluation_model.background(stage.x, curve_id=curve.id, values=values,
            registry=registry, component_ids=set(selected))
        usable = np.isfinite(stage.x) & np.isfinite(stage.y)
        if np.any(usable & ~np.isfinite(background)):
            raise DataValidationError("The edited background produces non-finite values.")
        item.operand = np.asarray(background, dtype=float).copy()
    stage.transformations = history
    stage._recompute()  # Replay subsequent processing before committing anything.
    return history
