from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from curvemole import Component, Curve, Fitter, Project
from curvemole.core.data import CurveState, Series
from curvemole.core.errors import CurveMoleError
from curvemole.core.export import (
    BundleExportSelection,
    analysis_dataframes,
    export_bundle,
    export_function_parameters,
)
from curvemole.core.serialization import load_project
from curvemole.core.spectrum_export import export_spectra


def test_default_export_is_a_complete_analysis_bundle(gaussian_curve, tmp_path: Path) -> None:
    project = Project("Default export")
    project.add_curve(gaussian_curve)
    component = Component.create(
        "gaussian",
        initial={"area": 3.0, "center": 0.7, "sigma": 0.8},
    )
    component.is_background = True
    project.model_for(gaussian_curve.id).add(component)

    root = tmp_path / "export"
    summary = export_bundle(project, root)

    assert summary.created
    assert all(BundleExportSelection().to_dict().values())
    assert (root / "Default_export.fitproj").is_file()
    assert (root / "function_parameters.csv").is_file()
    assert (root / "python/observations.csv").is_file()
    assert (root / "python/components.csv").is_file()
    assert (root / "python/curves.csv").is_file()
    assert (root / "python/replot.py").is_file()
    assert (root / "python/results.json").is_file()
    assert (root / "report/summary.pdf").is_file()
    assert (root / "summary_report.html").is_file()
    assert (root / "report/full_reproducibility.html").is_file()
    assert (root / "laboratory_notebook.txt").is_file()
    assert len(list((root / "figures/png").glob("*.png"))) == 1
    assert len(list((root / "figures/svg").glob("*.svg"))) == 1
    assert len(list((root / "figures/pdf").glob("*.pdf"))) == 1
    assert len(list((root / "models").glob("*.fitmodel"))) == 1
    assert len(list((root / "spectra").iterdir())) == 1
    assert len(list((root / "report").glob("*.pdf"))) == 1
    assert not (root / "python/data_tidy.csv").exists()
    assert not (root / "uncertainty").exists()
    assert not (root / ".curvemole-export.json").exists()
    manifest = json.loads((root / "manifest.json").read_text())
    assert {item["path"] for item in manifest["files"]} == {
        path.relative_to(root).as_posix() for path in summary.created
    }
    readme = (root / "README.txt").read_text()
    for extension in ("png", "svg", "pdf"):
        assert f"figures/{extension}/*.{extension} (1 file)" in readme
    assert "manifest.json contains its exact file inventory" in readme
    assert "point_index" in readme and "not a historical fit-inclusion flag" in readme
    assert "CURRENT model" in readme and "LAST fit" in readme
    assert "data_tidy.csv" not in readme

    frame = pd.read_csv(root / "fit_results.csv")
    assert {
        "curve",
        "curve_id",
        "component",
        "function",
        "function_id",
        "enabled",
        "is_background",
        "composition",
        "parameter",
        "parameter_path",
        "value",
        "standard_error",
        "human_readable",
    }.issubset(frame.columns)
    assert set(frame["curve"]) == {gaussian_curve.name}
    assert set(frame["function_id"]) == {"gaussian"}
    assert frame["is_background"].all()
    reopened = load_project(root / "Default_export.fitproj")
    assert reopened.export_config == project.export_config
    export_bundle(reopened, root, overwrite=True, selection=BundleExportSelection.none(fit_results=True))


def test_optional_export_creates_only_needed_directories(gaussian_curve, tmp_path: Path) -> None:
    project = Project("Selective export")
    project.add_curve(gaussian_curve)
    project.model_for(gaussian_curve.id).add(Component.create("gaussian"))
    selection = BundleExportSelection.none(
        tidy_table=True,
        main_plot_svg=True,
    )

    root = tmp_path / "export"
    export_bundle(project, root, selection=selection)

    assert (root / "python" / "observations.csv").is_file()
    assert len(list((root / "figures/svg").glob("*.svg"))) == 1
    assert {path.name for path in (root / "figures").iterdir()} == {"svg"}
    assert not (root / "data").exists()
    assert not (root / "report").exists()
    assert not (root / "uncertainty").exists()
    assert not (root / "diagnostics").exists()
    assert not (root / "fit_results.csv").exists()


