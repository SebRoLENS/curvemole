"""ImportMappingDialog."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.importers import ColumnMapping, ImportConfig, inspect_file
from curvemole.gui.dialogs._shared import (
    _name_accept,
    _set_list_checked,
)
from curvemole.gui.parameter_link import ParameterLinkDialog  # noqa: E402, F401


class ImportMappingDialog(QDialog):
    def __init__(
        self,
        path: str | Path,
        *,
        batch_size: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = Path(path)
        self.setWindowTitle(self.tr("Import data — column mapping"))
        self.resize(900, 610)
        self.inspection = inspect_file(self.path)
        layout = QVBoxLayout(self)
        title = QLabel(f"<b>{self.path.name}</b>")
        layout.addWidget(title)

        series_row = QFormLayout()
        self.series_form = series_row
        self.destination_series = QComboBox()
        self.destination_series.addItem(self.tr("Create a new series"), None)
        self.destination_series.setToolTip(self.tr("Destination for all files in this import."))
        series_row.addRow(self.tr("Destination:"), self.destination_series)
        self.series_name = QLineEdit(self.tr("Series 1"))
        self.series_name.setObjectName("import_series_name")
        self.series_name.setToolTip(self.tr("Name of the series containing all files in this import."))
        self.existing_series_names: set[str] = set()
        series_row.addRow(self.tr("Series name:"), self.series_name)
        self.destination_series.currentIndexChanged.connect(self._update_series_destination)
        layout.addLayout(series_row)

        settings = QGroupBox(self.tr("Parsing"))
        settings_layout = QHBoxLayout(settings)
        settings_layout.addWidget(QLabel(self.tr("Delimiter:")))
        self.delimiter = QComboBox()
        self.delimiter.addItem(self.tr("Whitespace"), None)
        self.delimiter.addItem(self.tr("Comma"), ",")
        self.delimiter.addItem(self.tr("Semicolon"), ";")
        self.delimiter.addItem(self.tr("Tab"), "\t")
        self.delimiter.addItem(self.tr("Pipe"), "|")
        selected = self.delimiter.findData(self.inspection.config.delimiter)
        self.delimiter.setCurrentIndex(max(0, selected))
        settings_layout.addWidget(self.delimiter)
        settings_layout.addWidget(QLabel(self.tr("Decimal:")))
        self.decimal = QComboBox()
        self.decimal.addItems([".", ","])
        self.decimal.setCurrentText(self.inspection.config.decimal)
        settings_layout.addWidget(self.decimal)
        self.header = QCheckBox(self.tr("First data row is a header"))
        self.header.setChecked(bool(self.inspection.config.header))
        settings_layout.addWidget(self.header)
        settings_layout.addWidget(QLabel(self.tr("Ignore first rows:")))
        self.skip_rows = QSpinBox()
        self.skip_rows.setRange(0, 1_000_000)
        self.skip_rows.setValue(int(self.inspection.config.skip_rows))
        self.skip_rows.setToolTip(self.tr(
            "Ignore this many physical lines at the beginning of the file before parsing."))
        settings_layout.addWidget(self.skip_rows)
        settings_layout.addStretch(1)
        self.skip_rows.valueChanged.connect(self._reload)
        self.delimiter.currentIndexChanged.connect(self._reload)
        self.decimal.currentTextChanged.connect(self._reload)
        self.header.toggled.connect(self._reload)
        layout.addWidget(settings)

        self.preview = QTableWidget()
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.setAlternatingRowColors(True)
        layout.addWidget(self.preview, 1)

        mapping_box = QGroupBox(self.tr("Columns"))
        mapping = QGridLayout(mapping_box)
        mapping.addWidget(QLabel(self.tr("X column")), 0, 0)
        self.x_column = QComboBox()
        mapping.addWidget(self.x_column, 0, 1)
        mapping.addWidget(QLabel(self.tr("Y column(s)")), 0, 2)
        self.y_columns = QListWidget()
        self.y_columns.setMaximumHeight(105)
        mapping.addWidget(self.y_columns, 0, 3, 3, 1)
        self.separated_files = QCheckBox(self.tr("as separated files"))
        self.separated_files.setToolTip(self.tr(
            "Import each selected Y column as an independent spectrum, using its associated X. "
            "Each spectrum is named after its Y column. No files are written to disk."))
        mapping.addWidget(self.separated_files, 3, 3)
        mapping.addWidget(QLabel(self.tr("sigma_x")), 1, 0)
        self.sigma_x = QComboBox()
        mapping.addWidget(self.sigma_x, 1, 1)
        self.uncertainty_label = QLabel(self.tr("Uncertainty/weight"))
        mapping.addWidget(self.uncertainty_label, 2, 0)
        uncertainty_row = QHBoxLayout()
        self.uncertainty_kind = QComboBox()
        self.uncertainty_kind.addItems(
            [self.tr("None"), "sigma_y", self.tr("Y error (confidence interval)"),
             self.tr("Weight"), self.tr("Variance"), self.tr("Inverse variance")]
        )
        self.uncertainty_column = QComboBox()
        uncertainty_row.addWidget(self.uncertainty_kind)
        uncertainty_row.addWidget(self.uncertainty_column)
        mapping.addLayout(uncertainty_row, 2, 1, 1, 2)
        self.asymmetric_error = QCheckBox(self.tr("Asymmetric error"))
        self.asymmetric_error.setToolTip(self.tr(
            "Import positive Y error magnitudes: y − error − to y + error +, "
            "at the confidence level declared below."))
        mapping.addWidget(self.asymmetric_error, 3, 0, 1, 2)
        self.error_plus_column = QComboBox()
        self.error_minus_column = QComboBox()
        self.error_confidence = QDoubleSpinBox()
        self.error_confidence.setRange(0.001, 99.999)
        self.error_confidence.setDecimals(3)
        self.error_confidence.setValue(95)
        self.error_confidence.setSuffix(" %")
        self.error_plus_label = QLabel(self.tr("Y error +"))
        self.error_minus_label = QLabel(self.tr("Y error −"))
        self.error_confidence_label = QLabel(self.tr("Data error confidence"))
        mapping.addWidget(self.error_plus_label, 4, 0)
        mapping.addWidget(self.error_plus_column, 4, 1)
        mapping.addWidget(self.error_minus_label, 4, 2)
        mapping.addWidget(self.error_minus_column, 4, 3)
        mapping.addWidget(self.error_confidence_label, 5, 0)
        mapping.addWidget(self.error_confidence, 5, 1)
        self.error_confidence.setToolTip(self.tr(
            "Central confidence interval of the imported data errors. "
            "This is separate from the confidence of fitted parameter intervals. "
            "Fit and Monte Carlo use a Gaussian approximation on each side."))
        self.asymmetric_error.toggled.connect(self._update_error_mapping)
        self.uncertainty_kind.currentIndexChanged.connect(self._update_error_mapping)
        self.asymmetric_error.toggled.connect(self._suggest_error_columns)
        self.uncertainty_kind.currentIndexChanged.connect(self._suggest_error_columns)
        self._update_error_mapping()
        layout.addWidget(mapping_box)
        y_buttons = QHBoxLayout()
        self.select_all_y_button = QPushButton(self.tr("Select all Y columns"))
        self.deselect_all_y_button = QPushButton(self.tr("Deselect all Y columns"))
        self.select_all_y_button.clicked.connect(self._select_all_import_y)
        self.deselect_all_y_button.clicked.connect(lambda: _set_list_checked(self.y_columns, False))
        y_buttons.addWidget(self.select_all_y_button)
        y_buttons.addWidget(self.deselect_all_y_button)
        y_buttons.addStretch(1)
        layout.addLayout(y_buttons)
        from curvemole.gui.import_spectra import SpectrumMappingEditor
        self.spectra_editor = SpectrumMappingEditor(self)
        layout.addWidget(self.spectra_editor)
        self.separated_files.toggled.connect(self._separated_mode_changed)
        self.y_columns.itemChanged.connect(self._y_selection_changed)
        self.spectra_editor.structure.currentIndexChanged.connect(self._update_mapping_controls)

        self.apply_all = QCheckBox(self.tr("Apply this mapping to all files in this batch"))
        self.apply_all.setChecked(batch_size > 1)
        self.apply_all.setVisible(batch_size > 1)
        layout.addWidget(self.apply_all)
        self.match_column_positions = QCheckBox(self.tr("Match columns by position (ignore headers)"))
        self.match_column_positions.setToolTip(self.tr(
            "Use the selected column numbers for X, Y and any uncertainty columns, "
            "even when another file uses different headers."
        ))
        layout.addWidget(self.match_column_positions)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        _name_accept(self.buttons, self.tr("Import"))
        self.buttons.accepted.connect(lambda: self._accept())
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._populate()
        from curvemole.gui.import_preview import SpectrumImportPreview
        self.spectrum_preview = SpectrumImportPreview(self)
        layout.insertWidget(layout.indexOf(self.preview) + 1, self.spectrum_preview)
        self.resize(900, 760)

    def config(self) -> ImportConfig:
        return ImportConfig(
            delimiter=self.delimiter.currentData(),
            decimal=self.decimal.currentText(),
            header=self.header.isChecked(),
            skip_rows=self.skip_rows.value(),
        )

    def mapping(self) -> ColumnMapping:
        if self.separated_files.isChecked() and len(self.inspection.columns) > 2:
            return self.spectra_editor.mapping()
        selected_y = [
            self.y_columns.item(index).text()
            for index in range(self.y_columns.count())
            if self.y_columns.item(index).checkState() == Qt.CheckState.Checked
        ]
        mapping = ColumnMapping(
            x=self.x_column.currentText(),
            y=selected_y,
            sigma_x=self.sigma_x.currentData(),
        )
        kind = self.uncertainty_kind.currentText()
        column = self.uncertainty_column.currentData()
        if (not self.asymmetric_error.isChecked()
                and self.uncertainty_kind.currentIndex() > 0 and column is None):
            raise ValueError(self.tr("Select the error/weight column."))
        if self.asymmetric_error.isChecked():
            mapping.error_y_plus = self.error_plus_column.currentData()
            mapping.error_y_minus = self.error_minus_column.currentData()
            if mapping.error_y_plus is None or mapping.error_y_minus is None:
                raise ValueError(self.tr("Select both Y error + and Y error − columns."))
            if mapping.error_y_plus == mapping.error_y_minus:
                raise ValueError(self.tr("Asymmetric errors require two distinct error columns."))
            mapping.error_confidence_level = self.error_confidence.value() / 100
        elif kind == self.tr("Y error (confidence interval)"):
            if column is None:
                raise ValueError(self.tr("Select the Y error column."))
            mapping.error_y_plus = mapping.error_y_minus = column
            mapping.error_confidence_level = self.error_confidence.value() / 100
        elif kind == "sigma_y":
            mapping.sigma_y = column
        elif kind == self.tr("Weight"):
            mapping.weights = column
        elif kind == self.tr("Variance"):
            mapping.variance = column
        elif kind == self.tr("Inverse variance"):
            mapping.inverse_variance = column
        axes = {mapping.x, *mapping.y}
        for name in ("sigma_x", "sigma_y", "weights", "variance", "inverse_variance",
                     "error_y_plus", "error_y_minus"):
            if getattr(mapping, name) is not None and getattr(mapping, name) in axes:
                raise ValueError(self.tr("An error/weight column is already assigned as X or Y."))
        return mapping

    def _select_all_import_y(self) -> None:
        self.y_columns.blockSignals(True)
        for row in range(self.y_columns.count()):
            self.y_columns.item(row).setCheckState(
                Qt.CheckState.Checked if row != self.x_column.currentIndex()
                else Qt.CheckState.Unchecked)
        self.y_columns.blockSignals(False)
        self.spectra_editor.sync_shared()

    def _y_selection_changed(self, item: QListWidgetItem) -> None:
        if not self.separated_files.isChecked() and item.checkState() == Qt.CheckState.Checked:
            self.y_columns.blockSignals(True)
            for row in range(self.y_columns.count()):
                other = self.y_columns.item(row)
                if other is not item:
                    other.setCheckState(Qt.CheckState.Unchecked)
            self.y_columns.blockSignals(False)
        self._suggest_error_columns()

    def _separated_mode_changed(self, *_: Any) -> None:
        if not self.separated_files.isChecked():
            selected = [self.y_columns.item(row) for row in range(self.y_columns.count())
                        if self.y_columns.item(row).checkState() == Qt.CheckState.Checked]
            if selected:
                self._y_selection_changed(selected[0])
        self.spectra_editor.sync_shared()
        self._update_mapping_controls()
        if hasattr(self, "spectrum_preview"):
            self.spectrum_preview.schedule()

    def _update_mapping_controls(self, *_: Any) -> None:
        multiple = len(self.inspection.columns) > 2
        self.separated_files.setVisible(multiple)
        separated = multiple and self.separated_files.isChecked()
        self.spectra_editor.setVisible(separated)
        shared = self.spectra_editor.structure.currentData() == "shared"
        self.x_column.setEnabled(not separated or shared)
        self.y_columns.setEnabled(not separated or shared)
        self.select_all_y_button.setVisible(separated and shared)
        self.deselect_all_y_button.setVisible(separated and shared)
        for widget in (self.uncertainty_label, self.uncertainty_kind,
                       self.uncertainty_column, self.asymmetric_error):
            widget.setVisible(not separated)
        self._update_error_mapping()

    def _suggest_error_columns(self, *_: Any) -> None:
        if self.separated_files.isChecked():
            return
        selected = [row for row in range(self.y_columns.count())
                    if self.y_columns.item(row).checkState() == Qt.CheckState.Checked]
        if not selected:
            return
        y = selected[0]
        def adjacent(offset: int) -> str | None:
            index = y + offset
            return self.inspection.columns[index] if index < len(self.inspection.columns) else None
        if self.asymmetric_error.isChecked():
            self.error_plus_column.setCurrentIndex(max(0, self.error_plus_column.findData(adjacent(1))))
            self.error_minus_column.setCurrentIndex(max(0, self.error_minus_column.findData(adjacent(2))))
        elif self.uncertainty_kind.currentIndex() > 0:
            self.uncertainty_column.setCurrentIndex(max(0, self.uncertainty_column.findData(adjacent(1))))

    def _update_error_mapping(self, *_: Any) -> None:
        asymmetric = self.asymmetric_error.isChecked()
        separated = self.separated_files.isChecked()
        self.uncertainty_kind.setEnabled(not asymmetric)
        self.uncertainty_column.setEnabled(not asymmetric)
        for widget in (self.error_plus_column, self.error_minus_column,
                       self.error_plus_label, self.error_minus_label):
            widget.setVisible(asymmetric and not separated)
        confidence = not separated and (asymmetric or self.uncertainty_kind.currentText() == self.tr("Y error (confidence interval)"))
        self.error_confidence.setVisible(confidence)
        self.error_confidence_label.setVisible(confidence)

    def _reload(self) -> None:
        try:
            self.inspection = inspect_file(self.path, self.config())
            self._populate()
            if hasattr(self, "spectrum_preview"):
                self.spectrum_preview.schedule()
        except Exception as exc:
            if hasattr(self, "spectrum_preview"):
                self.spectrum_preview.graph.clear()
                self.spectrum_preview.label.setText("Spectrum preview unavailable")
            QMessageBox.warning(self, self.tr("Import preview"), str(exc))

    def _populate(self) -> None:
        frame = self.inspection.preview
        self.preview.setRowCount(len(frame))
        self.preview.setColumnCount(len(frame.columns))
        self.preview.setHorizontalHeaderLabels([str(value) for value in frame.columns])
        for row in range(len(frame)):
            for column in range(len(frame.columns)):
                self.preview.setItem(row, column, QTableWidgetItem(str(frame.iat[row, column])))
        self.preview.resizeColumnsToContents()
        previous_x = self.x_column.currentText()
        previous_x_index = self.x_column.currentIndex()
        previous_y_indices = {index for index in range(self.y_columns.count())
                              if self.y_columns.item(index).checkState() == Qt.CheckState.Checked}
        previous_y = {
            self.y_columns.item(index).text()
            for index in range(self.y_columns.count())
            if self.y_columns.item(index).checkState() == Qt.CheckState.Checked
        }
        columns = [str(value) for value in frame.columns]
        retain_positions = self.x_column.count() == len(columns)
        self.x_column.blockSignals(True)
        self.x_column.clear()
        self.x_column.addItems(columns)
        if previous_x in columns:
            self.x_column.setCurrentText(previous_x)
        elif retain_positions and previous_x_index >= 0:
            self.x_column.setCurrentIndex(previous_x_index)
        self.x_column.blockSignals(False)
        self.y_columns.blockSignals(True)
        self.y_columns.clear()
        for index, column in enumerate(columns):
            item = QListWidgetItem(column)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = (index in previous_y_indices if retain_positions else column in previous_y)
            item.setCheckState(
                Qt.CheckState.Checked if checked or (not previous_y and index == 1) else Qt.CheckState.Unchecked
            )
            self.y_columns.addItem(item)
        self.y_columns.blockSignals(False)
        for combo in (self.sigma_x, self.uncertainty_column, self.error_plus_column, self.error_minus_column):
            old = combo.currentData()
            combo.clear()
            combo.addItem(self.tr("None"), None)
            for column in columns:
                combo.addItem(column, column)
            selected = combo.findData(old)
            combo.setCurrentIndex(max(0, selected))
        if len(columns) <= 2:
            self.separated_files.setChecked(False)
        self.spectra_editor.set_columns(columns)
        self._update_mapping_controls()

    def set_series_destinations(self, series, selected_id=None) -> None:
        self.destination_series.clear()
        self.destination_series.addItem(self.tr("Create a new series"), None)
        for item in series:
            self.destination_series.addItem(item.name, item.id)
        self.destination_series.setCurrentIndex(max(0, self.destination_series.findData(selected_id)))

    def _update_series_destination(self, *_args) -> None:
        new_series = self.destination_series.currentData() is None
        self.series_name.setEnabled(new_series)
        self.series_form.setRowVisible(self.series_name, new_series)

    def _accept(self) -> None:
        name = self.series_name.text().strip()
        if self.destination_series.currentData() is None and (not name or name in self.existing_series_names):
            QMessageBox.warning(
                self, self.tr("Series name"),
                self.tr("Enter a non-empty series name that is not already in use."),
            )
            self.series_name.setFocus()
            return
        self.series_name.setText(name)
        try:
            self.mapping().validate()
        except Exception as exc:
            QMessageBox.warning(self, self.tr("Column mapping"), str(exc))
            return
        self.accept()
