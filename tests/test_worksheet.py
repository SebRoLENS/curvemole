from __future__ import annotations

import gc
import weakref

import numpy as np
import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

from curvemole import Curve
from curvemole.core.calculator import apply_scalar
from curvemole.gui.panels import WorksheetPanel


@pytest.fixture
def worksheet():
    app = QApplication.instance() or QApplication([])
    panel = WorksheetPanel()
    yield panel, panel.table.model()
    panel.close()
    panel.deleteLater()
    app.processEvents()


def test_worksheet_shows_current_values_errors_weights_and_combined_masks(worksheet):
    panel, model = worksheet
    curve = Curve("Data", [0., 1., 2.], [2., 3., 4.],
                  sigma_y=[.1, .2, .3], weights=[1., 2., 3.])
    curve.mask_point(1.)
    curve.fit_ranges = [(0., 1.)]
    apply_scalar(curve, "y_multiply", 2)
    panel.set_curve(curve)
    assert model.rowCount() == 3
    assert model.columnCount() == 5
    assert [model.headerData(col, Qt.Orientation.Horizontal) for col in range(5)] == [
        "x", "y", "sigma_y", "weight", "masked",
    ]
    assert [[model.data(model.index(row, column)) for column in range(5)] for row in range(3)] == [
        ["0.0", "4.0", "0.2", "1.0", "False"],
        ["1.0", "6.0", "0.4", "2.0", "True"],
        ["2.0", "8.0", "0.6", "3.0", "True"],
    ]
    assert model.headerData(2, Qt.Orientation.Vertical) == "3"
    assert not model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsEditable


def test_worksheet_supports_asymmetric_confidence_errors_and_missing_fields(worksheet):
    panel, model = worksheet
    curve = Curve("Intervals", [0., 1.], [4., 5.], error_y_minus=[1., 2.],
                  error_y_plus=[3., 4.], error_confidence_level=.9)
    panel.set_curve(curve)
    assert model.columnCount() == 7
    assert [model.data(model.index(1, col)) for col in range(7)] == [
        "1.0", "5.0", "2.0", "4.0", "90.0", "", "False",
    ]
    curve = Curve("Plain", [0., 1.], [1., 2.])
    panel.set_curve(curve)
    assert model.columnCount() == 5
    assert [model.data(model.index(0, col)) for col in range(5)] == [
        "0.0", "1.0", "", "", "False",
    ]


def test_large_worksheet_keeps_original_arrays_and_formats_requested_rows_only(worksheet):
    panel, model = worksheet
    curve = Curve("Large", np.arange(200_000.), np.arange(200_000.) * 2)
    x_ref = weakref.ref(curve.x.base)
    y_ref = weakref.ref(curve.y.base)
    panel.set_curve(curve)
    assert model.rowCount() == 100_000
    assert panel.label.text() == "Large — 100000/200000 rows shown"
    assert model.data(model.index(99_999, 1)) == "199998.0"
    assert not model.index(100_000, 0).isValid()
    assert model.rowCount(model.index(0, 0)) == 0
    assert model.columnCount(model.index(0, 0)) == 0
    assert model.data(QModelIndex()) is None
    assert model.data(model.index(0, 0), Qt.ItemDataRole.EditRole) is None
    del curve
    gc.collect()
    # The view holds source arrays, rather than generating strings for all rows.
    assert x_ref() is not None and y_ref() is not None
    panel.set_curve(None)
    gc.collect()
    assert x_ref() is None and y_ref() is None
    assert model.rowCount() == 0


def test_worksheet_refresh_replaces_stale_arrays_after_data_transformation(worksheet):
    panel, model = worksheet
    curve = Curve("Refresh", [0., 1., 2.], [1., 2., 3.])
    panel.set_curve(curve, maximum_rows=2)
    assert model.rowCount() == 2
    assert model.data(model.index(1, 1)) == "2.0"
    apply_scalar(curve, "y_add", 5)
    panel.set_curve(curve, maximum_rows=1)
    assert model.rowCount() == 1
    assert model.data(model.index(0, 1)) == "6.0"
