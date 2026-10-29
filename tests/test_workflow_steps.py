from __future__ import annotations

import numpy as np
import pytest

from curvemole import Curve, Project
from curvemole.core.data import CurveState
from curvemole.core.errors import CurveMoleError
from curvemole.core.workflow_selection import select_curve_ids, validate_curve_selector
from curvemole.core.workflow_steps import apply_preprocessing, validate_preprocessing


@pytest.fixture
def project():
    value = Project("workflow preprocessing")
    for name in ("scan_2", "scan_10", "reference"):
        value.add_curve(Curve(name, np.arange(5.0), np.arange(1.0, 6.0), sigma_y=np.ones(5)))
    return value


def test_batch_selection_preserves_project_or_explicit_order(project):
    first, second, third = project.curves
    aliases = {"sample_a": first.id, "sample_b": second.id}
    assert select_curve_ids(project, aliases, curves="all") == [first.id, second.id, third.id]
    assert select_curve_ids(project, aliases, curves="first") == [first.id]
    assert select_curve_ids(project, aliases, curves="last") == [third.id]
    assert select_curve_ids(project, aliases, curves=["sample_b", "sample_a"]) == [second.id, first.id]
    assert select_curve_ids(project, aliases, match="scan_*") == [first.id, second.id]
    assert select_curve_ids(project, aliases, match="sample_?") == [first.id, second.id]
    assert select_curve_ids(project, aliases, curve=third.id) == [third.id]
    assert select_curve_ids(project, aliases, default_all=True) == [first.id, second.id, third.id]


def test_literal_names_are_not_batch_selector_keywords(project):
    project.curves[0].name = "first"
    aliases = {"first": project.curves[0].id}
    assert select_curve_ids(project, aliases, curve="first") == [project.curves[0].id]
    assert select_curve_ids(project, aliases, curves=["first"]) == [project.curves[0].id]


@pytest.mark.parametrize("selector", [{}, {"curves": []}, {"curves": "bad"},
    {"curves": ["scan_2", "scan_2"]}, {"curves": [True]}, {"curve": ""},
    {"match": 1}, {"curve": "scan_2", "curves": "all"}])
def test_invalid_selection_shapes_are_reported(selector):
    assert validate_curve_selector(selector)


def test_unknown_ambiguous_and_duplicate_resolved_selectors_fail(project):
    first, second, _third = project.curves
    first.name = second.name = "repeated"
    with pytest.raises(CurveMoleError, match="Ambiguous"):
        select_curve_ids(project, {}, curve="repeated")
    with pytest.raises(CurveMoleError, match="Unknown"):
        select_curve_ids(project, {}, curve="absent")
    with pytest.raises(CurveMoleError, match="same curve"):
        select_curve_ids(project, {"one": first.id}, curves=["one", first.id])
    # A declared workflow identity can disambiguate a repeated display name.
    assert select_curve_ids(project, {"repeated": second.id}, curve="repeated") == [second.id]
    with pytest.raises(CurveMoleError, match="No curves"):
        select_curve_ids(project, {}, match="SCAN_*")


@pytest.mark.parametrize("selector", ["all", "first", "last"])
def test_batch_selector_rejects_empty_project(selector):
    with pytest.raises(CurveMoleError, match="No curves"):
        select_curve_ids(Project(), {}, curves=selector)


