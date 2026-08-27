from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not find expected text for {label}")
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one occurrence for {label}, found {text.count(old)}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"Could not find start marker for {label}")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"Could not find end marker for {label}")
    return text[:start_index] + replacement + text[end_index:]


# --- core exporter ---------------------------------------------------------
path = Path("src/curvemole/core/export.py")
text = path.read_text(encoding="utf-8")

export_summary_marker = """\n\n@dataclass(slots=True)\nclass ExportSummary:\n"""
selection_class = '''

@dataclass(slots=True)
class BundleExportSelection:
    """User-selectable contents for an analysis export."""

    fit_results: bool = True
    wide_tables: bool = False
    tidy_table: bool = False
    results_json: bool = False
    fitmodel: bool = False
    project_copy: bool = False
    main_plot_png: bool = False
    main_plot_svg: bool = False
    html_summary: bool = False
    html_reproducibility: bool = False
    pdf_summary: bool = False
    uncertainty: bool = False
    diagnostics: bool = False
    readme: bool = False

    def any_selected(self) -> bool:
        return any(self.to_dict().values())

    def to_dict(self) -> dict[str, bool]:
        return {
            "fit_results": self.fit_results,
            "wide_tables": self.wide_tables,
            "tidy_table": self.tidy_table,
            "results_json": self.results_json,
            "fitmodel": self.fitmodel,
            "project_copy": self.project_copy,
            "main_plot_png": self.main_plot_png,
            "main_plot_svg": self.main_plot_svg,
            "html_summary": self.html_summary,
            "html_reproducibility": self.html_reproducibility,
            "pdf_summary": self.pdf_summary,
            "uncertainty": self.uncertainty,
            "diagnostics": self.diagnostics,
            "readme": self.readme,
        }
'''
text = replace_once(text, export_summary_marker, selection_class + export_summary_marker, "BundleExportSelection")

parameter_rows_old = '''                            "component_id": component.id,
                            "function": definition.display_name,
                            "parameter": name,
                            "value": value,
'''
parameter_rows_new = '''                            "component_id": component.id,
                            "function": definition.display_name,
                            "function_id": component.function_id,
                            "enabled": component.enabled,
                            "is_background": component.is_background,
                            "composition": component.operator,
                            "parameter": name,
                            "parameter_path": path,
                            "value": value,
'''
text = replace_once(text, parameter_rows_old, parameter_rows_new, "fit result columns")

