from __future__ import annotations

import numpy as np
import pytest

from curvemole import Curve
from curvemole.core.calculator import (
    apply_background_subtraction,
    apply_curve_operation,
    apply_scalar,
)
from curvemole.core.data import aligned_operand
from curvemole.core.errors import DataValidationError


def test_original_data_are_immutable_and_transformations_are_reversible() -> None:
    curve = Curve("c", np.arange(5.0), np.arange(5.0))
    with pytest.raises(ValueError):
        curve.original_y[0] = 100
    apply_scalar(curve, "y_multiply", 3)
    assert curve.y.tolist() == [0, 3, 6, 9, 12]
    assert curve.undo_transformation()
    assert curve.y.tolist() == [0, 1, 2, 3, 4]
    assert curve.redo_transformation()
    assert curve.y.tolist() == [0, 3, 6, 9, 12]
    curve.restore_original()
    assert curve.y.tolist() == [0, 1, 2, 3, 4]


def test_masks_preserve_values_and_use_x_transfer_tolerance() -> None:
    source = Curve("source", np.array([0, 1, 2, 3.0]), np.arange(4.0))
    target = Curve("target", np.array([0.05, 1.05, 2.05, 3.05]), np.arange(4.0))
    source.mask_point(1)
    assert target.transfer_mask_from(source, tolerance=0.1) == 1
    assert target.effective_mask.tolist() == [False, True, False, False]
    assert target.y[1] == 1


def test_invalid_rows_are_stored_but_excluded() -> None:
    curve = Curve("invalid", [0, 1, 2, 3], [1, np.nan, 3, 4])
    assert len(curve) == 4
    x, y, weight, indices = curve.fit_arrays()
    assert x.tolist() == [0, 2, 3]
    assert indices.tolist() == [0, 2, 3]
    assert weight is None


def test_curve_operation_does_not_extrapolate_by_default() -> None:
    target = Curve("target", np.arange(5.0), np.ones(5))
    operand = Curve("operand", np.array([1.0, 2.0, 3.0]), np.array([2.0, 3.0, 4.0]))
    apply_curve_operation(target, operand, "curve_multiply")
    assert np.isnan(target.y[0])
    assert target.y[1:4].tolist() == [2, 3, 4]
    assert np.isnan(target.y[4])


def test_cubic_interpolation_requires_enough_unique_points() -> None:
    with pytest.raises(DataValidationError):
        aligned_operand(np.arange(4.0), np.arange(3.0), np.arange(3.0), method="cubic")

def test_background_subtraction_applies_inside_masks() -> None:
    curve = Curve("background", np.arange(5.0), np.array([10.0, 11.0, 12.0, 13.0, 14.0]))
    curve.mask_interval(1.0, 3.0)
    before_mask = curve.effective_mask.copy()

    apply_background_subtraction(
        curve,
        np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
        method="test",
        description="test background",
    )

    assert curve.y.tolist() == pytest.approx([9.0, 9.0, 9.0, 9.0, 9.0])
    assert curve.effective_mask.tolist() == before_mask.tolist()
    assert curve.undo_transformation()
    assert curve.y.tolist() == pytest.approx([10.0, 11.0, 12.0, 13.0, 14.0])
