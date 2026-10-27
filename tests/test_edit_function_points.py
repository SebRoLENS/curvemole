from __future__ import annotations

import copy

import numpy as np
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.core.calculator import apply_background_subtraction
from curvemole.core.display import DisplayOptions
from curvemole.core.serialization import load_project, save_project
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.manual_points import initialise_component_from_points
from curvemole.gui.manual_points_live import _set_stored_points


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "edit.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    p = Project("Point edit")
    p.add_curve(Curve("curve", np.linspace(0, 2, 21), np.linspace(3, 5, 21)))
    p.add_curve(Curve("other", np.linspace(0, 2, 21), np.linspace(6, 8, 21)))
    win = CurveMoleMainWindow(p)
    win.show()
    app.processEvents()
    yield app, win
    win.plot_workspace.cancel_placement()
    win.project.dirty = False
    win.close()
    app.processEvents()


def add_points(win, function_id="polynomial", background=False):
    points = [(0., 2.), (1., 3.), (2., 2.)]
    component = Component.create(function_id, registry=win.registry,
                                 metadata={"x_nodes": [0., 1., 2.]} if function_id == "cubic_spline" else {})
    initialise_component_from_points(component, points, registry=win.registry)
    _set_stored_points(component, points)
    component.is_background = background
    win.project.model_for(win.active_curve_id).add(component)
    win.selected_component_id = component.id
    win.refresh_all()
    win._set_component(component.id)
    win.project.dirty = False
    return component


@pytest.mark.parametrize("function_id", ["polynomial", "cubic_spline", "linear", "gaussian"])
def test_reopen_add_delete_move_and_finish_is_one_undoable_edit(window, function_id):
    _, win = window
    component = add_points(win, function_id)
    before = copy.deepcopy(component.to_dict())
    curve_y = win.project.curves[0].y.copy()
    history = win.undo_stack.count()
    assert win.model_panel.edit_points_button.isEnabled()
    win.edit_points_action.trigger()
    workspace = win.plot_workspace
    assert win._function_point_editor.active
    assert workspace.placement_editor.mode.currentData() == "move"
    assert workspace._spline_points == [(0., 2.), (1., 3.), (2., 2.)]
    workspace._spline_points[1] = (1., 4.)
    workspace._render_placement_preview()
    workspace._add_spline_point(3., 2.)
    workspace._remove_spline_point(0., 2.)
    workspace.finish_placement()
    assert not win._function_point_editor.active
    after = win.project.model_for(win.active_curve_id).component(component.id)
    assert after.id == component.id
    assert after.metadata["_manual_points"] == [[1., 4.], [2., 2.], [3., 2.]]
    assert len(win.project.model_for(win.active_curve_id).components) == 1
    assert win.undo_stack.count() == history + 1
    np.testing.assert_array_equal(win.project.curves[0].y, curve_y)
    win.undo_stack.undo()
    assert win.project.model_for(win.active_curve_id).component(component.id).to_dict() == before
    win.undo_stack.redo()
    assert win.project.model_for(win.active_curve_id).component(component.id).metadata["_manual_points"][0] == [1., 4.]


@pytest.mark.parametrize("background", [False, True])
def test_cancel_restores_function_view_and_data_without_an_undo_entry(window, background):
    _, win = window
    component = add_points(win, background=background)
    controller = win.view_options_controller
    controller.apply({c.id: DisplayOptions(background="subtract") for c in win.project.curves})
    before_options = dict(controller.options)
    before_model = copy.deepcopy(component.to_dict())
    before_y = win.project.curves[0].y.copy()
    undo_count = win.undo_stack.count()
    win.edit_component_points(component.id)
    assert controller.for_curve(win.active_curve_id).background == ("restore" if background else "subtract")
    other_id = win.project.curves[1].id
    assert controller.for_curve(other_id) == before_options[other_id]
    win.plot_workspace._add_spline_point(3., 8.)
    win.plot_workspace.cancel_placement()
    assert not win._function_point_editor.active
    assert controller.options == before_options
    assert win.project.model_for(win.active_curve_id).component(component.id).to_dict() == before_model
    assert win.undo_stack.count() == undo_count
    assert not win.project.dirty
    np.testing.assert_array_equal(win.project.curves[0].y, before_y)