new_bundle = '''def export_bundle(
    project: Project,
    directory: str | Path,
    *,
    result: FitResult | None = None,
    delimiter: str = ",",
    versioned: bool = False,
    overwrite: bool = False,
    include_uncertainty_samples: bool = True,
    selection: BundleExportSelection | None = None,
) -> ExportSummary:
    selection = selection or BundleExportSelection()
    if not selection.any_selected():
        raise CurveMoleError("Select at least one item to export.")

    root = Path(directory)
    if versioned:
        root = root / datetime.now(UTC).strftime("export-%Y%m%d-%H%M%S")

    registry = _registry_for_project(project)
    planned = _bundle_paths(project, result, selection)
    if not planned:
        raise CurveMoleError("The selected export items have no available data to write.")

    # New exports keep ownership metadata inside the project so the default export
    # can genuinely contain one visible file. Old hidden manifests remain readable
    # for backwards-compatible updates, but are not created for new exports.
    previous_owned: set[str] = set()
    stored_directory = project.export_config.get("directory")
    if stored_directory:
        try:
            same_root = Path(str(stored_directory)).resolve(strict=False) == root.resolve(strict=False)
        except OSError:
            same_root = Path(str(stored_directory)) == root
        if same_root:
            previous_owned.update(
                _normalise_owned_path(relative)
                for relative in project.export_config.get("owned_files", [])
            )

    legacy_manifest = root / ".curvemole-export.json"
    if legacy_manifest.exists():
        try:
            previous_owned.update(
                _normalise_owned_path(relative)
                for relative in json.loads(legacy_manifest.read_text(encoding="utf-8")).get(
                    "owned_files", []
                )
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise CurveMoleError(
                f"Existing export manifest is unreadable: {legacy_manifest}. No files were changed."
            ) from exc

    collisions = [relative for relative in planned if (root / relative).exists()]
    if collisions and not overwrite:
        raise FileExistsError(
            "Export would overwrite existing files. Confirm update or choose versioned export: "
            + ", ".join(collisions[:8])
        )
    if collisions and overwrite and not previous_owned:
        raise FileExistsError(
            "Export refused because CurveMole cannot verify ownership of the existing files: "
            + ", ".join(collisions[:8])
        )
    if previous_owned:
        protected_collision = [relative for relative in collisions if relative not in previous_owned]
        if protected_collision:
            raise FileExistsError(
                "Export refused to overwrite files not owned by CurveMole: "
                + ", ".join(protected_collision[:8])
            )

    root.mkdir(parents=True, exist_ok=True)
    summary = ExportSummary(root)
    before = {relative: _sha256(root / relative) for relative in collisions}
    base = _safe_name(project.name) or "curvemole"

    if selection.fit_results:
        export_dataframe(
            parameter_dataframe(project, result, registry=registry),
            root / "fit_results.csv",
            delimiter=delimiter,
        )

    if selection.wide_tables:
        for curve in project.curves:
            frame = wide_dataframe(
                curve,
                project.models.get(curve.id),
                registry=registry,
                parameter_values=project.resolved_parameter_values(),
            )
            export_dataframe(
                frame,
                root / "data" / f"{_safe_name(curve.name)}_wide.csv",
                delimiter=delimiter,
            )

    if selection.tidy_table:
        export_dataframe(
            tidy_dataframe(project, registry=registry),
            root / "python" / "data_tidy.csv",
            delimiter=delimiter,
        )

    if selection.results_json:
        results_path = root / "python" / "results.json"
        results_path.parent.mkdir(parents=True, exist_ok=True)
        results_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "application_version": __version__,
                    "result": result.to_dict(arrays=False) if result else None,
                },
                indent=2,
                default=_json_default,
            )
            + "\\n",
            encoding="utf-8",
        )

    if selection.fitmodel:
        first_model = next(iter(project.models.values()), Model())
        save_fitmodel(
            first_model,
            root / f"{base}.fitmodel",
            custom_functions=project.custom_functions,
        )

    if selection.project_copy:
        save_project(
            project,
            root / f"{base}.fitproj",
            include_uncertainty_samples=include_uncertainty_samples,
            update_project_path=False,
        )

    if selection.main_plot_png:
        export_figure(project.curves, project.models, root / "main_plot.png", registry=registry)

    if selection.main_plot_svg:
        export_figure(
            project.curves,
            project.models,
            root / "figures" / "main_plot.svg",
            registry=registry,
        )

    if selection.html_summary:
        generate_html_report(
            project,
            root / "summary_report.html",
            result=result,
            registry=registry,
        )

    if selection.html_reproducibility:
        generate_html_report(
            project,
            root / "report" / "full_reproducibility.html",
            result=result,
            full=True,
            registry=registry,
        )

    if selection.pdf_summary:
        generate_pdf_report(
            project,
            root / "report" / "summary.pdf",
            result=result,
            registry=registry,
        )

    if selection.uncertainty and result:
        if result.covariance is not None:
            covariance_path = root / "uncertainty" / "covariance.csv"
            covariance_path.parent.mkdir(parents=True, exist_ok=True)
            np.savetxt(covariance_path, result.covariance, delimiter=delimiter)
        if result.correlation is not None:
            correlation_path = root / "uncertainty" / "correlation.csv"
            correlation_path.parent.mkdir(parents=True, exist_ok=True)
            np.savetxt(correlation_path, result.correlation, delimiter=delimiter)

    if selection.diagnostics and result:
        for curve_id, output in result.curve_outputs.items():
            diagnostics = residual_diagnostics(output.residual)
            diagnostics_path = root / "diagnostics" / f"{curve_id}_autocorrelation.csv"
            diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                {
                    "lag": np.arange(len(diagnostics.autocorrelation)),
                    "autocorrelation": diagnostics.autocorrelation,
                }
            ).to_csv(diagnostics_path, index=False)

    if selection.readme:
        (root / "README.txt").write_text(
            "CurveMole selected analysis export\\n\\n"
            "fit_results.csv contains the fitted functions and their parameters, grouped by data curve.\\n"
            "Additional files are present only when explicitly selected in the export dialog.\\n",
            encoding="utf-8",
        )

    written = sorted(relative for relative in planned if (root / relative).is_file())
    owned = sorted(previous_owned | set(written))
    for relative in written:
        output_path = root / relative
        if relative in before:
            (summary.unchanged if before[relative] == _sha256(output_path) else summary.updated).append(
                output_path
            )
        else:
            summary.created.append(output_path)

    project.export_config["directory"] = str(root)
    project.export_config["owned_files"] = owned
    project.export_config["selection"] = selection.to_dict()
    return summary


def _bundle_paths(
    project: Project,
    result: FitResult | None,
    selection: BundleExportSelection,
) -> list[str]:
    base = _safe_name(project.name) or "curvemole"
    paths: list[str] = []
    if selection.fit_results:
        paths.append("fit_results.csv")
    if selection.wide_tables:
        paths.extend(
            f"data/{_safe_name(curve.name)}_wide.csv"
            for curve in project.curves
        )
    if selection.tidy_table:
        paths.append("python/data_tidy.csv")
    if selection.results_json:
        paths.append("python/results.json")
    if selection.fitmodel:
        paths.append(f"{base}.fitmodel")
    if selection.project_copy:
        paths.append(f"{base}.fitproj")
    if selection.main_plot_png:
        paths.append("main_plot.png")
    if selection.main_plot_svg:
        paths.append("figures/main_plot.svg")
    if selection.html_summary:
        paths.append("summary_report.html")
    if selection.html_reproducibility:
        paths.append("report/full_reproducibility.html")
    if selection.pdf_summary:
        paths.append("report/summary.pdf")
    if selection.uncertainty and result:
        if result.covariance is not None:
            paths.append("uncertainty/covariance.csv")
        if result.correlation is not None:
            paths.append("uncertainty/correlation.csv")
    if selection.diagnostics and result:
        paths.extend(
            f"diagnostics/{curve_id}_autocorrelation.csv"
            for curve_id in result.curve_outputs
        )
    if selection.readme:
        paths.append("README.txt")
    return paths


'''
text = replace_between(
    text,
    "def export_bundle(\n",
    "def _registry_for_project(project: Project) -> FunctionRegistry:\n",
    new_bundle,
    "selective export bundle",
)
path.write_text(text, encoding="utf-8")


