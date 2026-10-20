import copy

import numpy as np
import pytest

from curvemole.core.data import Curve, Transformation
from curvemole.core.display import DisplayOptions, display_curve, operation_keys
from curvemole.core.errors import DataValidationError


def test_replay_keeps_order_and_does_not_mutate_data_errors_or_history():
    curve = Curve('sample', [0, 1, 2], [2, 3, 4], sigma_y=[1, 1, 1])
    curve.apply_transformation(Transformation('y_multiply', {'value': 2}))
    curve.apply_transformation(Transformation('y_add', {'value': 5}))
    curve.apply_transformation(Transformation('normalize_max'))
    before = copy.deepcopy(curve)
    preview = display_curve(curve, DisplayOptions(excluded=frozenset(operation_keys(curve)[:1])))
    np.testing.assert_allclose(preview.y, np.array([7, 8, 9]) / 9)
    np.testing.assert_allclose(preview.current_sigma_y, np.ones(3) / 9)
    np.testing.assert_array_equal(curve.y, before.y)
    np.testing.assert_array_equal(curve.current_sigma_y, before.current_sigma_y)
    assert curve.to_metadata() == before.to_metadata()
    assert display_curve(curve, DisplayOptions()) is curve


def test_original_restores_deleted_rows_and_ignores_masks_and_point_edits():
    curve = Curve('sample', [0, 1, 2, 3], [2, 3, 4, 5], sigma_y=[1, 2, 3, 4])
    curve.masks[curve.active_mask].excluded[1] = True
    curve.delete_points([2])
    curve.move_points([0], x=[8], y=[10])
    preview = display_curve(curve, DisplayOptions(original=True))
    np.testing.assert_array_equal(preview.x, curve.original_x)
    np.testing.assert_array_equal(preview.y, curve.original_y)
    np.testing.assert_array_equal(preview.current_sigma_y, [1, 2, 3, 4])
    assert not preview.effective_mask.any()
    assert len(curve) == 3
    assert curve.masks[curve.active_mask].excluded[1]


def test_restoring_a_deleted_row_preserves_original_mask_identities():
    curve = Curve('sample', [0, 1, 2, 3], [2, 3, 4, 5])
    curve.masks[curve.active_mask].excluded[2] = True
    curve.delete_points([2])
    curve.apply_transformation(Transformation('y_multiply', {'value': 2}))
    preview = display_curve(curve, DisplayOptions(excluded=frozenset(operation_keys(curve)[:1])))
    np.testing.assert_array_equal(preview.y, [4, 6, 8, 10])
    np.testing.assert_array_equal(preview.effective_mask, [False, False, True, False])
    np.testing.assert_array_equal(curve.effective_mask, [False, False, False])


def test_preview_before_background_subtraction_replays_later_operations():
    curve = Curve('sample', [0, 1, 2], [5, 6, 7])
    curve.apply_transformation(Transformation('background_subtract', operand=np.full(3, 2)))
    curve.apply_transformation(Transformation('y_multiply', {'value': 3}))
    preview = display_curve(curve, DisplayOptions(background='restore'))
    np.testing.assert_array_equal(preview.y, [15, 18, 21])
    np.testing.assert_array_equal(curve.y, [9, 12, 15])


def test_dependent_array_operand_rejects_an_incompatible_preview():
    curve = Curve('sample', [0, 1, 2, 3], [2, 3, 4, 5])
    curve.delete_points([1])
    curve.apply_transformation(Transformation('replace_y', operand=np.array([8, 9, 10])))
    before = curve.y.copy()
    with pytest.raises(DataValidationError, match='dependent operation'):
        display_curve(curve, DisplayOptions(excluded=frozenset(operation_keys(curve)[:1])))
    np.testing.assert_array_equal(curve.y, before)
    preview = display_curve(curve, DisplayOptions(excluded=frozenset(operation_keys(curve))))
    np.testing.assert_array_equal(preview.y, curve.original_y)


def test_x_replay_keeps_mask_and_fit_range_membership_on_original_rows():
    curve = Curve('sample', [0, 1, 2, 3], [2, 3, 4, 5])
    curve.apply_transformation(Transformation('x_add', {'value': 100}))
    curve.mask_interval(101, 101.2)
    curve.fit_ranges = [(101, 102)]
    preview = display_curve(curve, DisplayOptions(excluded=frozenset(operation_keys(curve))))
    np.testing.assert_array_equal(preview.x, [0, 1, 2, 3])
    np.testing.assert_array_equal(preview.effective_mask, [True, True, False, True])
    assert all(not mask.ranges for mask in preview.masks.values())
    assert curve.fit_ranges == [(101, 102)]
    assert curve.masks[curve.active_mask].ranges == [(101, 101.2)]