def test_subtracted_background_uses_unsubtracted_preview_and_preserves_recorded_operations(window):
    _, win = window
    component = add_points(win, background=True)
    curve = win.project.curves[0]
    apply_background_subtraction(curve, np.full(len(curve), 2.), method="model", description="background",
                                 parameters={"component_ids": [component.id]})
    component.enabled = False
    win.refresh_all()
    before_y = curve.y.copy()
    before_transformations = list(curve.transformations)
    win.edit_component_points(component.id)
    assert win.view_options_controller.for_curve(curve.id).background == "restore"
    np.testing.assert_allclose(win.plot_workspace.curve_for_display(curve).y, before_y + 2)
    win.plot_workspace._add_spline_point(3., 4.)
    win.plot_workspace.finish_placement()
    assert not win._function_point_editor.active
    np.testing.assert_array_equal(curve.y, before_y)
    assert curve.transformations == before_transformations
    assert not win.project.model_for(curve.id).component(component.id).enabled
    assert win.view_options_controller.for_curve(curve.id) == DisplayOptions()


def test_degree_changes_preserve_identity_and_reject_deleted_link_targets(window):
    _, win = window
    component = add_points(win)
    linked = Component.create("constant")
    linked.parameters["offset"].link = f"${{{win.active_curve_id}.{component.id}.c2}}"
    win.project.model_for(win.active_curve_id).add(linked)
    win.refresh_all()
    win._set_component(component.id)
    win.edit_component_points(component.id)
    win.plot_workspace._remove_spline_point(2., 2.)
    win.plot_workspace.finish_placement()
    assert win._function_point_editor.active
    assert "c2" in win.project.model_for(win.active_curve_id).component(component.id).parameters
    win.plot_workspace._add_spline_point(2., 4.)
    win.plot_workspace.finish_placement()
    assert not win._function_point_editor.active
    assert "c2" in win.project.model_for(win.active_curve_id).component(component.id).parameters
    win.project.resolved_parameter_values()


def test_edit_survives_project_round_trip_and_curve_switch_cancels(window, tmp_path):
    _, win = window
    component = add_points(win, "cubic_spline")
    path = tmp_path / "points.fitproj"
    save_project(win.project, path)
    loaded = load_project(path)
    win.project = loaded
    win.refresh_all()
    win._set_component(component.id)
    win.edit_component_points(component.id)
    assert win._function_point_editor.active
    win._set_active_curve(loaded.curves[1].id)
    assert not win._function_point_editor.active
    assert loaded.models[loaded.curves[0].id].component(component.id).metadata["_manual_points"] == [[0., 2.], [1., 3.], [2., 2.]]


def test_legacy_graphical_peak_can_reopen_and_keeps_normal_width_handles(window):
    import pyqtgraph as pg

    _, win = window
    component = Component.create("gaussian", initial={"area": 10., "center": 1., "sigma": 0.3})
    win.project.model_for(win.active_curve_id).add(component)
    win.selected_component_id = component.id
    win.refresh_all()
    win._set_component(component.id)
    assert win.edit_points_action.isEnabled()
    win.edit_component_points(component.id)
    assert len(win.plot_workspace._spline_points) >= 3
    win.plot_workspace.finish_placement()
    assert not win._function_point_editor.active
    win._set_component(component.id)
    assert any(isinstance(item, pg.InfiniteLine) for item in win.plot_workspace._handles)
    assert all(not p.fixed for p in win.project.model_for(win.active_curve_id).component(component.id).parameters.values())


def test_changing_selected_function_cancels_point_edit(window):
    _, win = window
    component = add_points(win, background=True)
    another = Component.create("constant")
    win.project.model_for(win.active_curve_id).add(another)
    win.refresh_all()
    win._set_component(component.id)
    win.edit_component_points(component.id)
    assert win._function_point_editor.active
    win._set_component(another.id)
    assert not win._function_point_editor.active
    assert win.view_options_controller.for_curve(win.active_curve_id) == DisplayOptions()


def test_read_only_function_cannot_enter_point_edit(window):
    _, win = window
    component = add_points(win)
    win.project.read_only = True
    win._set_component(component.id)
    assert not win.edit_points_action.isEnabled()
    win.edit_component_points(component.id)
    assert not win._function_point_editor.active
    assert win.plot_workspace._placement_mode is None
    win.project.read_only = False


def test_edit_uses_selected_spectrum_identity_in_all_functions_view(window):
    _, win = window
    other = win.project.curves[1]
    component = Component.create("linear")
    initialise_component_from_points(component, [(0., 6.), (2., 8.)], registry=win.registry)
    _set_stored_points(component, [(0., 6.), (2., 8.)])
    win.project.model_for(other.id).add(component)
    win.refresh_all()
    win.model_panel.show_all_functions.setChecked(True)
    assert win.model_panel.select_component_ref(other.id, component.id)
    win._set_component(component.id)
    assert win.active_curve_id != other.id
    win.edit_points_action.trigger()
    assert win.active_curve_id == other.id
    assert win._function_point_editor.active
    assert win._pending_component.id == component.id
    win.plot_workspace.cancel_placement()
