import numpy as np
import pytest
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.core.extensions import Contribution, extensions
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.plugin_services import PluginServices


@pytest.fixture
def preview_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    monkeypatch.setattr('curvemole.gui.main_window.QSettings', lambda *args: settings)
    monkeypatch.setenv('CURVEMOLE_DISABLE_PLUGINS', '1')
    project = Project('Generic plugin previews')
    curve = Curve('Samples', np.arange(1., 10.), [2, 2, 3, 5, 8, 5, 3, 2, 2])
    project.add_curve(curve)
    main = CurveMoleMainWindow(project)
    main.resize(1400, 900)
    main.show()
    app.processEvents()
    owner = 'test.generic_preview'
    monkeypatch.setattr(extensions, 'entries', {
        owner: Contribution(owner, owner, 'Preview tool', 'panels', lambda ctx: None)
    })
    service = PluginServices(main.plugin_host, owner)
    session = service.plot_session(curve.id)
    main.plot_workspace.view_box.setRange(xRange=(0, 10), yRange=(0, 10), padding=0)
    yield app, main, curve, service, session
    for active in list(main.plot_workspace._plugin_plot_sessions.values()):
        active.close()
    main.project.dirty = False
    main.close()
    main.deleteLater()
    app.processEvents()


def click(main, x, y):
    QApplication.instance().processEvents()
    ws = main.plot_workspace
    position = ws.graphics.mapFromScene(ws.view_box.mapViewToScene(QPointF(x, y)))
    QTest.mouseClick(ws.graphics.viewport(), Qt.MouseButton.LeftButton, pos=position)
    QApplication.instance().processEvents()


def test_generic_previews_reuse_main_graph_without_mutation_or_navigation_changes(preview_window):
    _, main, curve, service, session = preview_window
    ws = main.plot_workspace
    before = curve.content_hash
    view = np.array(ws.view_box.viewRange())
    assert service.plot_session(curve.id) is session
    session.set_preview(segments=[{'indices': [3, 4, 5], 'y': [5, 5, 5]}],
                        markers=[{'index': 4, 'colour': '#ff0000'}], selected_interval=(3, 5))
    assert len(session._items) == 3
    np.testing.assert_array_equal(session._items[0].getOriginalDataset()[0], [4, 5, 6])
    np.testing.assert_array_equal(session._items[0].getOriginalDataset()[1], [5, 5, 5])
    assert all(item in ws.plot.items for item in session._items)
    main.refresh_all()
    assert len(session._items) == 3 and not session.closed
    np.testing.assert_allclose(ws.view_box.viewRange(), view)
    assert curve.content_hash == before and main.undo_stack.count() == 0
    assert len(ws._data_items) == 1
    session.set_preview()
    assert not session._items and not session.closed


def test_marker_review_and_exclusive_real_sample_picking(preview_window):
    app, main, curve, _, session = preview_window
    selected, picked, modes = [], [], []
    session.markerClicked.connect(selected.append)
    session.sampleClicked.connect(picked.append)
    session.pickingChanged.connect(modes.append)
    session.set_preview(markers=[{'index': 4}])
    click(main, 5, 8)
    assert selected == [0]
    session.set_picking(True)
    click(main, 5, 8)
    click(main, 9, 9)
    assert picked == [4]
    QTest.keyClick(main.plot_workspace.graphics.viewport(), Qt.Key.Key_Escape)
    assert not session.picking and modes == [True, False]
    session.set_picking(True)
    main.edit_data_points_action.setChecked(True)
    assert not session.picking and main.plot_workspace.point_editor.active
    assert main.plot_workspace.view_box.interaction_mode == 'data_points'
    assert main.undo_stack.count() == 0
    main.plot_workspace.point_editor.finish()
    session.set_picking(True)
    main.plot_workspace.begin_peak_placement('Gaussian')
    assert not session.picking and main.plot_workspace.view_box.interaction_mode == 'peak'
    main.plot_workspace.cancel_placement()
    session.set_picking(True)
    main.plot_workspace.mask_toggle.setChecked(True)
    assert not session.picking and main.plot_workspace.view_box.mask_mode
    main.plot_workspace.mask_toggle.setChecked(False)
    app.processEvents()
    assert curve.y[4] == 8


