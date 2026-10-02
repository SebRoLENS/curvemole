from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.core.fitting import FitSettings
from curvemole.core.importers import import_file
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.dialogs import FitPlanDialog, ImportMappingDialog


def test_import_asymmetric_confidence_and_live_error_bar_preview(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "errors.csv"
    path.write_text("x,y,plus,minus\n0,4,3,1\n1,5,4,2\n2,6,5,3\n")
    dialog = ImportMappingDialog(path)
    try:
        assert dialog.error_confidence.value() == 95
        dialog.asymmetric_error.setChecked(True)
        assert not dialog.uncertainty_kind.isEnabled()
        dialog.error_plus_column.setCurrentText("plus")
        dialog.error_minus_column.setCurrentText("minus")
        dialog.error_confidence.setValue(90)
        curve = import_file(path, dialog.mapping(), dialog.config())[0]
        assert curve.error_confidence_level == .9
        np.testing.assert_array_equal(curve.error_y_plus, [3, 4, 5])
        dialog.spectrum_preview.refresh()
        bars = dialog.spectrum_preview.graph.listDataItems()[1]
        _, values = bars.getOriginalDataset()
        assert np.nanmax(values) == 11
        assert dialog.spectrum_preview.graph.viewRange()[1][1] >= 11
        dialog.asymmetric_error.setChecked(False)
        dialog.uncertainty_kind.setCurrentIndex(2)
        dialog.uncertainty_column.setCurrentText("plus")
        symmetric = import_file(path, dialog.mapping(), dialog.config())[0]
        np.testing.assert_array_equal(symmetric.error_y_minus, symmetric.error_y_plus)
        assert symmetric.error_confidence_level == .9
    finally:
        dialog.close()
        app.processEvents()


def test_advanced_weighting_toggle_saved_and_reset():
    app = QApplication.instance() or QApplication([])
    project = Project()
    curve = Curve("data", [0, 1], [1, 2])
    project.add_curve(curve)
    dialog = FitPlanDialog(project, {curve.id}, FitSettings(use_data_errors=False))
    try:
        assert not dialog.use_data_errors.isChecked()
        assert dialog.use_data_errors.parent() is dialog.solver_options
        dialog.advanced_toggle.setChecked(True)
        assert not dialog.plan().settings.use_data_errors
        dialog.use_data_errors.setChecked(True)
        assert dialog.plan().settings.use_data_errors
        dialog.use_data_errors.setChecked(False)
        dialog.reset_defaults.click()
        assert dialog.plan().settings.use_data_errors
    finally:
        dialog.close()
        app.processEvents()


def test_plot_bars_keep_raw_ci_and_toggle_does_not_change_fit_choice():
    app = QApplication.instance() or QApplication([])
    curve = Curve("intervals", [0, 1, 2], [4, 5, 6],
                  error_y_minus=[1, 2, 3], error_y_plus=[3, 4, 5])
    project = Project()
    project.add_curve(curve)
    window = CurveMoleMainWindow(project)
    try:
        workspace = window.plot_workspace
        bars = workspace._error_items[curve.id]
        _, values = bars.getOriginalDataset()
        assert np.nanmax(values) == 11
        assert np.nanmin(values) == 3
        assert window.fit_settings.use_data_errors
        workspace.error_bars_toggle.setChecked(False)
        assert not workspace._error_items
        assert window.fit_settings.use_data_errors
        assert project.ui_state["show_error_bars"] is False
        workspace.error_bars_toggle.setChecked(True)
        workspace._fit_experimental_data(active_only=True)
        assert workspace.plot.viewRange()[1][1] >= 11
        workspace.set_log_y(True)
        app.processEvents()
        _, displayed_y = workspace._error_items[curve.id].getData()
        assert np.nanmax(displayed_y) == np.log10(11)
        workspace.set_log_y(False)
        background = Component.create("constant", initial={"offset": 2.})
        background.is_background = True
        project.model_for(curve.id).add(background)
        workspace.set_background_subtracted_view(True)
        _, values = workspace._error_items[curve.id].getOriginalDataset()
        assert np.nanmax(values) == 9
        assert np.nanmin(values) == 1
        np.testing.assert_array_equal(curve.current_error_y_plus, [3, 4, 5])
    finally:
        project.dirty = False
        window.close()
        app.processEvents()
