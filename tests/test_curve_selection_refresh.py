from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from curvemole import Curve, Project, Series
from curvemole.gui.app import CurveMoleMainWindow


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    project = Project()
    project.add_series(Series('First', [Curve(str(i), [0., 1., 2.], [i, i + 1, i]) for i in range(3)]))
    project.add_series(Series('Second', [Curve('Other', [0., 1.], [0., 1.])]))
    window = CurveMoleMainWindow(project)
    window.show()
    app.processEvents()
    yield window
    project.dirty = False
    window.close()


@pytest.mark.parametrize('mode', [1, 2])
@pytest.mark.parametrize('operation', ['range', 'point', 'rename', 'reorder'])
def test_edits_and_undo_keep_selected_plot_and_zoom(window, mode, operation):
    tree, plot = window.curve_tree, window.plot_workspace
    curves = window.project.dataset.series[0].curves
    tree.topLevelItem(0).child(2).setSelected(True)
    selected = tree.selected_curve_ids()
    assert len(selected) == 2
    plot.display_mode.setCurrentIndex(mode)
    plot.scope_selected.click()
    plot.view_box.setRange(xRange=(0.2, 1.8), yRange=(-1., 5.), padding=0)
    bounds = np.array(plot.view_box.viewRange())
    active = window.active_curve_id
    selection_signals = QSignalSpy(tree.itemSelectionChanged)
    if operation == 'range':
        window.mask_range(0.5, 1.5)
    elif operation == 'point':
        window.mask_point(1.)
    elif operation == 'rename':
        window._rename_curve(curves[0].id, 'Renamed')
    else:
        window.reorder_curves([curves[0].id], 1)
    for action in (lambda: None, window.undo_stack.undo, window.undo_stack.redo):
        action()
        assert tree.selected_curve_ids() == selected
        assert set(plot._data_items) == selected
        assert window.active_curve_id == active
        np.testing.assert_allclose(plot.view_box.viewRange(), bounds)
    assert selection_signals.count() == 0


def test_refresh_preserves_series_selection_collapse_and_empty_selection(window):
    tree = window.curve_tree
    tree.setCurrentItem(tree.topLevelItem(0))
    tree.topLevelItem(1).setExpanded(False)
    selected = tree.selected_curve_ids()
    window.refresh_all()
    assert tree.selected_curve_ids() == selected
    assert tree.currentItem() is tree.topLevelItem(0)
    assert not tree.topLevelItem(1).isExpanded()
    tree.clearSelection()
    window.refresh_all()
    assert tree.selected_curve_ids() == set()


def test_refresh_prunes_deleted_items_and_resets_for_new_project(window):
    tree = window.curve_tree
    tree.topLevelItem(0).child(2).setSelected(True)
    curves = window.project.dataset.series[0].curves
    removed = curves.pop(2)
    window.refresh_all()
    assert removed.id not in tree.selected_curve_ids()
    assert tree.selected_curve_ids() == {curves[0].id}
    replacement = Project()
    curve = Curve('New', [0., 1.], [0., 1.])
    replacement.add_series(Series('New', [curve]))
    tree.populate(replacement, curve.id)
    assert tree.selected_curve_ids() == {curve.id}
    assert tree.currentItem().data(1, Qt.ItemDataRole.UserRole) == ('curve', curve.id)
