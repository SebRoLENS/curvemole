"""ExportBundleDialog."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.export import BundleExportSelection
from curvemole.gui.dialogs._shared import (
    _name_accept,
)
from curvemole.gui.parameter_link import ParameterLinkDialog  # noqa: E402, F401


class ExportBundleDialog(QDialog):
    def __init__(self, remembered: str | None = None, parent: QWidget | None = None, *, project_name: str = "analysis") -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Export analysis bundle"))
        self._remembered_directory = remembered
        self.resize(860, 760)
        layout = QVBoxLayout(self)

        info = QLabel(
            self.tr(
                "The complete bundle includes every available export, including the quick exports. "
                "Each curve has its own figures and numeric files. Unavailable fit results are skipped."
            )
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        row = QHBoxLayout()
        self.directory = QLineEdit(str(Path(remembered).parent) if remembered else str(Path.cwd()))
        browse = QLabel(f'<a href="#">{self.tr("Choose folder…")}</a>')
        browse.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        browse.linkActivated.connect(self._browse)
        row.addWidget(self.directory, 1)
        row.addWidget(browse)
        layout.addLayout(row)
        folder_row = QHBoxLayout()
        self.create_subfolder = QCheckBox(self.tr("Create a folder for this bundle"))
        self.create_subfolder.setChecked(True)
        safe_project = "".join(character if character.isalnum() or character in "-_" else "_" for character in project_name).strip("._") or "analysis"
        self.folder_name = QLineEdit(f"{safe_project}-analysis-{datetime.now():%Y%m%d-%H%M%S}")
        self.folder_name.setPlaceholderText(self.tr("New folder name"))
        self.create_subfolder.toggled.connect(self.folder_name.setEnabled)
        folder_row.addWidget(self.create_subfolder)
        folder_row.addWidget(self.folder_name, 1)
        layout.addLayout(folder_row)
        self.destination_preview = QLabel()
        self.destination_preview.setWordWrap(True)
        self.directory.textChanged.connect(self._update_destination)
        self.folder_name.textChanged.connect(self._update_destination)
        self.create_subfolder.toggled.connect(self._update_destination)
        self._update_destination()
        layout.addWidget(self.destination_preview)

        mode_box = QGroupBox(self.tr("Export mode"))
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.addWidget(
            QLabel(
                self.tr(
                    "For an existing bundle, choose update; a versioned export adds a timestamped folder."
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
        self.overwrite.toggled.connect(self._existing_destination)
        mode_layout.addWidget(self.versioned)
        mode_layout.addWidget(self.overwrite)
        layout.addWidget(mode_box)

        export_box = QWidget()
        export_layout = QVBoxLayout(export_box)
        export_layout.setContentsMargins(0, 0, 0, 0)
        self.fit_results = QCheckBox(
            self.tr("Detailed fit parameters (CSV)")
        )
        self.fit_results.setToolTip(self.tr("fit_results.csv: functions, parameters, errors, bounds and links for each curve."))
        self.fit_results.setChecked(True)
        self.fit_settings = QCheckBox(self.tr("Recorded last-fit settings (CSV)"))
        self.fit_settings.setToolTip(self.tr(
            "Export every recorded optimizer and loss parameter, with the fit timestamp and curve IDs. "
            "Model parameter values are in fit_results.csv."))
        self.wide_tables = QCheckBox(self.tr("Data and fitted curves (CSV)"))
        self.tidy_table = QCheckBox(self.tr("Python tables + replot.py"))
        self.results_json = QCheckBox(self.tr("Recorded fit results (JSON)"))
        self.fitmodel = QCheckBox(self.tr("Reusable models (.fitmodel)"))
        self.project_copy = QCheckBox(self.tr("Project copy (.fitproj)"))
        self.main_plot_png = QCheckBox(self.tr("PNG figures (one per curve)"))
        self.main_plot_svg = QCheckBox(self.tr("SVG figures (one per curve)"))
        self.html_summary = QCheckBox(self.tr("Summary report (HTML)"))
        self.html_reproducibility = QCheckBox(self.tr("Full reproducibility report (HTML)"))
        self.pdf_summary = QCheckBox(self.tr("PDF figures + combined report"))
        self.uncertainty = QCheckBox(self.tr("Intervals, assessments and matrices"))
        self.diagnostics = QCheckBox(self.tr("Residual diagnostics"))
        self.readme = QCheckBox(self.tr("Export README"))
        self.laboratory_notebook = QCheckBox(self.tr("Laboratory notebook (TXT)"))
        self.spectra = QCheckBox(self.tr("Spectra and fitted traces (quick export)"))
        self.function_parameters = QCheckBox(self.tr("Function parameter matrix (quick export)"))
        self.parameter_covariances = QCheckBox(self.tr("Parameter covariance matrices"))
        self.current_view = QCheckBox(self.tr("Current view (PNG, SVG, PDF)"))

        self.main_plot_png.setToolTip(self.tr("Separate PNG figures in figures/png/."))
        self.main_plot_svg.setToolTip(self.tr("Separate SVG figures in figures/svg/."))
        self.pdf_summary.setToolTip(self.tr("Separate PDF figures in figures/pdf/ and the combined report at report/summary.pdf."))
        self.current_view.setToolTip(self.tr("The visible plot, including zoom and display settings. Each format has its own figures/png/, figures/svg/ or figures/pdf/ folder."))
        self.tidy_table.setToolTip(self.tr("Observation and component tables, curve metadata, and a script to regenerate the figures with Python."))
        self.fitmodel.setToolTip(self.tr("One reusable .fitmodel file per curve, inside models/."))
        self.full_samples = QCheckBox(
            self.tr("Include full uncertainty samples in the project copy")
        )
        self.full_samples.setChecked(True)
        self.project_copy.toggled.connect(self.full_samples.setEnabled)

        groups = [
            ("export_figures", self.tr("Figures"), [
                self.main_plot_png, self.main_plot_svg, self.pdf_summary, self.current_view,
            ]),
            ("export_data", self.tr("Data tables"), [
                self.spectra, self.wide_tables,
            ]),
            ("export_parameters", self.tr("Fit parameters and uncertainty"), [
                self.function_parameters, self.fit_results, self.fit_settings,
                self.parameter_covariances, self.uncertainty, self.diagnostics,
            ]),
            ("export_project", self.tr("Project and Python"), [
                self.project_copy, self.fitmodel, self.tidy_table, self.results_json,
            ]),
            ("export_reports", self.tr("Reports and documentation"), [
                self.html_summary, self.html_reproducibility, self.readme, self.laboratory_notebook,
            ]),
        ]
        choices = [widget for _, _, widgets in groups for widget in widgets]
        defaults = BundleExportSelection().to_dict()
        for field_name, checked in defaults.items():
            getattr(self, field_name).setChecked(checked)
        self.full_samples.setEnabled(self.project_copy.isChecked())
        for object_name, title, widgets in groups:
            group_box = QGroupBox(title)
            group_box.setObjectName(object_name)
            group_layout = QGridLayout(group_box)
            for index, widget in enumerate(widgets):
                group_layout.addWidget(widget, index // 2, index % 2)
            if self.project_copy in widgets:
                group_layout.addWidget(self.full_samples, 2, 0, 1, 2)
            group_layout.setColumnStretch(0, 1)
            group_layout.setColumnStretch(1, 1)
            export_layout.addWidget(group_box)
        export_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(export_box)
        layout.addWidget(scroll, 1)
        selection_row = QHBoxLayout()
        select_all = QPushButton(self.tr("Select all"))
        clear_all = QPushButton(self.tr("Clear selection"))
        select_all.clicked.connect(lambda: [widget.setChecked(True) for widget in choices])
        clear_all.clicked.connect(lambda: [widget.setChecked(False) for widget in choices])
        selection_row.addWidget(select_all)
        selection_row.addWidget(clear_all)
        selection_row.addStretch()
        layout.addLayout(selection_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        _name_accept(buttons, self.tr("Export"))
        buttons.accepted.connect(lambda: self._accept())
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selection(self) -> BundleExportSelection:
        return BundleExportSelection(
            spectra=self.spectra.isChecked(),
            function_parameters=self.function_parameters.isChecked(),
            parameter_covariances=self.parameter_covariances.isChecked(),
            current_view=self.current_view.isChecked(),
            fit_results=self.fit_results.isChecked(),
            fit_settings=self.fit_settings.isChecked(),
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
            laboratory_notebook=self.laboratory_notebook.isChecked(),
        )

    def _existing_destination(self, checked: bool) -> None:
        if checked and self._remembered_directory:
            self.directory.setText(str(self._remembered_directory))
            self.create_subfolder.setChecked(False)

    def destination(self) -> Path:
        root = Path(self.directory.text().strip()).expanduser()
        return root / self.folder_name.text().strip() if self.create_subfolder.isChecked() else root

    def _update_destination(self, *_args) -> None:
        self.destination_preview.setText(self.tr("Bundle destination: ") + str(self.destination()))

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, self.tr("Export folder"), self.directory.text())
        if selected:
            self.directory.setText(selected)

    def _accept(self) -> None:
        if not self.directory.text().strip():
            QMessageBox.warning(self, self.tr("Export"), self.tr("Choose an export folder."))
            return
        if self.create_subfolder.isChecked():
            name = self.folder_name.text().strip()
            if not name or name in {".", ".."} or any(character in name for character in '/\\'):
                QMessageBox.warning(self, self.tr("Export"), self.tr("Enter a single new folder name."))
                return
        if not self.selection().any_selected():
            QMessageBox.warning(
                self,
                self.tr("Export"),
                self.tr("Select at least one item to export."),
            )
            return
        self.accept()
