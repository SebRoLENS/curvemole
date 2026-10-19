from __future__ import annotations

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Model, Project
from curvemole.core.calculator import apply_column_formula, apply_scalar
from curvemole.core.data import CurveState, Transformation
from curvemole.core.errors import DataValidationError
from curvemole.core.export import ExportSelection, tidy_dataframe, wide_dataframe
from curvemole.core.fitting import FitPlan
from curvemole.core.serialization import capture_project_snapshot, load_project, save_project
from curvemole.core.spectrum_export import spectrum_export_dataframe
from curvemole.core.uncertainty import UncertaintyAnalyzer


def data_curve(*, asymmetric=False):
    columns = {'c1': np.arange(6.), 'c2': np.arange(6.) + 10, 'c3': np.arange(6.) + 20}
    return Curve('Data', columns['c1'], columns['c2'], sigma_x=np.arange(6.) + .1,
                 sigma_y=None if asymmetric else np.arange(6.) + .2,
                 error_y_plus=np.arange(6.) + .4 if asymmetric else None,
                 error_y_minus=np.arange(6.) + .3 if asymmetric else None,
                 weights=np.arange(6.) + 1, original_columns=columns,
                 column_axes={'x': 'c1', 'y': 'c2'}, column_labels={'c1': 'x', 'c2': 'y', 'c3': 'extra'})


def test_move_keeps_originals_and_tracks_transformations_and_state():
    curve = data_curve()
    curve.state = CurveState.FITTED
    previous_hash = curve.content_hash
    curve.move_points([3, 1], x=[30, 10], y=[300, 100])
    np.testing.assert_array_equal(curve.x, [0, 10, 2, 30, 4, 5])
    np.testing.assert_array_equal(curve.y, [10, 100, 12, 300, 14, 15])
    np.testing.assert_array_equal(curve.original_x, np.arange(6.))
    np.testing.assert_array_equal(curve.original_y, np.arange(6.) + 10)
    np.testing.assert_array_equal(curve.columns['c1'], curve.x)
    np.testing.assert_array_equal(curve.columns['c2'], curve.y)
    assert curve.state == CurveState.MODIFIED
    assert curve.content_hash != previous_hash
    assert not curve.original_x.flags.writeable
    assert not curve.row_indices.flags.writeable
    assert curve.undo_transformation()
    assert curve.content_hash == previous_hash
    assert curve.redo_transformation()
    assert curve.x[3] == 30


@pytest.mark.parametrize('asymmetric', [False, True])
def test_delete_compresses_all_current_arrays_and_restores_masks(asymmetric):
    curve = data_curve(asymmetric=asymmetric)
    curve.mask_point(2)
    curve.add_mask('Other')
    curve.mask_point(4)
    curve.fit_ranges = [(1, 5)]
    original_errors = (curve.current_sigma_y, curve.current_error_y_plus, curve.current_error_y_minus)
    curve.delete_points([2, 4])
    assert len(curve) == 4
    assert len(curve.original_x) == 6
    np.testing.assert_array_equal(curve.row_indices, [0, 1, 3, 5])
    np.testing.assert_array_equal(curve.x, [0, 1, 3, 5])
    np.testing.assert_array_equal(curve.current_weights, [1, 2, 4, 6])
    np.testing.assert_array_equal(curve.current_sigma_x, [.1, 1.1, 3.1, 5.1])
    np.testing.assert_array_equal(curve.columns['c3'], [20, 21, 23, 25])
    np.testing.assert_array_equal(curve.effective_mask, [True, False, False, False])
    for current, original in zip((curve.current_sigma_y, curve.current_error_y_plus,
                                  curve.current_error_y_minus), original_errors, strict=True):
        if original is not None:
            np.testing.assert_array_equal(current, original[[0, 1, 3, 5]])
    curve.mask_point(3, name='Default')
    assert curve.undo_transformation()
    np.testing.assert_array_equal(curve.masks['Default'].excluded, [False, False, True, True, False, False])
    np.testing.assert_array_equal(curve.masks['Other'].excluded, [False, False, False, False, True, False])
    assert curve.redo_transformation()
    np.testing.assert_array_equal(curve.masks['Default'].excluded, [False, False, True, False])


