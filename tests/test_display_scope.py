from __future__ import annotations

from PySide6.QtWidgets import QApplication

from curvemole import Curve, Project, Series
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.background_navigation import _displayed_curves


def test_one_click_scope_limits_rendering_ranges_masks_and_waterfall_offsets():
    app = QApplication.instance() or QApplication([])
    project = Project()
    first = Series("First", [Curve("A", [0., 1.], [0., 1.])])
    second = Series("Second", [Curve("B", [10., 11.], [2., 3.]), Curve("C", [12., 13.], [4., 5.])])
    project.add_series(first)
    project.add_series(second)
    window = CurveMoleMainWindow(project)
    window.show()
    plot = window.plot_workspace
    plot.display_mode.setCurrentIndex(1)
    assert plot.scope_project.isEnabled()
    assert len(plot._data_items) == 3
    plot.scope_series.click()
    assert set(plot._data_items) == {first.curves[0].id}
    # Selecting a series header follows that series without a scope dialog.
    window.curve_tree.setCurrentItem(window.curve_tree.topLevelItem(1))
    app.processEvents()
    expected = {curve.id for curve in second.curves}
    assert set(plot._data_items) == expected
    assert window.curve_tree.selected_curve_ids() == expected
    assert {curve.id for curve in _displayed_curves(plot)[0]} == expected
    plot._mask_scope = "visible"
    assert {curve.id for curve in window._mask_targets()} == expected
    plot.display_mode.setCurrentIndex(2)
    plot.x_offset.setValue(2.)
    plot.y_offset.setValue(3.)
    window._set_active_curve(second.curves[1].id)
    assert plot._active_display_offsets() == (2., 3.)
    plot.auto_range()
    low, high = plot.view_box.viewRange()[0]
    assert low > 5 and high > 15
    second.curves[0].visible = False
    window.refresh_all()
    assert set(plot._data_items) == {second.curves[1].id}
    assert plot._active_display_offsets() == (0., 0.)
    plot.scope_project.click()
    assert len(plot._data_items) == 2
    plot.display_mode.setCurrentIndex(0)
    assert not plot.scope_series.isEnabled()
    assert set(plot._data_items) == {second.curves[1].id}
    project.dirty = False
    window.close()
