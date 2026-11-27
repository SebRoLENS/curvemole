import numpy as np

from curvemole import Component, Curve, Project, Series
from curvemole.core.data import Transformation


def _project(target_x):
    x = np.arange(0., 200.)
    project = Project()
    project.add_series(Series("s", [Curve("src", x, np.ones_like(x)), Curve("dst", target_x, np.ones_like(target_x))]))
    source, target = project.curves
    project.add_component(source.id, Component.create("gaussian"))
    return project, source, target


def test_copied_masks_follow_x_transformations():
    project, source, target = _project(np.arange(0., 300.))
    source.mask_interval(10, 20)
    source.apply_transformation(Transformation("x_add", {"value": 100.0}))
    project.copy_fit(source.id, [target.id], masks=True)
    np.testing.assert_array_equal(target.x[target.effective_mask], np.arange(110., 121.))


def test_partial_unmask_keeps_the_remaining_masked_interval():
    project, source, target = _project(np.arange(0., 200.) + 0.5)
    source.mask_interval(10, 30)
    source.unmask_interval(25, 40)
    assert source.masks["Default"].ranges == [(10.0, 24.0)]
    project.copy_fit(source.id, [target.id], masks=True)
    np.testing.assert_array_equal(target.x[target.effective_mask], np.arange(10.5, 24.))


def test_current_ranges_report_separate_runs_in_ascending_x():
    curve = Curve("c", np.arange(10.)[::-1], np.zeros(10))
    curve.mask_interval(1, 2)
    curve.mask_interval(6, 7)
    assert curve.masks["Default"].current_ranges(curve.x) == [(1.0, 2.0), (6.0, 7.0)]