def test_unavailable_optional_output_does_not_create_empty_folder(gaussian_curve, tmp_path: Path) -> None:
    project = Project("No uncertainty")
    project.add_curve(gaussian_curve)
    selection = BundleExportSelection.none(uncertainty=True)
    root = tmp_path / "export"

    with pytest.raises(CurveMoleError, match="no available data"):
        export_bundle(project, root, selection=selection)

    assert not root.exists()


def test_explicit_fit_results_only_export_remains_available(gaussian_curve, tmp_path):
    project = Project()
    project.add_curve(gaussian_curve)
    project.model_for(gaussian_curve.id).add(Component.create("gaussian"))
    summary = export_bundle(project, tmp_path, selection=BundleExportSelection.none(fit_results=True))
    assert [path.name for path in summary.created] == ["fit_results.csv"]


def test_duplicate_names_have_separate_files_and_indexed_source_metadata(tmp_path):
    project = Project("Duplicates")
    for index in range(2):
        curve = Curve("same/name", [0., 1., 1.], [2., 3., 4.],
                      source=f"/source/{index}.csv", x_label="Time", x_unit="s", y_unit="mV")
        project.add_series(Series(f"Series {index}", curves=[curve]))
        project.model_for(curve.id).add(Component.create("constant"))
    root = tmp_path / "bundle"
    export_bundle(project, root)
    index = pd.read_csv(root / "index.csv")
    assert index.curve.tolist() == ["same/name", "same/name"]
    assert index.series.tolist() == ["Series 0", "Series 1"]
    assert index.x_unit.tolist() == ["s", "s"]
    for column in ("spectrum_file", "wide_file", "png_file", "svg_file", "pdf_file", "model_file"):
        assert index[column].nunique() == 2
        assert all((root / path).is_file() for path in index[column])
    for row in index.itertuples(index=False):
        for extension in ("png", "svg", "pdf"):
            relative = Path(getattr(row, f"{extension}_file"))
            assert relative.parent == Path("figures") / extension
            assert relative.name == f"{row.file_stem}.{extension}"
    assert {path.name for path in (root / "figures").iterdir()} == {"png", "svg", "pdf"}
    assert {path.name for path in (root / "report").glob("*.pdf")} == {"summary.pdf"}
    assert not (root / "figures/main_plot.svg").exists()
    assert not (root / "main_plot.png").exists()

    quick_directory = tmp_path / "quick_spectra"
    quick_files = export_spectra(project, quick_directory, [curve.id for curve in project.curves])
    for quick_file, bundled_path in zip(quick_files, index.spectrum_file, strict=True):
        assert quick_file.read_bytes() == (root / bundled_path).read_bytes()
    quick_parameters = export_function_parameters(project, tmp_path / "quick_parameters.csv")
    assert quick_parameters.read_bytes() == (root / "function_parameters.csv").read_bytes()


def test_python_tables_keep_repeated_x_and_duplicate_components_distinct(tmp_path):
    project = Project("Python schema")
    curve = Curve("scan", [1., 1., 2.], [3., 4., 5.], sigma_y=[.1, .2, .3], x_unit="s", y_unit="a.u.")
    project.add_curve(curve)
    model = project.model_for(curve.id)
    for offset in (1., 2.):
        model.add(Component.create("constant", name="Repeated name", initial={"offset": offset}))
    curve.masks[curve.active_mask].excluded[1] = True
    observations, components, metadata = analysis_dataframes(project)
    assert len(observations) == 3 and len(components) == 6
    assert not observations.duplicated(["curve_id", "point_index"]).any()
    assert not components.duplicated(["curve_id", "point_index", "component_id"]).any()
    assert components.component_id.nunique() == 2
    assert components.component.nunique() == 1
    assert observations.original_row_index.tolist() == [0, 1, 2]
    assert observations.masked.tolist() == [False, True, False]
    assert observations.x.tolist() == [1., 1., 2.]
    np.testing.assert_allclose(observations.model_y, 3.)
    np.testing.assert_allclose(observations.residual, [0., 1., 2.])
    assert metadata.iloc[0].x_unit == "s"
    assert metadata.iloc[0].state == CurveState.NOT_FITTED
    root = tmp_path / "bundle"
    export_bundle(project, root, delimiter=";", selection=BundleExportSelection.none(tidy_table=True))
    subprocess.run([sys.executable, str(root / "python/replot.py")], check=True, timeout=60)
    replotted = root / "python/replotted"
    assert {path.name for path in replotted.iterdir()} == {"svg", "png"}
    for extension in ("svg", "png"):
        figures = list((replotted / extension).glob(f"*.{extension}"))
        assert len(figures) == 1
        assert figures[0].stem == metadata.iloc[0].file_stem


