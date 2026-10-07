from __future__ import annotations

import numpy as np
import pytest

from curvemole.core.errors import DataValidationError
from curvemole.core.importers import (
    ColumnMapping,
    ImportConfig,
    ImportPreview,
    import_file,
    repeated_spectrum_mappings,
)


def test_shared_x_separate_names_and_independent_errors(tmp_path):
    path = tmp_path / "spectra.csv"
    path.write_text("x,A,errorA,B,plusB,minusB\n0,10,1,20,3,2\n1,11,2,21,4,3\n")
    mapping = ColumnMapping(as_separated_files=True, spectra=[
        ColumnMapping(x=0, y=[1], sigma_y=2),
        ColumnMapping(x=0, y=[3], error_y_plus=4, error_y_minus=5, error_confidence_level=.9),
    ])
    curves = import_file(path, mapping)
    assert [curve.name for curve in curves] == ["A", "B"]
    np.testing.assert_array_equal(curves[0].sigma_y, [1, 2])
    assert curves[0].error_y_plus is None
    assert curves[1].sigma_y is None
    np.testing.assert_array_equal(curves[1].error_y_plus, [3, 4])
    np.testing.assert_array_equal(curves[1].error_y_minus, [2, 3])
    assert curves[1].error_confidence_level == .9
    assert curves[0].metadata["import"]["sigma_y_column"] == 2
    preview = ImportPreview(path, ImportConfig(delimiter=",", header=True)).curves(mapping)
    for expected, actual in zip(curves, preview, strict=True):
        assert actual.name == expected.name
        np.testing.assert_array_equal(actual.x, expected.x)
        np.testing.assert_array_equal(actual.y, expected.y)


@pytest.mark.parametrize(("count", "ys", "kind", "expected"), [
    (5, 1, "none", [(0, 1), (2, 3)]),  # Trailing X is excluded.
    (6, 2, "none", [(0, 1), (0, 2), (3, 4), (3, 5)]),
    (6, 1, "sigma_y", [(0, 1), (3, 4)]),
    (10, 2, "sigma_y", [(0, 1), (0, 3), (5, 6), (5, 8)]),
    (8, 1, "asymmetric", [(0, 1), (4, 5)]),
    (7, 2, "asymmetric", [(0, 1), (0, 4)]),
])
def test_explicit_repeated_patterns(count, ys, kind, expected):
    spectra = repeated_spectrum_mappings(count, y_per_x=ys, error_kind=kind)
    assert [(s.x, s.y[0]) for s in spectra] == expected
    for spectrum in spectra:
        spectrum.validate()
        if kind == "sigma_y":
            assert spectrum.sigma_y == spectrum.y[0] + 1
        elif kind == "asymmetric":
            assert spectrum.error_y_plus == spectrum.y[0] + 1
            assert spectrum.error_y_minus == spectrum.y[0] + 2


def test_custom_different_axes_positional_batch_and_no_header(tmp_path):
    mapping = ColumnMapping(as_separated_files=True, spectra=[
        ColumnMapping(x=0, y=[1], sigma_y=2),
        ColumnMapping(x=3, y=[4], weights=5),
    ])
    for header in ("x,A,e,x2,B,w\n", "otherX,C,e,otherX2,D,w\n", ""):
        path = tmp_path / "data.csv"
        path.write_text(header + "0,10,1,5,20,2\n1,11,2,6,21,3\n")
        curves = import_file(path, mapping)
        assert [c.name for c in curves] == (
            ["A", "B"] if header.startswith("x,") else ["C", "D"] if header else
            ["Y — column 2", "Y — column 5"])
        np.testing.assert_array_equal(curves[1].x, [5, 6])
        np.testing.assert_array_equal(curves[1].weights, [2, 3])


@pytest.mark.parametrize("spectra", [
    [ColumnMapping(x=0, y=[1]), ColumnMapping(x=2, y=[1])],
    [ColumnMapping(x=0, y=[1], sigma_y=2), ColumnMapping(x=0, y=[2])],
    [ColumnMapping(x=0, y=[1]), ColumnMapping(x=1, y=[2])],
    [ColumnMapping(x=0, y=[1], error_y_plus=2)],
    [ColumnMapping(x=0, y=[1], sigma_y=20)],
])
def test_invalid_separated_mappings_rejected(tmp_path, spectra):
    path = tmp_path / "data.csv"
    path.write_text("x,a,b\n0,1,2\n1,2,3\n")
    with pytest.raises(DataValidationError):
        import_file(path, ColumnMapping(as_separated_files=True, spectra=spectra))