# --- export dialog ---------------------------------------------------------
path = Path("src/curvemole/gui/dialogs.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from curvemole.core.data import Curve\n",
    "from curvemole.core.data import Curve\nfrom curvemole.core.export import BundleExportSelection\n",
    "dialog export selection import",
)

new_dialog = '''class ExportBundleDialog(QDialog):
    def __init__(self, remembered: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Export analysis"))
        self.resize(720, 610)
        layout = QVBoxLayout(self)

        info = QLabel(
            self.tr(
                "Choose how the export is saved and, independently, what it contains. "
                "By default CurveMole writes only fit_results.csv."
            )
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        row = QHBoxLayout()
        self.directory = QLineEdit(remembered or "")
        browse = QLabel(f'<a href="#">{self.tr("Choose folder…")}</a>')
        browse.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        browse.linkActivated.connect(self._browse)
        row.addWidget(self.directory, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        mode_box = QGroupBox(self.tr("Export mode"))
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.addWidget(
            QLabel(
                self.tr(
                    "Leave both options unchecked to create a new export in the selected folder."
                )
            )
        )
        self.versioned = QCheckBox(self.tr("Create versioned export"))
        self.overwrite = QCheckBox(
            self.tr("Update existing CurveMole-owned files after confirmation")
        )
        self.versioned.toggled.connect(
            lambda checked: self.overwrite.setChecked(False) if checked else None
        )
        self.overwrite.toggled.connect(
            lambda checked: self.versioned.setChecked(False) if checked else None
        )
        mode_layout.addWidget(self.versioned)
        mode_layout.addWidget(self.overwrite)
        layout.addWidget(mode_box)

        export_box = QGroupBox(self.tr("What to export?"))
        export_layout = QGridLayout(export_box)
        self.fit_results = QCheckBox(
            self.tr("Fit results (functions, parameters and errors) — fit_results.csv")
        )
        self.fit_results.setChecked(True)
        self.wide_tables = QCheckBox(self.tr("Data + fitted curves tables (CSV)"))
        self.tidy_table = QCheckBox(self.tr("Tidy data table for Python (CSV)"))
        self.results_json = QCheckBox(self.tr("Machine-readable fit result (JSON)"))
        self.fitmodel = QCheckBox(self.tr("Reusable fit model (.fitmodel)"))
        self.project_copy = QCheckBox(self.tr("Project copy (.fitproj)"))
        self.main_plot_png = QCheckBox(self.tr("Main plot (PNG)"))
        self.main_plot_svg = QCheckBox(self.tr("Main plot (SVG)"))
        self.html_summary = QCheckBox(self.tr("Summary report (HTML)"))
        self.html_reproducibility = QCheckBox(self.tr("Full reproducibility report (HTML)"))
        self.pdf_summary = QCheckBox(self.tr("Summary report (PDF)"))
        self.uncertainty = QCheckBox(self.tr("Covariance/correlation matrices"))
        self.diagnostics = QCheckBox(self.tr("Residual diagnostics"))
        self.readme = QCheckBox(self.tr("Export README"))

        choices = [
            self.fit_results,
            self.wide_tables,
            self.tidy_table,
            self.results_json,
            self.fitmodel,
            self.project_copy,
            self.main_plot_png,
            self.main_plot_svg,
            self.html_summary,
            self.html_reproducibility,
            self.pdf_summary,
            self.uncertainty,
            self.diagnostics,
            self.readme,
        ]
        for index, widget in enumerate(choices):
            export_layout.addWidget(widget, index // 2, index % 2)
        layout.addWidget(export_box)

        self.full_samples = QCheckBox(
            self.tr("Include full uncertainty samples in the .fitproj copy")
        )
        self.full_samples.setChecked(True)
        self.full_samples.setEnabled(False)
        self.project_copy.toggled.connect(self.full_samples.setEnabled)
        layout.addWidget(self.full_samples)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selection(self) -> BundleExportSelection:
        return BundleExportSelection(
            fit_results=self.fit_results.isChecked(),
            wide_tables=self.wide_tables.isChecked(),
            tidy_table=self.tidy_table.isChecked(),
            results_json=self.results_json.isChecked(),
            fitmodel=self.fitmodel.isChecked(),
            project_copy=self.project_copy.isChecked(),
            main_plot_png=self.main_plot_png.isChecked(),
            main_plot_svg=self.main_plot_svg.isChecked(),
            html_summary=self.html_summary.isChecked(),
            html_reproducibility=self.html_reproducibility.isChecked(),
            pdf_summary=self.pdf_summary.isChecked(),
            uncertainty=self.uncertainty.isChecked(),
            diagnostics=self.diagnostics.isChecked(),
            readme=self.readme.isChecked(),
        )

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, self.tr("Export folder"), self.directory.text())
        if selected:
            self.directory.setText(selected)

    def _accept(self) -> None:
        if not self.directory.text().strip():
            QMessageBox.warning(self, self.tr("Export"), self.tr("Choose an export folder."))
            return
        if not self.selection().any_selected():
            QMessageBox.warning(
                self,
                self.tr("Export"),
                self.tr("Select at least one item under 'What to export?'."),
            )
            return
        self.accept()
'''
text = replace_between(
    text,
    "class ExportBundleDialog(QDialog):\n",
    "\n\nclass AboutDialog(QDialog):\n",
    new_dialog,
    "export dialog",
)
path.write_text(text, encoding="utf-8")


