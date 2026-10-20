"""Non-mutating replay of a spectrum's recorded processing for display."""
from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np

from curvemole.core.data import Curve, Mask, Transformation
from curvemole.core.errors import DataValidationError


def operation_keys(curve: Curve) -> list[str]:
    return [f"{index}:{item.operation}:{item.created_at}"
            for index, item in enumerate(curve.transformations)]


@dataclass(frozen=True)
class DisplayOptions:
    original: bool = False
    background: str = "stored"
    excluded: frozenset[str] = frozenset()

    def includes(self, key: str, operation: Transformation) -> bool:
        return (not self.original and key not in self.excluded
                and not (self.background == "restore" and operation.operation == "background_subtract"))

    def replays(self, curve: Curve) -> bool:
        return self.original or any(not self.includes(key, item)
                                    for key, item in zip(operation_keys(curve), curve.transformations, strict=True))


def display_curve(curve: Curve, options: DisplayOptions) -> Curve:
    """Replay retained operations on detached arrays, retaining original row identities.

    Recorded array operands remain snapshots. A later operand may require rows
    removed by an earlier deletion; reject that combination rather than inventing
    values for restored rows or silently omitting another operation.
    """
    if not options.replays(curve):
        return curve
    preview = copy.copy(curve)
    preview.masks = copy.deepcopy(curve.masks)
    preview._mask_original_excluded = {mask.id: curve.original_mask(mask)
                                       for mask in curve.masks.values()}
    preview.transformations = [item for key, item in zip(operation_keys(curve), curve.transformations, strict=True)
                               if options.includes(key, item)]
    preview.redo_transformations = []
    preview.fit_ranges = []
    if options.original:
        preview.masks = {}
    else:
        # Coordinate-based decorations belong to the processed X axis. Keep
        # their row membership without drawing ranges at incorrect preview X.
        for mask in preview.masks.values():
            mask.ranges = []
        if curve.fit_ranges:
            included = np.zeros(len(curve), dtype=bool)
            for lower, upper in curve.fit_ranges:
                included |= (curve.x >= min(lower, upper)) & (curve.x <= max(lower, upper))
            key = "_display_fit_ranges"
            while key in preview.masks:
                key += "_"
            mask = Mask(key, ~included)
            preview.masks[key] = mask
            excluded = np.zeros(len(curve.original_x), dtype=bool)
            excluded[curve.row_indices] = mask.excluded
            preview._mask_original_excluded[mask.id] = excluded
    try:
        preview._recompute()
    except (DataValidationError, ValueError, IndexError, FloatingPointError) as exc:
        raise DataValidationError(
            f"{curve.name}: these operations cannot be replayed together ({exc}). "
            "Keep the required earlier operation, or also exclude the dependent operation."
        ) from exc
    return preview
