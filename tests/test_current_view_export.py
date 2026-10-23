from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QFileDialog

from curvemole import Component, Curve, Project
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.current_view_export import capture_plot_snapshot


def test_snapshot_preserves_scope_offsets_background_zoom_and_owns_arrays():
    app = QApplication.instance() or QApplication([])
    project = Project("snapshot")
    curves = [Curve(name, [1., 2., 3.], [3., 4., 5.], sigma_y=[.1, .2, .3])
              for name in ("A", "B", "hidden")]
    for curve in curves:
        project.add_curve(curve)
        background = Component.create("constant", initial={"offset": 2.})
        background.is_background = True
        project.model_for(curve.id).add(background)
    curves[-1].visible = False
    window = CurveMoleMainWindow(project)
    plot = window.plot_workspace
    plot.display_mode.setCurrentIndex(2)
    plot.scope_project.setChecked(True)
    plot.x_offset.setValue(5.)
    plot.y_offset.setValue(7.)
    window.background_subtracted_view_action.setChecked(True)
    plot.error_bars_toggle.setChecked(True)
    plot.view_box.setRange(xRange=(1.2, 7.7), yRange=(-.2, 10.), padding=0)
    snapshot = capture_plot_snapshot(plot)
    data = [trace for trace in snapshot.traces if trace.kind == "data"]
    assert [trace.label for trace in data] == ["A", "B"]
    np.testing.assert_allclose(data[1].x, [6., 7., 8.])
    np.testing.assert_allclose(data[1].y, [8., 9., 10.])
    np.testing.assert_allclose(data[1].y_error_minus, [.1, .2, .3])
    assert snapshot.x_range == pytest.approx((1.2, 7.7))
    before = data[0].y.copy()
    plot._data_items[curves[0].id].setData([1., 2.], [42., 43.])
    np.testing.assert_array_equal(data[0].y, before)
    project.dirty = False
    window.close()
    app.processEvents()


def test_snapshot_uses_raw_values_once_on_log_axes_and_hides_residuals():
    app = QApplication.instance() or QApplication([])
    project = Project("log view")
    curve = Curve("data", [1., 10., 100.], [10., 100., 1000.])
    project.add_curve(curve)
    window = CurveMoleMainWindow(project)
    plot = window.plot_workspace
    plot.plot.setLogMode(x=True, y=True)
    plot.view_box.setRange(xRange=(0., 2.), yRange=(1., 3.), padding=0)
    plot.residual_toggle.setChecked(False)
    plot.set_reverse_x(True)
    plot.set_reverse_y(True)
    snapshot = capture_plot_snapshot(plot)
    assert snapshot.log_x and snapshot.log_y
    np.testing.assert_array_equal(snapshot.traces[0].x, curve.x)
    assert snapshot.x_range == pytest.approx((100., 1.))
    assert snapshot.y_range == pytest.approx((1000., 10.))
    assert not snapshot.residuals
    project.dirty = False
    window.close()
    app.processEvents()


def test_file_menu_quick_exports_and_current_view_file(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    project = Project("quick export")
    project.add_curve(Curve("A", [0., 1.], [1., 2.]))
    window = CurveMoleMainWindow(project)
    for action in (window.export_view_action, window.export_spectra_action, window.export_parameters_action):
        assert "Quick export" in action.text()
    output = tmp_path / "view.svg"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(output), "SVG figure (*.svg)"))
    window.export_current_view()
    assert output.is_file() and "<svg" in output.read_text()
    project.dirty = False
    window.close()
    app.processEvents()


def test_snapshot_includes_visible_masked_samples_and_ranges():
    app = QApplication.instance() or QApplication([])
    project = Project("masked")
    curve = Curve("A", np.arange(8.), np.arange(8.) + 1.)
    project.add_curve(curve)
    curve.mask_interval(1., 3.)
    curve.mask_point(6.)
    window = CurveMoleMainWindow(project)
    snapshot = capture_plot_snapshot(window.plot_workspace)
    masked = [trace for trace in snapshot.traces if trace.kind == "masked"]
    assert masked
    actual = np.sort(np.concatenate([trace.x for trace in masked]))
    np.testing.assert_array_equal(actual, curve.x[curve.effective_mask])
    project.dirty = False
    window.close()
    app.processEvents()


def test_bundle_uses_named_destination_and_snapshot_from_button_press(tmp_path, monkeypatch):
    from curvemole.core.export import ExportSummary
    from curvemole.gui import main_window
    from curvemole.gui.dialogs import ExportBundleDialog

    app = QApplication.instance() or QApplication([])
    project = Project("bundle view")
    curve = Curve("A", [0., 1.], [1., 2.])
    project.add_curve(curve)
    window = CurveMoleMainWindow(project)
    def accept(dialog):
        dialog.directory.setText(str(tmp_path))
        dialog.folder_name.setText("chosen-bundle")
        window.plot_workspace._data_items[curve.id].setData([0., 1.], [20., 30.])
        return dialog.DialogCode.Accepted
    def export(project, directory, **options):
        assert directory == tmp_path / "chosen-bundle"
        np.testing.assert_array_equal(options["current_view"].traces[0].y, [1., 2.])
        assert all(options["selection"].to_dict().values())
        return ExportSummary(directory)
    monkeypatch.setattr(ExportBundleDialog, "exec", accept)
    monkeypatch.setattr(main_window, "export_bundle", export)
    window.export_analysis()
    project.dirty = False
    window.close()
    app.processEvents()


def test_point_only_snapshot_preserves_marker_colour():
    app = QApplication.instance() or QApplication([])
    project = Project("colours")
    curve = Curve("data", [0., 1.], [1., 2.])
    project.add_curve(curve)
    window = CurveMoleMainWindow(project)
    item = window.plot_workspace._data_items[curve.id]
    item.setPen(None)
    item.setSymbol("o")
    item.setSymbolBrush("#123456")
    snapshot = capture_plot_snapshot(window.plot_workspace)
    assert snapshot.traces[0].color == "#123456"
    assert snapshot.traces[0].line_style == "none"
    project.dirty = False
    window.close()
    app.processEvents()