# --- main-window wiring ----------------------------------------------------
path = Path("src/curvemole/gui/main_window.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '                    "CurveMole will overwrite only files recorded in its export manifest. "\n'
    '                    "Unrelated files will be preserved. Continue?"\n',
    '                    "CurveMole will overwrite only files previously recorded as belonging "\n'
    '                    "to this project export. Unrelated files will be preserved. Continue?"\n',
    "export update message",
)
text = replace_once(
    text,
    "                include_uncertainty_samples=dialog.full_samples.isChecked(),\n",
    "                include_uncertainty_samples=dialog.full_samples.isChecked(),\n"
    "                selection=dialog.selection(),\n",
    "export dialog selection wiring",
)
path.write_text(text, encoding="utf-8")


# --- manual ---------------------------------------------------------------
path = Path("docs/manual.md")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    """Then choose **File > Export analysis bundle**. Select a new empty directory for the
first export. The bundle contains human-readable CSV tables, fit parameters, plots,
HTML and PDF reports, machine-readable JSON, a reusable model, and a portable project
copy.
""",
    """Then choose **File > Export analysis bundle**. Select a destination and choose both
how to save and **What to export?**. The default selection writes only
`fit_results.csv`, which associates every curve with its model functions and lists
each parameter together with its fitted value and standard error. Data tables, plots,
reports, JSON, reusable models, project copies, uncertainty matrices, and diagnostics
are optional.
""",
    "manual first-export tutorial",
)