def test_point_identity_survives_deletion_calculator_and_restoration():
    curve = data_curve()
    curve.delete_points([0, 2])
    curve.move_points([1], x=[30], y=[300])  # Current index 1 is original row 3.
    assert curve.transformations[-1].parameters['indices'] == [3]
    apply_column_formula(curve, 'c3', 'c1 + c2')
    apply_scalar(curve, 'y_multiply', 2)
    np.testing.assert_array_equal(curve.columns['c3'], curve.x + curve.y / 2)
    curve.restore_original()
    assert len(curve) == 6
    np.testing.assert_array_equal(curve.y, curve.original_y)
    for _ in range(4):
        assert curve.redo_transformation()
    assert curve.x[1] == 30
    assert curve.y[1] == 600


@pytest.mark.parametrize('operation', [
    lambda c: c.move_points([0], x=[np.inf]),
    lambda c: c.move_points([0], y=[np.nan]),
    lambda c: c.move_points([0, 1], x=[3]),
    lambda c: c.move_points([0]),
    lambda c: c.delete_points([0, 0]),
    lambda c: c.delete_points([-1]),
    lambda c: c.delete_points([6]),
    lambda c: c.delete_points([1.2]),
    lambda c: c.delete_points([True]),
    lambda c: c.delete_points([0, 1, 2, 3, 4]),
    lambda c: c.apply_transformation(Transformation('move_points', {'indices': [99], 'x': [0]})),
    lambda c: c.apply_transformation(Transformation('delete_points', {'indices': [-1]})),
])
def test_invalid_edits_are_atomic_and_keep_redo(operation):
    curve = data_curve()
    curve.move_points([0], x=[7])
    curve.undo_transformation()
    before = curve.content_hash
    with pytest.raises(DataValidationError):
        operation(curve)
    assert curve.content_hash == before
    assert curve.transformations == []
    assert len(curve.redo_transformations) == 1
    assert curve.redo_transformation()
    assert curve.x[0] == 7


@pytest.mark.parametrize('snapshot', [False, True])
def test_project_roundtrip_preserves_deleted_rows_masks_and_transform_redo(tmp_path, snapshot):
    curve = data_curve(asymmetric=True)
    curve.mask_point(2)
    curve.delete_points([2])
    curve.move_points([1], x=[8], y=[80])
    curve.undo_transformation()
    project = Project()
    project.add_curve(curve)
    source = capture_project_snapshot(project) if snapshot else project
    path = tmp_path / 'points.fitproj'
    save_project(source, path, update_project_path=not snapshot)
    restored = load_project(path).curves[0]
    assert len(restored) == 5
    np.testing.assert_array_equal(restored.row_indices, [0, 1, 3, 4, 5])
    np.testing.assert_array_equal(restored.current_error_y_plus, [.4, 1.4, 3.4, 4.4, 5.4])
    assert restored.redo_transformation()
    assert restored.x[1] == 8
    assert restored.undo_transformation()
    assert restored.undo_transformation()
    assert restored.masks['Default'].excluded[2]
    assert len(restored) == 6


def test_exports_and_fits_only_contain_current_points():
    curve = data_curve()
    curve.delete_points([1, 3])
    curve.move_points([1], x=[2.5], y=[13])
    project = Project()
    project.add_curve(curve)
    wide = wide_dataframe(curve, selection=ExportSelection(original_x=True))
    assert len(wide) == 4
    np.testing.assert_array_equal(wide['x original'], [0, 2, 4, 5])
    np.testing.assert_array_equal(wide['weight'], [1, 3, 5, 6])
    assert len(spectrum_export_dataframe(project, curve.id)) == 4
    assert len(tidy_dataframe(project).query("quantity == 'y'")) == 4
    for use_errors in (False, True):
        x, y, weights, indices = curve.fit_arrays(use_data_errors=use_errors)
        assert len(x) == len(y) == len(indices) == 4
        if weights is not None:
            assert len(weights) == 4


def test_revalidation_of_edited_curve_preserves_compressed_masks():
    curve = data_curve()
    curve.mask_point(2)
    curve.delete_points([2])
    curve.__post_init__()  # Plugin host revalidates every curve this way.
    assert len(curve) == 5
    assert curve.undo_transformation()
    assert curve.masks['Default'].excluded[2]


def test_resampling_after_deletions_uses_current_arrays():
    curve = data_curve()
    curve.delete_points([1, 3])
    model = Model(components=[Component.create('linear', initial={'slope': 1, 'intercept': 10})])
    plan = FitPlan([curve.id])
    fitter = Fitter()
    baseline = fitter.fit(plan, [curve], {curve.id: model})
    assert baseline.success
    result = UncertaintyAnalyzer(fitter).residual_bootstrap(
        baseline, plan, [curve], {curve.id: model}, replicates=3, workers=1)
    assert result.completed == 3
