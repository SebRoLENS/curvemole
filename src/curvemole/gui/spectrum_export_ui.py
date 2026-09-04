"""GUI for exporting selected spectra and fitted traces as numeric columns."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.project import Project
from curvemole.core.spectrum_export import SpectrumExportOptions, export_spectra
from curvemole.gui.main_window import MainWindow

_ORIGINAL_BUILD_ACTIONS = MainWindow._build_actions
_ORIGINAL_BUILD_MENUS = MainWindow._build_menus


class SpectrumExportDialog(QDialog):
    def __init__(
        self,
        project: Project,
        active_curve_id: str | None,
        remembered: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle(self.tr("Export spectra and fit curves"))
        self.resize(680, 640)
        layout = QVBoxLayout(self)

        info = QLabel(
            self.tr(
                "CurveMole writes one numeric, multi-column file for each selected spectrum. "
                "The first column is x; the other columns are spectrum/fit y values and have descriptive headers."
            )
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        folder_row = QHBoxLayout()
        initial_directory = remembered or self._source_directory(active_curve_id)
        self.directory = QLineEdit(initial_directory)
        self.directory.setPlaceholderText(self.tr("Export folder"))
        browse = QPushButton(self.tr("Choose folder…"))
        browse.clicked.connect(self._browse)
        folder_row.addWidget(self.directory, 1)
        folder_row.addWidget(browse)
        layout.addLayout(folder_row)

        spectra_box = QGroupBox(self.tr("Spectra to export"))
        spectra_layout = QVBoxLayout(spectra_box)
        self.spectra = QListWidget()
        for index, curve in enumerate(project.curves):
            item = QListWidgetItem(curve.name)
            item.setData(Qt.ItemDataRole.UserRole, curve.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = curve.id == active_curve_id or (active_curve_id is None and index == 0)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.spectra.addItem(item)
        spectra_layout.addWidget(self.spectra)
        selection_row = QHBoxLayout()
        select_all = QPushButton(self.tr("Select all"))
        deselect_all = QPushButton(self.tr("Deselect all"))
        select_all.clicked.connect(lambda: self._set_all_checked(True))
        deselect_all.clicked.connect(lambda: self._set_all_checked(False))
        selection_row.addWidget(select_all)
        selection_row.addWidget(deselect_all)
        selection_row.addStretch(1)
        spectra_layout.addLayout(selection_row)
        layout.addWidget(spectra_box, 1)

        data_box = QGroupBox(self.tr("Spectrum data"))
        data_layout = QVBoxLayout(data_box)
        data_layout.addWidget(
            QLabel(self.tr("The spectrum itself is always exported together with its x column."))
        )
        self.subtract_background = QCheckBox(
            self.tr("Export spectrum with fitted background subtracted")
        )
        self.unmasked_only = QCheckBox(self.tr("Export only non-masked points"))
        data_layout.addWidget(self.subtract_background)
        data_layout.addWidget(self.unmasked_only)
        layout.addWidget(data_box)

        fit_box = QGroupBox(self.tr("Additional fitted traces"))
        fit_layout = QVBoxLayout(fit_box)
        self.include_components = QCheckBox(
            self.tr("Individual fit functions/components")
        )
        self.include_total_fit = QCheckBox(self.tr("Total fit (sum/model result)"))
        self.include_residual = QCheckBox(self.tr("Residuals (data - total fit)"))
        self.include_background = QCheckBox(self.tr("Combined fitted background"))
        for widget in (
            self.include_components,
            self.include_total_fit,
            self.include_residual,
            self.include_background,
        ):
            widget.setChecked(True)
            fit_layout.addWidget(widget)
        layout.addWidget(fit_box)

        note = QLabel(
            self.tr(
                "Each output is named <spectrum>_curvemole.<original extension>. "
                "The original delimiter is retained when possible; otherwise a tab-delimited table is used."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_curve_ids(self) -> list[str]:
        selected = {
            str(self.spectra.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.spectra.count())
            if self.spectra.item(index).checkState() == Qt.CheckState.Checked
        }
        return [curve.id for curve in self.project.curves if curve.id in selected]

    def options(self) -> SpectrumExportOptions:
        return SpectrumExportOptions(
            subtract_background=self.subtract_background.isChecked(),
            unmasked_only=self.unmasked_only.isChecked(),
            include_background=self.include_background.isChecked(),
            include_components=self.include_components.isChecked(),
            include_total_fit=self.include_total_fit.isChecked(),
            include_residual=self.include_residual.isChecked(),
        )

    def _source_directory(self, curve_id: str | None) -> str:
        if curve_id is None:
            return ""
        try:
            source = self.project.dataset.curve(curve_id).source
        except KeyError:
            return ""
        if not source:
            return ""
        return str(Path(source).expanduser().parent)

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            self.tr("Choose export folder"),
            self.directory.text().strip() or str(Path.home()),
        )
        if selected:
            self.directory.setText(selected)

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for index in range(self.spectra.count()):
            self.spectra.item(index).setCheckState(state)

    def _accept(self) -> None:
        if not self.directory.text().strip():
            QMessageBox.warning(self, self.tr("Export spectra"), self.tr("Choose an export folder."))
            return
        if not self.selected_curve_ids():
            QMessageBox.warning(
                self,
                self.tr("Export spectra"),
                self.tr("Select at least one spectrum to export."),
            )
            return
        self.accept()


def _build_actions(window: MainWindow) -> None:
    _ORIGINAL_BUILD_ACTIONS(window)
    window.export_spectra_action = QAction(
        window.tr("Export spectra and fit curves…"), window
    )
    window.export_spectra_action.setShortcut("Ctrl+Shift+E")
    window.export_spectra_action.triggered.connect(
        lambda checked=False: window.export_spectra_data()
    )


def _build_menus(window: MainWindow) -> None:
    _ORIGINAL_BUILD_MENUS(window)
    for menu_action in window.menuBar().actions():
        menu = menu_action.menu()
        if menu is not None and window.export_action in menu.actions():
            menu.insertAction(window.export_action, window.export_spectra_action)
            break


def _export_spectra_data(window: MainWindow) -> None:
    if not window.project.curves:
        window._notify(window.tr("Import data before exporting spectra."), warning=True)
        return
    remembered = str(window.settings.value("spectrum_export_directory", ""))
    dialog = SpectrumExportDialog(
        window.project,
        window.active_curve_id,
        remembered or None,
        window,
    )
    if dialog.exec() != dialog.DialogCode.Accepted:
        return
    try:
        destination = dialog.directory.text().strip()
        created = export_spectra(
            window.project,
            destination,
            dialog.selected_curve_ids(),
            options=dialog.options(),
            registry=window.registry,
        )
        window.settings.setValue("spectrum_export_directory", destination)
        window._notify(
            window.tr("Spectrum export complete: ")
            + f"{len(created)} "
            + window.tr("file(s) written.")
        )
    except Exception as exc:
        window._show_error(window.tr("Export spectra"), exc)


def _install() -> None:
    if getattr(MainWindow, "_curvemole_spectrum_export_ui", False):
        return
    MainWindow._build_actions = _build_actions
    MainWindow._build_menus = _build_menus
    MainWindow.export_spectra_data = _export_spectra_data
    MainWindow._curvemole_spectrum_export_ui = True


_install()
