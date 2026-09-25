from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from curvemole import Component, Curve, Project
from curvemole.core.data import CurveState
from curvemole.core.export import (
    _normalise_owned_path,
    export_bundle,
    export_function_parameters,
    tidy_dataframe,
    wide_dataframe,
)
from curvemole.core.importers import ColumnMapping, ImportConfig, import_file


def test_import_shared_x_multiple_y_and_invalid_row(tmp_path: Path) -> None:
    path = tmp_path / "multiple.csv"
    path.write_text("x,a,b\n0,1,2\n1,bad,3\n2,4,5\n", encoding="utf-8")
    curves = import_file(path, ColumnMapping(x="x", y=["a", "b"]))
    assert [curve.name for curve in curves] == ["multiple", "multiple"]
    assert [curve.y_label for curve in curves] == ["a", "b"]
    assert [curve.metadata["import"]["y_column"] for curve in curves] == ["a", "b"]
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
    assert curves[0].name == "comma"
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


def test_function_parameter_matrix_aligns_names_and_fit_errors(tmp_path: Path) -> None:
    x = np.linspace(-2, 2, 11)
    curves = [Curve(name, x, np.zeros_like(x)) for name in ("scan 1", "scan 2", "unfitted")]
    project = Project()
    for curve in curves:
        project.add_curve(curve)
    for curve, order in zip(curves, (("Gaussian 1", "Voigt 1"),
                                     ("Voigt 1", "Gaussian 1"), ("Gaussian 1",)), strict=True):
        for label in order:
            function = "voigt" if label.startswith("Voigt") else "gaussian"
            component = Component.create(function, name=label)
            component.parameters["center"].value = 1.25 if curve is curves[0] else 2.5
            component.parameters["center"].standard_error = .03
            project.model_for(curve.id).add(component)
    curves[0].state = curves[1].state = CurveState.FITTED
    output = export_function_parameters(project, tmp_path / "parameters.csv")
    with output.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0][0] == "Spectrum" and rows[1][0] == ""
    center = next(i for i, pair in enumerate(zip(rows[0], rows[1], strict=True))
                  if pair == ("Gaussian 1", "center"))
    assert (rows[0][center + 1], rows[1][center + 1]) == ("Gaussian 1", "center_err")
    assert rows[2][0] == "scan 1" and rows[2][center:center + 2] == ["1.25", "0.03"]
    assert rows[3][0] == "scan 2" and rows[3][center:center + 2] == ["2.5", "0.03"]
    assert rows[4][0] == "unfitted" and rows[4][center:center + 2] == ["", ""]
    assert len(rows[0]) == len(rows[1]) == len(rows[2]) == len(rows[3]) == len(rows[4])


def test_file_menu_exports_function_parameters(gaussian_curve, tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication, QFileDialog

    from curvemole.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    project = Project()
    project.add_curve(gaussian_curve)
    project.model_for(gaussian_curve.id).add(Component.create("gaussian", name="Gaussian 1"))
    gaussian_curve.state = CurveState.FITTED
    output = tmp_path / "functions.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(output), "CSV files (*.csv)"))
    window = MainWindow(project)
    file_menu = next(action.menu() for action in window.menuBar().actions()
                     if action.text().replace("&", "") == "File")
    assert window.export_parameters_action in file_menu.actions()
    window.export_parameters_action.trigger()
    assert output.exists()
    with output.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0][1:3] == [project.models[gaussian_curve.id].components[0].name] * 2
    assert rows[1][1:3] == ["area", "area_err"]
    project.dirty = False
    window.close()
    app.processEvents()


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


def test_export_manifest_paths_are_portable_between_operating_systems() -> None:
    assert _normalise_owned_path(r"python\data_tidy.csv") == "python/data_tidy.csv"


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