@pytest.mark.parametrize('change', ['data', 'active', 'project', 'hidden', 'disabled'])
def test_previews_and_picking_expire_on_context_changes(preview_window, monkeypatch, change):
    _, main, curve, _, session = preview_window
    session.set_preview(markers=[{'index': 4}])
    session.set_picking(True)
    expired = []
    session.invalidated.connect(lambda: expired.append(True))
    if change == 'data':
        curve.move_points([4], y=[6])
    elif change == 'active':
        other = Curve('Other', [1, 2, 3], [2, 3, 4])
        main.project.add_curve(other)
        main.active_curve_id = other.id
    elif change == 'project':
        main.project = Project('Other project')
        main.active_curve_id = None
    elif change == 'hidden':
        main.plot_workspace.display_mode.setCurrentIndex(1)
        curve.visible = False
    else:
        monkeypatch.setattr(extensions, 'entries', {})
    main.refresh_all()
    assert session.closed and not session.picking and not session._items
    assert expired == [True]
    assert not main.plot_workspace._plugin_plot_sessions


def test_preview_coordinates_follow_log_waterfall_and_background_view(preview_window):
    _, main, curve, _, session = preview_window
    ws = main.plot_workspace
    other = Curve('First', [1., 5., 10.], [1., 2., 1.])
    main.project.add_curve(other)
    main.project.dataset.series[0].curves.reverse()
    ws.display_mode.setCurrentIndex(2)
    ws.x_offset.setValue(2)
    ws.y_offset.setValue(3)
    model = main.project.model_for(curve.id)
    component = Component.create('constant', initial={'offset': 1})
    component.is_background = True
    model.add(component)
    ws._background_subtracted_view = True
    main.refresh_all()
    ws.set_log_x(True)
    ws.set_log_y(True)
    session.set_preview(segments=[{'indices': [3, 4, 5], 'y': [5, 5, 5]}], markers=[{'index': 4}],
                        selected_interval=(3, 5))
    dx, dy = ws._active_display_offsets()
    assert dx == 2 and dy == 3
    np.testing.assert_array_equal(session._items[0].getOriginalDataset()[0], [6, 7, 8])
    np.testing.assert_array_equal(session._items[0].getOriginalDataset()[1], [7, 7, 7])
    position = ws.view_box.mapViewToScene(QPointF(np.log10(7), np.log10(10)))
    assert session.marker_at(position) == 0
    picked = []
    session.sampleClicked.connect(picked.append)
    session.set_picking(True)
    QApplication.instance().processEvents()
    position = ws.view_box.mapViewToScene(QPointF(np.log10(7), np.log10(10)))
    session.pick(position)
    assert picked == [4]


def test_invalid_previews_leave_existing_overlay_intact(preview_window):
    _, main, _, service, session = preview_window
    session.set_preview(markers=[{'index': 4}])
    items = list(session._items)
    for kwargs in ({'segments': [{'indices': [100], 'y': [3]}]},
                   {'segments': [{'indices': [1, 2], 'y': [3]}]},
                   {'markers': [{'index': True}]}, {'selected_interval': (2,)}):
        with pytest.raises(ValueError):
            session.set_preview(**kwargs)
        assert session._items == items
    with pytest.raises(ValueError, match='active spectrum'):
        service.plot_session('stale')
    assert main.undo_stack.count() == 0


def test_multiple_plugin_sessions_share_plot_but_have_exclusive_picking(preview_window):
    _, main, curve, _, first = preview_window
    owner = 'test.another_preview'
    extensions.entries[owner] = Contribution(owner, owner, 'Other preview', 'panels', lambda ctx: None)
    second = PluginServices(main.plugin_host, owner).plot_session(curve.id)
    first.set_preview(markers=[{'index': 3}])
    second.set_preview(markers=[{'index': 5}])
    first.set_picking(True)
    second.set_picking(True)
    assert not first.picking and second.picking
    first.close()
    assert second.picking and second._items
    second.set_picking(False)
    main._thread = object()
    try:
        with pytest.raises(ValueError, match='calculation'):
            second.set_picking(True)
    finally:
        main._thread = None
    curve.mask_point(6)
    main.refresh_all()
    assert second.closed
    second = PluginServices(main.plugin_host, owner).plot_session(curve.id)
    second.set_preview(markers=[{'index': 5}])
    assert not second._items
