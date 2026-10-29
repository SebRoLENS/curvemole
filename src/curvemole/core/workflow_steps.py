"""Checked preprocessing stages using the same reversible core calculator APIs."""

from __future__ import annotations

import math
from collections.abc import Mapping
from numbers import Real
from typing import Any

from curvemole.core.calculator import apply_column_formula, apply_custom_formula, apply_scalar
from curvemole.core.columns import compile_column_formula
from curvemole.core.errors import CurveMoleError
from curvemole.core.expressions import SafeExpression, formula_source
from curvemole.core.project import Project
from curvemole.core.workflow_selection import (
    SELECTOR_KEYS,
    select_curve_ids,
    validate_curve_selector,
)

_SCALAR_OPERATIONS = frozenset({
    "y_add", "y_subtract", "y_multiply", "y_divide", "x_add", "x_multiply",
})
_NORMALIZATIONS = frozenset({"normalize_max", "normalize_area"})
_ACTION_KEYS = frozenset({
    "transformations", "clear_masks", "mask_intervals", "unmask_intervals", "fit_ranges",
})
_INTERVAL_KEYS = ("mask_intervals", "unmask_intervals", "fit_ranges")


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _validate_transformation(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        return ["must be a mapping"]
    operation = value.get("operation")
    if not isinstance(operation, str):
        return ["operation must be a supported operation name"]
    errors = []
    if operation in _SCALAR_OPERATIONS:
        allowed = {"operation", "value"}
        if not _finite_number(value.get("value")):
            errors.append("value must be a finite number")
        elif operation == "y_divide" and value["value"] == 0:
            errors.append("y_divide requires a nonzero value")
    elif operation in _NORMALIZATIONS:
        allowed = {"operation"}
    elif operation in {"custom_formula", "column_formula"}:
        target_key = "axis" if operation == "custom_formula" else "target"
        allowed = {"operation", target_key, "formula"}
        target = value.get(target_key)
        formula = value.get("formula")
        if not isinstance(target, str) or not target.strip():
            errors.append(f"{target_key} must be a non-empty string")
        elif operation == "custom_formula" and target not in {"x", "y"}:
            errors.append("axis must be x or y")
        if not isinstance(formula, str) or not formula.strip():
            errors.append("formula must be a non-empty string")
        if not errors:
            try:
                if operation == "custom_formula":
                    expression = SafeExpression.compile(formula_source(formula, target))
                    if set(expression.variables) - {target} or expression.references:
                        errors.append(f"custom formula may use only {target}")
                else:
                    compile_column_formula(formula, target)
            except CurveMoleError as exc:
                errors.append(str(exc))
    else:
        return [f"unknown operation '{operation}'"]
    unknown = value.keys() - allowed
    if unknown:
        errors.append("unknown field(s): " + ", ".join(sorted(map(str, unknown))))
    return errors


def validate_preprocessing(steps: Any) -> list[str]:
    """Validate all stage shapes and safe formula syntax before changing data.

    Data-dependent conditions (available columns, finite formula results and
    normalization divisors) are checked when the stages execute.
    """
    if not isinstance(steps, list):
        return ["preprocess must be a list"]
    errors = []
    for index, step in enumerate(steps):
        prefix = f"preprocess[{index}]"
        if not isinstance(step, Mapping):
            errors.append(f"{prefix} must be a mapping")
            continue
        unknown = step.keys() - (_ACTION_KEYS | SELECTOR_KEYS)
        if unknown:
            errors.append(f"{prefix} has unknown field(s): " + ", ".join(sorted(map(str, unknown))))
        errors.extend(f"{prefix}: {error}" for error in validate_curve_selector(step, default_all=True))
        if not step.keys() & _ACTION_KEYS:
            errors.append(f"{prefix} must specify at least one preprocessing operation")
        if "clear_masks" in step and not isinstance(step["clear_masks"], bool):
            errors.append(f"{prefix}.clear_masks must be a boolean")
        for name in _INTERVAL_KEYS:
            if name not in step:
                continue
            intervals = step[name]
            if not isinstance(intervals, list):
                errors.append(f"{prefix}.{name} must be a list of two-number intervals")
                continue
            for number, pair in enumerate(intervals):
                if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                        or not all(_finite_number(item) for item in pair)):
                    errors.append(f"{prefix}.{name}[{number}] must contain two finite numbers")
        if "transformations" in step:
            transformations = step["transformations"]
            if not isinstance(transformations, list):
                errors.append(f"{prefix}.transformations must be a list")
            else:
                for number, transformation in enumerate(transformations):
                    errors.extend(
                        f"{prefix}.transformations[{number}]: {error}"
                        for error in _validate_transformation(transformation)
                    )
    return errors


def apply_preprocessing(
    project: Project, steps: list[Mapping[str, Any]], aliases: Mapping[str, str],
) -> None:
    """Apply steps before model construction and fitting, preserving originals.

    Each step applies transformations in order, clears all named masks if
    requested, masks intervals, unmasks intervals, then replaces fit ranges.
    Intervals therefore refer to the transformed X coordinate. Shape and selector
    failures precede any mutation; a later data-dependent failure can leave prior
    in-memory edits. The workflow runner saves no output before these stages.
    """
    errors = validate_preprocessing(steps)
    if errors:
        raise CurveMoleError("Invalid preprocessing: " + "; ".join(errors))
    planned = [
        (step, select_curve_ids(project, aliases, default_all=True, **{
            name: step[name] for name in SELECTOR_KEYS if name in step
        }))
        for step in steps
    ]
    if not planned:
        return
    project.touch()  # Also reject read-only projects before modifying their curves.
    affected = {identity for _step, identities in planned for identity in identities}
    project.invalidate_fits(affected)
    for step, identities in planned:
        for identity in identities:
            curve = project.dataset.curve(identity)
            for transformation in step.get("transformations", []):
                operation = transformation["operation"]
                if operation == "custom_formula":
                    apply_custom_formula(curve, transformation["axis"], transformation["formula"])
                elif operation == "column_formula":
                    apply_column_formula(curve, transformation["target"], transformation["formula"])
                else:
                    apply_scalar(curve, operation, transformation.get("value"))
            if step.get("clear_masks", False):
                for name in tuple(curve.masks):
                    curve.clear_mask(name)
            for lower, upper in step.get("mask_intervals", []):
                curve.mask_interval(lower, upper)
            for lower, upper in step.get("unmask_intervals", []):
                curve.unmask_interval(lower, upper)
            if "fit_ranges" in step:
                curve.fit_ranges = [tuple(sorted(map(float, pair))) for pair in step["fit_ranges"]]
