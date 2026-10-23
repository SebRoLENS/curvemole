from __future__ import annotations

from curvemole import Project
from curvemole.core.export import (
    BundleExportSelection,
    _bundle_file_description,
    _bundle_readme,
    _bundle_readme_inventory,
    _bundle_readme_table,
    export_bundle,
)


def test_readme_groups_many_spectra_by_format_and_lists_snapshots_separately() -> None:
    paths = [
        f"figures/{extension}/Spectrum_{number:03d}.{extension}"
        for extension in ("png", "svg", "pdf")
        for number in range(98)
    ] + [
        f"figures/{extension}/current_view.{extension}"
        for extension in ("png", "svg", "pdf")
    ] + ["index.csv", "README.txt", "manifest.json", "report/summary.pdf"]

    readme = _bundle_readme(Project("Many spectra"), paths, ",")
    contents = readme.split("Using these files", 1)[0]

    assert "File or folder" in contents and "What it contains" in contents
    for extension in ("png", "svg", "pdf"):
        assert f"figures/{extension}/*.{extension} (98 files)" in contents
        assert f"figures/{extension}/current_view.{extension}" in contents
    assert "Snapshot of the visible plot" in contents
    assert "Spectrum_000" not in readme
    assert "report/summary.pdf" in contents
    assert "Combined PDF report" in contents
    assert contents.index("Figures\n") < contents.index("Project and Python\n")
    assert "manifest.json contains its exact file inventory" in readme


def test_partial_bundle_readme_only_directs_readers_to_available_files(gaussian_curve, tmp_path) -> None:
    project = Project("Small export")
    project.add_curve(gaussian_curve)
    export_bundle(project, tmp_path, selection=BundleExportSelection.none(fit_results=True, readme=True))

    readme = (tmp_path / "README.txt").read_text()

    assert "fit_results.csv" in readme
    assert ".fitproj" not in readme
    assert "index.csv" not in readme
    assert "figures/" not in readme
    assert "python/" not in readme
    assert "Understanding the Python tables" not in readme
    assert "fit_results.csv" in readme.split("Using these files", 1)[0]


def test_readme_explains_point_keys_units_masks_and_current_vs_recorded_fit() -> None:
    paths = [
        "python/observations.csv", "python/components.csv", "python/curves.csv",
        "python/replot.py", "python/results.json", "fit_results.csv",
        "uncertainty/covariance.csv", "README.txt", "manifest.json",
    ]

    readme = " ".join(_bundle_readme(Project("Python export"), paths, ";").split())

    assert "CURRENT model" in readme and "LAST fit" in readme
    assert "(curve_id, point_index)" in readme
    assert "original_row_index" in readme
    assert "never join on x alone" in readme
    assert "not a historical fit-inclusion flag" in readme
    assert "weights_are_inverse_variance=true" in readme
    assert "confidence-interval half-widths" in readme
    assert "Correlations are dimensionless" in readme
    assert "python/replotted/png/" in readme and "python/replotted/svg/" in readme
    assert "data_tidy.csv" not in readme


def test_covariance_guide_is_not_hidden_in_matrix_file_group() -> None:
    inventory = _bundle_readme_inventory([
        "function_parameters_covariance/index.csv",
        "function_parameters_covariance/001_fit_covariance.csv",
        "function_parameters_covariance/002_analysis_residual_bootstrap.csv",
        "fit_results.csv",
    ])

    assert len(inventory) == 1
    category, rows = inventory[0]
    assert category == "Fit parameters and uncertainty"
    assert [name for name, _ in rows] == [
        "fit_results.csv",
        "function_parameters_covariance/[0-9]*.csv (2 files)",
        "function_parameters_covariance/index.csv",
    ]
    assert "Guide to the covariance files" in rows[2][1]


def test_names_and_descriptions_cannot_break_plain_text_table() -> None:
    table = _bundle_readme_table([
        ("folder/left|right\nnext\tcolumn.csv", "Contains | a tab\tand a line\nbreak."),
        ("x" * 110 + ".csv", "A " * 100),
    ])
    readme = _bundle_readme(Project("Project\nInjected | heading\x1b"), ["README.txt"], ",")

    assert "left\\u007cright\\nnext\\tcolumn.csv" in table
    assert "Contains \\u007c a tab\\tand a line\\nbreak." in table
    assert all(line.count("|") == 1 for line in table.splitlines() if "|" in line)
    assert all(len(line) <= 117 for line in table.splitlines())
    assert readme.splitlines()[0].endswith(r"Project\nInjected \u007c heading\u001b")


def test_curve_named_current_view_is_not_described_as_screen_capture() -> None:
    assert "Snapshot" in _bundle_file_description("figures/png/current_view.png")
    assert "PNG images" in _bundle_file_description("figures/png/current_view__abcdef.png")
    assert "Open in CurveMole" in _bundle_file_description("current_view.fitproj")


def test_project_names_do_not_determine_inventory_category() -> None:
    inventory = _bundle_readme_inventory([
        "fit_experiment.fitproj", "function_parameters_experiment.fitproj", "current_view.fitproj",
    ])

    assert len(inventory) == 1
    assert inventory[0][0] == "Project and Python"
    assert all("Open in CurveMole" in description for _, description in inventory[0][1])


def test_snapshot_only_readme_describes_captured_display_separately() -> None:
    readme = _bundle_readme(Project("Screen"), ["figures/png/current_view.png", "README.txt"], ",")

    assert "Snapshot of the visible plot" in readme
    assert "figures/svg" not in readme and "figures/pdf" not in readme
    assert "Background subtraction is not applied" not in readme
    assert "Current model and recorded fits" not in readme