def test_bundle_retains_per_curve_fit_records_and_labeled_covariances(gaussian_curve, tmp_path):
    project = Project("Recorded fit")
    project.add_curve(gaussian_curve)
    model = project.model_for(gaussian_curve.id)
    model.add(Component.create("gaussian", initial={"area": 3., "center": .7, "sigma": .8}))
    result = Fitter().fit_single(gaussian_curve, model)
    project.results["last_fit"] = result
    project.results["fit_by_curve"] = {gaussian_curve.id: {"baseline": result}}
    root = tmp_path / "bundle"
    export_bundle(project, root, selection=BundleExportSelection.none(
        results_json=True, parameter_covariances=True, uncertainty=True, fit_settings=True,
    ))
    payload = json.loads((root / "python/results.json").read_text())
    assert payload["result"]["timestamp"] == result.timestamp
    assert payload["fit_by_curve"][gaussian_curve.id]["baseline"]["timestamp"] == result.timestamp
    covariance = pd.read_csv(root / "uncertainty/covariance.csv", index_col=0)
    assert covariance.columns.tolist() == result.free_parameter_paths
    assert covariance.index.tolist() == result.free_parameter_paths
    np.testing.assert_allclose(covariance.to_numpy(), result.covariance)
    assert (root / "function_parameters_covariance/index.csv").is_file()
    with pytest.raises(FileExistsError):
        export_bundle(project, root, selection=BundleExportSelection.none(parameter_covariances=True))


def test_current_view_is_optional_and_its_files_are_preflighted(tmp_path, monkeypatch):
    from curvemole.core import figure_export

    project = Project()
    selection = BundleExportSelection.none(current_view=True)
    with pytest.raises(CurveMoleError, match="no available data"):
        export_bundle(project, tmp_path / "no_view", selection=selection)
    snapshot = object()
    calls = []

    def save_snapshot(captured, destination):
        assert captured is snapshot
        calls.append(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("snapshot")

    monkeypatch.setattr(figure_export, "export_plot_snapshot", save_snapshot)
    root = tmp_path / "bundle"
    summary = export_bundle(project, root, selection=selection, current_view=snapshot)
    assert {path.relative_to(root).as_posix() for path in summary.created} == {
        "figures/png/current_view.png", "figures/svg/current_view.svg", "figures/pdf/current_view.pdf"}
    assert not (root / "report").exists()
    with pytest.raises(FileExistsError):
        export_bundle(project, root, selection=selection, current_view=snapshot)
    assert len(calls) == 3
    update = export_bundle(project, root, selection=selection, current_view=snapshot, overwrite=True)
    assert len(update.unchanged) == 3
    assert not update.created and not update.updated
    assert len(calls) == 6


@pytest.mark.parametrize("extension", ["png", "svg", "pdf"])
def test_current_view_checks_every_format_before_writing(tmp_path, monkeypatch, extension):
    from curvemole.core import figure_export

    project = Project()
    selection = BundleExportSelection.none(current_view=True)
    root = tmp_path / "bundle"
    occupied = root / "figures" / extension / f"current_view.{extension}"
    occupied.parent.mkdir(parents=True)
    occupied.write_text("unrelated figure")
    calls = []
    monkeypatch.setattr(figure_export, "export_plot_snapshot", lambda *args: calls.append(args))

    with pytest.raises(FileExistsError, match="overwrite existing files"):
        export_bundle(project, root, selection=selection, current_view=object())

    assert not calls
    assert [path for path in root.rglob("*") if path.is_file()] == [occupied]
    assert occupied.read_text() == "unrelated figure"


def test_data_only_fit_results_have_readable_empty_schema(tmp_path):
    project = Project("No model")
    project.add_curve(Curve("data", [0., 1.], [1., 2.]))
    export_bundle(project, tmp_path, selection=BundleExportSelection.none(fit_results=True))
    table = pd.read_csv(tmp_path / "fit_results.csv")
    assert table.empty
    assert {"curve_id", "component_id", "parameter_path", "value", "unit"}.issubset(table.columns)
