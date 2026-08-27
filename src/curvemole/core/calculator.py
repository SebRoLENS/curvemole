"""Non-destructive data-calculator operations."""

from __future__ import annotations

from typing import Any

import numpy as np

from curvemole.core.data import Curve, Transformation, aligned_operand
from curvemole.core.errors import DataValidationError

UNARY_OPERATIONS = {
    "y_add",
    "y_subtract",
    "y_multiply",
    "y_divide",
    "x_add",
    "x_multiply",
    "normalize_max",
    "normalize_area",
}


def apply_scalar(curve: Curve, operation: str, value: float | None = None) -> Transformation:
    if operation not in UNARY_OPERATIONS:
        raise DataValidationError(f"Unknown calculator operation: {operation}")
    parameters: dict[str, Any] = {}
    if operation not in {"normalize_max", "normalize_area"}:
        if value is None or not np.isfinite(value):
            raise DataValidationError(f"Operation '{operation}' requires a finite numeric value.")
        parameters["value"] = float(value)
    transformation = Transformation(
        operation,
        parameters,
        description=_description(operation, value),
    )
    curve.apply_transformation(transformation)
    return transformation


def apply_background_subtraction(
    curve: Curve,
    background: np.ndarray,
    *,
    method: str,
    description: str,
    parameters: dict[str, Any] | None = None,
) -> Transformation:
    """Subtract a background array from every data point, including masked points."""
    values = np.asarray(background, dtype=np.float64).reshape(-1)
    if len(values) != len(curve):
        raise DataValidationError(
            f"Background length {len(values)} does not match curve length {len(curve)}."
        )
    usable = np.isfinite(curve.x) & np.isfinite(curve.y)
    if np.any(usable & ~np.isfinite(values)):
        raise DataValidationError("Background contains invalid values at usable data points.")
    metadata: dict[str, Any] = {"method": str(method)}
    metadata.update(parameters or {})
    transformation = Transformation(
        "background_subtract",
        metadata,
        description=description,
        operand=values.copy(),
    )
    curve.apply_transformation(transformation)
    return transformation


def apply_curve_operation(
    target: Curve,
    operand: Curve,
    operation: str,
    *,
    interpolation: str = "linear",
    extrapolate: bool = False,
) -> Transformation:
    if operation not in {"curve_add", "curve_subtract", "curve_multiply", "curve_divide"}:
        raise DataValidationError(f"Unknown curve-to-curve operation: {operation}")
    aligned = aligned_operand(
        target.x,
        operand.x,
        operand.y,
        method=interpolation,
        extrapolate=extrapolate,
    )
    transformation = Transformation(
        operation,
        {
            "operand_curve_id": operand.id,
            "operand_curve_name": operand.name,
            "interpolation": interpolation,
            "extrapolate": extrapolate,
        },
        description=f"{operation} with {operand.name} ({interpolation} interpolation)",
        operand=aligned,
    )
    target.apply_transformation(transformation)
    return transformation


def _description(operation: str, value: float | None) -> str:
    names = {
        "y_add": "Add to y",
        "y_subtract": "Subtract from y",
        "y_multiply": "Multiply y",
        "y_divide": "Divide y",
        "x_add": "Shift x",
        "x_multiply": "Scale x",
        "normalize_max": "Normalise y by maximum absolute value",
        "normalize_area": "Normalise y by signed integrated area",
    }
    return names[operation] if value is None else f"{names[operation]}: {value:.17g}"