new_manual_section = '''## 14. Exporting an analysis bundle

### 14.1 Starting an export

Choose **File > Export analysis bundle** or press **Ctrl+E**. Export mode and export
content are independent.

The existing save modes remain:

- leave both mode checkboxes clear to create a new export in the selected directory;
- **Create versioned export** to create a timestamped subdirectory;
- **Update existing CurveMole-owned files after confirmation** to update files that
  CurveMole can verify as belonging to the current project export.

Under **What to export?**, select the desired outputs. Only **Fit results** is checked
by default.

### 14.2 Default fit-results file

The default export creates only `fit_results.csv`. No additional visible file and no
empty subdirectory is created.

Each row represents one parameter of one model component and includes the series,
curve and curve ID, component and component ID, displayed function and function ID,
enabled/background state, composition operator, parameter name and full parameter
path, fitted value, standard error, confidence interval, bounds, fixed/link state,
unit, human-readable value with uncertainty, and derived area/FWHM where defined.

This format makes the association between every data curve, the functions used to fit
it, and the fitted parameters explicit in a single table.

### 14.3 Optional outputs

The dialog can additionally export:

- data plus fitted-function wide CSV tables;
- a tidy CSV table for Python;
- machine-readable fit results as JSON;
- a reusable `.fitmodel`;
- a `.fitproj` project copy, optionally including full uncertainty samples;
- the main plot as PNG and/or SVG;
- compact HTML and PDF summaries;
- a full reproducibility HTML report;
- covariance and correlation matrices when available;
- residual autocorrelation diagnostics when available;
- an export README.

Directories such as `data/`, `python/`, `figures/`, `report/`, `uncertainty/`, and
`diagnostics/` are created only when a selected output actually writes a file there.
An option whose required fit result is unavailable does not create an empty folder.

### 14.4 Safe overwrite policy

New exports store their ownership list in the project export configuration rather
than creating a hidden sidecar file. This allows the default export to contain truly
only `fit_results.csv`. Existing `.curvemole-export.json` manifests from older
versions are still read for backwards-compatible updates.

When **Update existing** is selected, CurveMole refuses to overwrite a colliding file
unless it can verify that the file belongs to the current project export. Unrelated
files in the directory are preserved.

### 14.5 Wide data tables

Optional wide CSV files are intended for direct inspection and tools such as Origin
or QtiPlot. Depending on data and model, columns include:

- x and y;
- total fit;
- residual as data minus fit;
- total background;
- every enabled component;
- `sigma_y` or point weight;
- mask flag.

Rows remain aligned with the complete curve, including masked and invalid entries.

### 14.6 Tidy data and JSON

`python/data_tidy.csv` stores one quantity per row with series, curve, component, x,
value, mask, and validity fields. `python/results.json` records schema version,
application version, result metadata, parameters, statistics, warnings, and settings
without duplicating large numeric arrays.

### 14.7 Reports and reusable files

- `summary_report.html` is a compact human-readable report.
- `report/full_reproducibility.html` includes project metadata.
- `report/summary.pdf` contains a summary plot and statistics.
- `.fitmodel` stores the first project model and custom formulas for programmatic
  reuse.
- `.fitproj` is a complete portable project snapshot.

The exported report PDF is an analysis summary, not the CurveMole software manual.

'''
text = replace_between(
    text,
    "## 14. Exporting an analysis bundle\n",
    "## 15. Command-line interface\n",
    new_manual_section,
    "manual export chapter",
)
path.write_text(text, encoding="utf-8")


# --- regression tests -----------------------------------------------------
Path("tests/test_export_selection.py").write_text(
    '''from __future__ import annotations

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
''',
    encoding="utf-8",
)

Path("tests/test_export_dialog.py").write_text(
    '''from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)

from PySide6.QtWidgets import QApplication

from curvemole.gui.dialogs import ExportBundleDialog


def test_export_dialog_defaults_to_fit_results_only() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = ExportBundleDialog()

    selected = dialog.selection().to_dict()
    assert selected["fit_results"] is True
    assert sum(bool(value) for value in selected.values()) == 1
    assert dialog.full_samples.isEnabled() is False

    dialog.project_copy.setChecked(True)
    assert dialog.full_samples.isEnabled() is True

    dialog.versioned.setChecked(True)
    dialog.overwrite.setChecked(True)
    assert dialog.overwrite.isChecked() is True
    assert dialog.versioned.isChecked() is False

    dialog.close()
    app.processEvents()
''',
    encoding="utf-8",
)

print("Export redesign patch applied")
