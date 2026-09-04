from __future__ import annotations

from pathlib import Path

from curvemole.core.importers import ColumnMapping, ImportConfig, import_file, inspect_file


def test_inspection_accepts_valid_data_with_unknown_extension(tmp_path: Path) -> None:
    path = tmp_path / "spectrum.vendorformat"
    path.write_text("x y\n0 1\n1 2\n2 3\n", encoding="utf-8")

    inspection = inspect_file(path)

    assert inspection.columns == ["x", "y"]
    assert inspection.config.header is True


def test_leading_metadata_rows_are_detected_for_preview(tmp_path: Path) -> None:
    path = tmp_path / "spectrum.xy"
    path.write_text(
        "Instrument: CurveLab\n"
        "Acquisition: test\n"
        "x y\n"
        "0 1\n"
        "1 2\n"
        "2 3\n",
        encoding="utf-8",
    )

    inspection = inspect_file(path)

    assert inspection.config.skip_rows == 2
    assert inspection.config.header is True
    assert inspection.columns == ["x", "y"]


def test_explicit_skip_rows_are_applied_to_import(tmp_path: Path) -> None:
    path = tmp_path / "spectrum.xy"
    path.write_text(
        "instrument header\n"
        "second header\n"
        "x y\n"
        "0 1\n"
        "1 2\n",
        encoding="utf-8",
    )

    curves = import_file(
        path,
        ColumnMapping(x="x", y=["y"]),
        ImportConfig(delimiter=None, header=True, skip_rows=2),
    )

    assert curves[0].x.tolist() == [0.0, 1.0]
    assert curves[0].y.tolist() == [1.0, 2.0]
    assert curves[0].metadata["import"]["skip_rows"] == 2


def test_decimal_comma_detection_still_works_with_arbitrary_extension(
    tmp_path: Path,
) -> None:
    path = tmp_path / "measurement.xy"
    path.write_text("x;y\n0,0;1,5\n1,0;2,5\n", encoding="utf-8")

    inspection = inspect_file(path)

    assert inspection.config.delimiter == ";"
    assert inspection.config.decimal == ","
    assert inspection.columns == ["x", "y"]
