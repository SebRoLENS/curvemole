from __future__ import annotations

from pathlib import Path

import pandas as pd

from curvemole import Component, Project
from curvemole.core.export import BundleExportSelection, export_bundle


def test_default_export_writes_only_fit_results(gaussian_curve, tmp_path: Path) -> None:
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

    assert [path.name for path in summary.created] == ["fit_results.csv"]
    assert sorted(path.name for path in root.iterdir()) == ["fit_results.csv"]
    assert not (root / ".curvemole-export.json").exists()

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


def test_optional_export_creates_only_needed_directories(gaussian_curve, tmp_path: Path) -> None:
    project = Project("Selective export")
    project.add_curve(gaussian_curve)
    project.model_for(gaussian_curve.id).add(Component.create("gaussian"))
    selection = BundleExportSelection(
        fit_results=False,
        tidy_table=True,
        main_plot_svg=True,
    )

    root = tmp_path / "export"
    export_bundle(project, root, selection=selection)

    assert (root / "python" / "data_tidy.csv").is_file()
    assert (root / "figures" / "main_plot.svg").is_file()
    assert not (root / "data").exists()
    assert not (root / "report").exists()
    assert not (root / "uncertainty").exists()
    assert not (root / "diagnostics").exists()
    assert not (root / "fit_results.csv").exists()


def test_unavailable_optional_output_does_not_create_empty_folder(gaussian_curve, tmp_path: Path) -> None:
    project = Project("No uncertainty")
    project.add_curve(gaussian_curve)
    selection = BundleExportSelection(fit_results=False, uncertainty=True)
    root = tmp_path / "export"

    try:
        export_bundle(project, root, selection=selection)
        raise AssertionError("Expected unavailable-output error")
    except Exception as exc:
        assert "no available data" in str(exc).lower()

    assert not root.exists()