def test_preprocessing_uses_transformed_x_and_preserves_originals(project):
    first, second, third = project.curves
    first.mask_interval(0, 4)
    first.add_mask("another")
    first.mask_interval(0, 4)
    original_x, original_y = first.original_x.copy(), first.original_y.copy()
    first.state = CurveState.FITTED
    apply_preprocessing(project, [{
        "match": "scan_*",
        "transformations": [
            {"operation": "x_add", "value": 10},
            {"operation": "y_multiply", "value": -2},
            {"operation": "custom_formula", "axis": "y", "formula": "y = y + 1"},
        ],
        "clear_masks": True,
        "mask_intervals": [[11, 13]],
        "unmask_intervals": [[12, 12]],
        "fit_ranges": [[14, 10]],
    }], {})
    np.testing.assert_array_equal(first.x, original_x + 10)
    np.testing.assert_array_equal(first.y, original_y * -2 + 1)
    np.testing.assert_allclose(first.current_sigma_y, np.full(5, 2.0))
    np.testing.assert_array_equal(first.original_x, original_x)
    np.testing.assert_array_equal(first.original_y, original_y)
    np.testing.assert_array_equal(first.effective_mask, [False, True, False, True, False])
    assert first.fit_ranges == [(10.0, 14.0)]
    assert first.state == CurveState.MODIFIED
    np.testing.assert_array_equal(second.x, original_x + 10)
    np.testing.assert_array_equal(third.x, original_x)
    assert len(first.transformations) == 3


def test_column_formula_and_multiple_steps_run_in_order(project):
    first = project.curves[0]
    apply_preprocessing(project, [
        {"curves": "first", "transformations": [{"operation": "column_formula", "target": "y", "formula": "x + y"}]},
        {"curve": first.id, "transformations": [{"operation": "normalize_max"}], "fit_ranges": []},
    ], {})
    np.testing.assert_allclose(first.y, np.array([1, 3, 5, 7, 9]) / 9)
    assert first.fit_ranges == []
    assert len(first.transformations) == 2


@pytest.mark.parametrize("invalid", [
    None, {}, [None], [{}], [{"unknown": True}], [{"clear_masks": "true"}],
    [{"mask_intervals": "0,1"}], [{"mask_intervals": [[0]]}], [{"fit_ranges": [[True, 1]]}],
    [{"unmask_intervals": [[0, float("inf")]]}], [{"transformations": {}}],
    [{"transformations": [None]}], [{"transformations": [{"operation": []}]}],
    [{"transformations": [{"operation": "exec", "formula": "print(1)"}]}],
    [{"transformations": [{"operation": "y_multiply", "value": True}]}],
    [{"transformations": [{"operation": "y_add", "value": float("nan")}]}],
    [{"transformations": [{"operation": "y_divide", "value": 0}]}],
    [{"transformations": [{"operation": "normalize_max", "value": 1}]}],
    [{"transformations": [{"operation": "custom_formula", "axis": "z", "formula": "z"}]}],
    [{"transformations": [{"operation": "custom_formula", "axis": "y", "formula": "x+y"}]}],
    [{"transformations": [{"operation": "custom_formula", "axis": "y", "formula": "${other}"}]}],
    [{"transformations": [{"operation": "custom_formula", "axis": "y", "formula": "y.__class__"}]}],
    [{"transformations": [{"operation": "column_formula", "target": "y", "formula": "import os"}]}],
])
def test_invalid_preprocessing_is_actionable(invalid):
    assert validate_preprocessing(invalid)


def test_all_shapes_and_selectors_validate_before_mutating(project):
    first = project.curves[0]
    before = first.y.copy()
    good = {"curves": "all", "transformations": [{"operation": "y_add", "value": 100}]}
    with pytest.raises(CurveMoleError, match="unknown field"):
        apply_preprocessing(project, [good, {"mask_intervals": [], "typo": True}], {})
    np.testing.assert_array_equal(first.y, before)
    with pytest.raises(CurveMoleError, match="Unknown curve"):
        apply_preprocessing(project, [good, {"curve": "absent", "clear_masks": True}], {})
    np.testing.assert_array_equal(first.y, before)
    assert not first.transformations


def test_read_only_project_is_not_modified(project):
    first = project.curves[0]
    project.read_only = True
    with pytest.raises(PermissionError, match="read-only"):
        apply_preprocessing(project, [{"transformations": [{"operation": "y_add", "value": 1}]}], {})
    assert not first.transformations
