import math

import numpy as np

from curvemole import Component, Curve, Fitter, Project, Series
from curvemole.core.serialization import load_project, save_project


def test_open_ranges_and_infinite_bounds_survive_save_and_load(tmp_path):
    curve = Curve("c", np.linspace(0, 10, 11), np.exp(-(np.linspace(0, 10, 11) - 4) ** 2) + 0.1)
    curve.fit_ranges = [(-math.inf, 8.0)]
    curve.mask_interval(9.0, math.inf)
    project = Project("p")
    project.add_series(Series("s", [curve]))
    project.model_for(curve.id).add(Component.create("gaussian", initial={"center": 4}))
    project.results["last_fit"] = Fitter().fit_single(curve, project.model_for(curve.id))

    loaded = load_project(save_project(project, tmp_path / "a.fitproj"))
    restored = loaded.curves[0]
    assert restored.fit_ranges == [(-math.inf, 8.0)]
    assert restored.masks["Default"].ranges == [(9.0, math.inf)]
    np.testing.assert_array_equal(restored.effective_mask, curve.effective_mask)
    for estimate in loaded.results["last_fit"].parameters.values():
        assert isinstance(estimate.minimum, float) and isinstance(estimate.maximum, float)
