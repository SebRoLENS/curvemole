import numpy as np

from curvemole.core.data import Curve
from curvemole.core.export import wide_dataframe


def test_wide_export_includes_x_uncertainty():
    curve = Curve("c", [0., 1., 2.], [1., 2., 3.], sigma_x=[0.1, 0.2, 0.3], sigma_y=[1., 1., 1.])
    frame = wide_dataframe(curve)
    np.testing.assert_array_equal(frame["sigma_x"], [0.1, 0.2, 0.3])
    assert list(frame.columns).index("sigma_x") < list(frame.columns).index("sigma_y")
