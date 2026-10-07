"""Explicit multi-spectrum mappings, with independent errors for every Y."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.errors import DataValidationError
from curvemole.core.importers import ColumnMapping, repeated_spectrum_mappings


class SpectrumMappingEditor(QWidget):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.columns = []
        self._updating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        controls.addWidget(QLabel(self.tr("Structure:")))
        self.structure = QComboBox()
        for label, value in (("Shared X", "shared"), ("Repeated groups", "repeated"),
                             ("Custom", "custom")):
            self.structure.addItem(self.tr(label), value)
        controls.addWidget(self.structure)
        self.add_button = QPushButton(self.tr("Add spectrum"))
        self.remove_button = QPushButton(self.tr("Remove selected"))
        controls.addWidget(self.add_button)
        controls.addWidget(self.remove_button)
        controls.addStretch()
        layout.addLayout(controls)

        self.pattern_controls = QWidget()
        pattern_layout = QHBoxLayout(self.pattern_controls)
        pattern_layout.setContentsMargins(0, 0, 0, 0)
        pattern_layout.addWidget(QLabel(self.tr("First column:")))
        self.first_column = QSpinBox()
        self.first_column.setMinimum(1)
        pattern_layout.addWidget(self.first_column)
        pattern_layout.addWidget(QLabel(self.tr("Y columns per X:")))
        self.y_per_x = QSpinBox()
        self.y_per_x.setRange(1, 1000)
        pattern_layout.addWidget(self.y_per_x)
        pattern_layout.addWidget(QLabel(self.tr("Errors per Y:")))
        self.pattern_error = self._error_combo()
        pattern_layout.addWidget(self.pattern_error)
        self.apply_pattern = QPushButton(self.tr("Apply pattern"))
        self.apply_pattern.setToolTip(self.tr(
            "Replace the associations below using column positions only. "
            "Column names are never used to infer X, Y or errors."))
        pattern_layout.addWidget(self.apply_pattern)
        pattern_layout.addStretch()
        layout.addWidget(self.pattern_controls)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            self.tr("X"), self.tr("Y / name"), self.tr("Error / weight"),
            self.tr("Error / +"), self.tr("Error −"), self.tr("Confidence"),
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(125)
        self.table.setMaximumHeight(230)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(2, 195)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.structure.currentIndexChanged.connect(self._structure_changed)
        self.apply_pattern.clicked.connect(self._apply_pattern)
        self.add_button.clicked.connect(self._add_spectrum)
        self.remove_button.clicked.connect(self._remove_selected)
        self.dialog.x_column.currentIndexChanged.connect(self.sync_shared)
        self.dialog.y_columns.itemChanged.connect(self.sync_shared)
        self.dialog.sigma_x.currentIndexChanged.connect(self._changed)
        self._structure_changed()

    def _error_combo(self):
        combo = QComboBox()
        for label, value in (
            ("None", "none"), ("Symmetric (sigma_y)", "sigma_y"),
            ("Y error (confidence interval)", "interval"),
            ("Asymmetric error (confidence interval)", "asymmetric"),
            ("Weight", "weights"), ("Variance", "variance"),
            ("Inverse variance", "inverse_variance"),
        ):
            combo.addItem(self.tr(label), value)
        return combo

    def _column_combo(self, selected=None, *, optional=False):
        combo = QComboBox()
        if optional:
            combo.addItem(self.tr("None"), None)
        for index, name in enumerate(self.columns):
            combo.addItem(f"{index + 1}: {name}", index)
        combo.setCurrentIndex(max(0, combo.findData(selected)))
        return combo

    def set_columns(self, columns):
        if list(columns) == self.columns:
            self.sync_shared()
            return
        saved = [(self._row_mapping(row, validate=False), self.table.cellWidget(row, 2).currentData())
                 for row in range(self.table.rowCount())] if len(columns) == len(self.columns) else []
        self.columns = list(columns)
        self.first_column.setMaximum(max(1, len(columns)))
        self._updating = True
        self.table.setRowCount(0)
        for spectrum, kind in saved:
            self._add_row(spectrum, error_kind=kind)
        self._updating = False
        if saved:
            self.sync_shared()
            self._changed()
        elif self.structure.currentData() == "shared":
            self.sync_shared()
        elif self.structure.currentData() == "repeated":
            self._apply_pattern()
        else:
            self._add_row(ColumnMapping(x=0, y=[1]))
            self._changed()

    def _structure_changed(self, *_):
        mode = self.structure.currentData()
        self.pattern_controls.setVisible(mode == "repeated")
        self.add_button.setVisible(mode == "custom")
        self.remove_button.setVisible(mode == "custom")
        if mode == "shared":
            self.sync_shared()
        elif mode == "repeated" and self.columns:
            self._apply_pattern()
        elif mode == "custom" and self.columns and not self.table.rowCount():
            self._add_row(ColumnMapping(x=0, y=[1]))
        for row in range(self.table.rowCount()):
            self.table.cellWidget(row, 0).setEnabled(mode != "shared")
            self.table.cellWidget(row, 1).setEnabled(mode != "shared")
        self._changed()

    def sync_shared(self, *_):
        if self._updating or self.structure.currentData() != "shared" or not self.columns:
            return
        if not self.dialog.separated_files.isChecked():
            return
        saved = {self.table.cellWidget(row, 1).currentData(): (
                     self._row_mapping(row, validate=False), self.table.cellWidget(row, 2).currentData())
                 for row in range(self.table.rowCount())}
        self._updating = True
        self.table.setRowCount(0)
        for index in range(self.dialog.y_columns.count()):
            if self.dialog.y_columns.item(index).checkState() == Qt.CheckState.Checked:
                spectrum, kind = saved.get(index, (ColumnMapping(y=[index]), "none"))
                spectrum.x = self.dialog.x_column.currentIndex()
                self._add_row(spectrum, error_kind=kind)
        self._updating = False
        self._changed()

    def _apply_pattern(self):
        spectra = repeated_spectrum_mappings(
            len(self.columns), y_per_x=self.y_per_x.value(),
            error_kind=self.pattern_error.currentData(), first_column=self.first_column.value() - 1,
        )
        self._updating = True
        self.table.setRowCount(0)
        for spectrum in spectra:
            self._add_row(spectrum)
        self._updating = False
        self._changed()

    def _add_spectrum(self):
        used = {self.table.cellWidget(row, 1).currentData() for row in range(self.table.rowCount())}
        x = self.dialog.x_column.currentIndex()
        y = next((index for index in range(len(self.columns)) if index not in used and index != x), 1)
        self._add_row(ColumnMapping(x=x, y=[y]))
        self._changed()

    def _remove_selected(self):
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)
        self._changed()

    def _add_row(self, spectrum, *, error_kind=None):
        row = self.table.rowCount()
        self.table.insertRow(row)
        x = self._column_combo(spectrum.x)
        y = self._column_combo(spectrum.y[0])
        kind = self._error_combo()
        value = "none"
        for name in ("sigma_y", "weights", "variance", "inverse_variance"):
            if getattr(spectrum, name) is not None:
                value = name
        if spectrum.error_y_plus is not None:
            value = "interval" if spectrum.error_y_plus == spectrum.error_y_minus else "asymmetric"
        if error_kind is not None:
            value = error_kind
        kind.setCurrentIndex(kind.findData(value))
        first = next((getattr(spectrum, name) for name in (
            "sigma_y", "weights", "variance", "inverse_variance", "error_y_plus")
            if getattr(spectrum, name) is not None), None)
        plus = self._column_combo(first, optional=True)
        minus = self._column_combo(spectrum.error_y_minus if value == "asymmetric" else None,
                                   optional=True)
        confidence = QDoubleSpinBox()
        confidence.setRange(0.001, 99.999)
        confidence.setDecimals(3)
        confidence.setSuffix(" %")
        confidence.setValue(spectrum.error_confidence_level * 100)
        for column, widget in enumerate((x, y, kind, plus, minus, confidence)):
            self.table.setCellWidget(row, column, widget)
        for combo in (x, plus, minus):
            combo.currentIndexChanged.connect(self._changed)
        confidence.valueChanged.connect(self._changed)
        # Locate the row by its widget: rows can be removed or rebuilt.
        kind.currentIndexChanged.connect(lambda *_: self._error_changed(kind, defaults=True))
        y.currentIndexChanged.connect(lambda *_: self._error_changed(kind, defaults=True))
        self._error_changed(kind, defaults=False)
        shared = self.structure.currentData() == "shared"
        x.setEnabled(not shared)
        y.setEnabled(not shared)

    def _error_changed(self, kind, *, defaults):
        row = next((row for row in range(self.table.rowCount())
                    if self.table.cellWidget(row, 2) is kind), None)
        if row is None:
            return
        value = kind.currentData()
        kind.setToolTip(kind.currentText())
        plus, minus, confidence = (self.table.cellWidget(row, col) for col in (3, 4, 5))
        plus.setEnabled(value != "none")
        minus.setEnabled(value == "asymmetric")
        confidence.setEnabled(value in {"interval", "asymmetric"})
        if defaults:
            y = self.table.cellWidget(row, 1).currentData()
            plus.blockSignals(True)
            minus.blockSignals(True)
            plus.setCurrentIndex(max(0, plus.findData(y + 1)) if value != "none" else 0)
            minus.setCurrentIndex(max(0, minus.findData(y + 2)) if value == "asymmetric" else 0)
            plus.blockSignals(False)
            minus.blockSignals(False)
        self._changed()

    def _row_mapping(self, row, *, validate=True):
        x, y, kind, plus, minus, confidence = (self.table.cellWidget(row, col) for col in range(6))
        sigma_x = self.dialog.sigma_x.currentData()
        spectrum = ColumnMapping(x=x.currentData(), y=[y.currentData()],
                                 sigma_x=self.columns.index(sigma_x) if sigma_x in self.columns else None,
                                 error_confidence_level=confidence.value() / 100)
        value = kind.currentData()
        if value != "none":
            if validate and plus.currentData() is None:
                raise ValueError(self.tr("Select an error/weight column for every spectrum using errors."))
            if value in {"interval", "asymmetric"}:
                spectrum.error_y_plus = plus.currentData()
                spectrum.error_y_minus = (minus.currentData() if value == "asymmetric"
                                          else plus.currentData())
                if (validate and value == "asymmetric"
                        and (minus.currentData() is None or minus.currentData() == plus.currentData())):
                    raise ValueError(self.tr("Asymmetric errors require two distinct error columns."))
            else:
                setattr(spectrum, value, plus.currentData())
        return spectrum

    def mapping(self):
        if not self.table.rowCount():
            if self.structure.currentData() == "repeated":
                raise ValueError(self.tr(
                    "The pattern contains no complete spectrum. Change the pattern or first column."))
            raise ValueError(self.tr("Select at least one Y column or add a spectrum."))
        spectra = [self._row_mapping(row) for row in range(self.table.rowCount())]
        axes = {spectrum.x for spectrum in spectra} | {spectrum.y[0] for spectrum in spectra}
        ys = [spectrum.y[0] for spectrum in spectra]
        if len(set(ys)) != len(ys) or any(spectrum.x in ys for spectrum in spectra):
            raise ValueError(self.tr("Each Y must be distinct and cannot also be assigned as X."))
        for spectrum in spectra:
            for name in ("sigma_x", "sigma_y", "weights", "variance", "inverse_variance",
                         "error_y_plus", "error_y_minus"):
                column = getattr(spectrum, name)
                if column is not None and column in axes:
                    raise ValueError(self.tr("An error/weight column is already assigned as X or Y."))
        mapping = ColumnMapping(as_separated_files=True, spectra=spectra)
        mapping.validate()
        return mapping

    def _changed(self, *_):
        if self._updating:
            return
        try:
            mapping = self.mapping()
            used = set()
            for spectrum in mapping.spectra:
                used.update((spectrum.x, spectrum.y[0]))
                for name in ("sigma_x", "sigma_y", "weights", "variance", "inverse_variance",
                             "error_y_plus", "error_y_minus"):
                    column = getattr(spectrum, name)
                    if column is not None:
                        used.add(column)
            unused = [str(index + 1) for index in range(len(self.columns)) if index not in used]
            message = self.tr("Independent spectra: ") + str(len(mapping.spectra))
            if unused:
                message += self.tr(". Unassigned columns (excluded): ") + ", ".join(unused)
            self.status.setText(message)
        except (ValueError, DataValidationError) as exc:
            self.status.setText(str(exc))
        if hasattr(self.dialog, "spectrum_preview"):
            self.dialog.spectrum_preview.schedule()
