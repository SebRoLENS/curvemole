from __future__ import annotations

from pathlib import Path

import numpy as np

from curvemole import Component, Curve, Project
from curvemole.core.export import export_bundle, tidy_dataframe, wide_dataframe
from curvemole.core.importers import ColumnMapping, ImportConfig, import_file


def test_import_shared_x_multiple_y_and_invalid_row(tmp_path: Path) -> None:
    path = tmp_path / "multiple.csv"
    path.write_text("x,a,b\n0,1,2\n1,bad,3\n2,4,5\n", encoding="utf-8")
    curves = import_file(path, ColumnMapping(x="x", y=["a", "b"]))
    assert [curve.name for curve in curves] == ["a", "b"]
    assert np.isnan(curves[0].y[1])
    assert len(curves[0]) == 3


def test_decimal_comma_semicolon_import(tmp_path: Path) -> None:
    path = tmp_path / "comma.dat"
    path.write_text("x;y\n0,0;1,5\n1,0;2,5\n", encoding="utf-8")
    curves = import_file(
        path,
        ColumnMapping(x="x", y=["y"]),
        ImportConfig(delimiter=";", decimal=",", header=True),
    )
    assert curves[0].x.tolist() == [0, 1]
    assert curves[0].y.tolist() == [1.5, 2.5]


def test_wide_and_tidy_profiles(gaussian_curve, tmp_path: Path) -> None:
    project = Project("Profiles")
    project.add_curve(gaussian_curve)
    project.model_for(gaussian_curve.id).add(
        Component.create("gaussian", initial={"area": 3, "center": 0.7, "sigma": 0.8})
    )
    wide = wide_dataframe(gaussian_curve, project.model_for(gaussian_curve.id))
    tidy = tidy_dataframe(project)
    assert "Total fit" in wide
    assert {"curve", "quantity", "x", "value", "masked"}.issubset(tidy.columns)


def test_bundle_preserves_unrelated_files_and_requires_confirmation(gaussian_curve, tmp_path: Path) -> None:
    project = Project("Bundle")
    project.add_curve(gaussian_curve)
    project.model_for(gaussian_curve.id).add(Component.create("gaussian"))
    root = tmp_path / "bundle"
    first = export_bundle(project, root)
    external = root / "my_notes.txt"
    external.write_text("do not touch", encoding="utf-8")
    try:
        export_bundle(project, root)
        raise AssertionError("Expected overwrite confirmation failure")
    except FileExistsError:
        pass
    second = export_bundle(project, root, overwrite=True)
    assert external.read_text(encoding="utf-8") == "do not touch"
    assert first.created
    assert second.updated or second.unchanged


def test_cross_spectrum_links_are_resolved_in_exports() -> None:
    x = np.linspace(-4, 4, 101)
    source = Curve("source", x, np.zeros_like(x))
    target = Curve("target", x, np.zeros_like(x))
    project = Project("Linked export")
    project.add_curve(source)
    project.add_curve(target)

    source_peak = Component.create(
        "gaussian", initial={"area": 2.0, "center": 1.25, "sigma": 0.7}
    )
    target_peak = Component.create(
        "gaussian", initial={"area": 3.0, "center": -2.0, "sigma": 0.9}
    )
    project.model_for(source.id).add(source_peak)
    project.model_for(target.id).add(target_peak)
    source_path = project.model_for(source.id).parameter_path(
        source.id, source_peak.id, "center"
    )
    target_path = project.model_for(target.id).parameter_path(
        target.id, target_peak.id, "center"
    )
    target_peak.parameters["center"].link = "${" + source_path + "}"

    resolved = project.resolved_parameter_values()
    tidy = tidy_dataframe(project)

    assert resolved[target_path] == resolved[source_path] == 1.25
    assert not tidy.empty
    assert np.isfinite(tidy["value"]).all()
