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
    assert win.edit_points_action.isEnabled()
    assert not hasattr(win.model_panel, "edit_points_button")
    win.edit_points_action.trigger()
    workspace = win.plot_workspace
    assert win._function_point_editor.active
    assert workspace.placement_editor.mode.currentData() == "move"
    assert workspace._spline_points == [(0., 2.), (1., 3.), (2., 2.)]
    workspace._spline_points[1] = (1., 4.)
    workspace._render_placement_preview()
    tail = .5 if function_id == "gaussian" else 2.
    workspace._add_spline_point(3., tail)
    workspace._remove_spline_point(0., 2.)
    workspace.finish_placement()
    assert not win._function_point_editor.active
    after = win.project.model_for(win.active_curve_id).component(component.id)
    assert after.id == component.id
    assert after.metadata["_manual_points"] == [[1., 4.], [2., 2.], [3., tail]]
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
    updated = win.project.model_for(curve.id).component(component.id)
    background = win.registry.get(updated.function_id).evaluate(curve.x,
        {n: p.value for n, p in updated.parameters.items()}, updated.metadata)
    np.testing.assert_allclose(curve.y, curve.original_y-background)
    assert len(curve.transformations) == len(before_transformations)
    assert curve.transformations[0].created_at == before_transformations[0].created_at
    win.undo_stack.undo()
    np.testing.assert_array_equal(curve.y, before_y)
    win.undo_stack.redo()
    np.testing.assert_allclose(curve.y, curve.original_y-background)
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


@pytest.mark.parametrize("function_id", ["gaussian", "lorentzian", "voigt", "pseudo_voigt"])
@pytest.mark.parametrize("area", [10., -10.])
def test_peak_edit_noop_preserves_exact_current_shape(window, function_id, area):
    _, win = window
    component = Component.create(function_id, registry=win.registry)
    component.parameters["area"].value = area
    component.parameters["center"].value = 500.
    for name in ("sigma", "gamma", "fwhm"):
        if name in component.parameters:
            component.parameters[name].value = .005
    # Emulate stored points left behind after a drag or a subsequent fit.
    _set_stored_points(component, [(0., 0.), (1., 1.), (2., 0.)])
    win.project.model_for(win.active_curve_id).add(component)
    win.refresh_all()
    win._set_component(component.id)
    before = copy.deepcopy(component.to_dict())
    count = win.undo_stack.count()
    win.edit_component_points(component.id)
    editor = win._function_point_editor
    points = win.plot_workspace._spline_points
    assert min(x for x, _ in points) > 499.
    assert editor.preview(points).to_dict() == before
    win.plot_workspace.finish_placement()
    assert not editor.active
    assert win.undo_stack.count() == count
    assert win.project.model_for(win.active_curve_id).component(component.id).to_dict() == before


@pytest.mark.parametrize("area", [10., -10.])
def test_narrow_peak_preview_matches_finish_after_moving_controls(window, area):
    _, win = window
    component = Component.create("gaussian", initial={"area": area, "center": 500., "sigma": .005})
    win.project.model_for(win.active_curve_id).add(component)
    win.refresh_all()
    win._set_component(component.id)
    win.edit_component_points(component.id)
    workspace = win.plot_workspace
    # A coherent translation/stretch/height change should remain a well-shaped peak.
    points = [(500. + (x-500.)*1.2 + .002, y*.8) for x, y in workspace._spline_points]
    workspace._spline_points = points
    workspace._render_placement_preview()
    preview = win._function_point_editor.preview(points)
    assert preview.parameters["center"].value == pytest.approx(500.002, abs=1e-6)
    assert preview.parameters["sigma"].value == pytest.approx(.006, rel=1e-3)
    assert preview.parameters["area"].value == pytest.approx(area*.96, rel=1e-3)
    workspace.finish_placement()
    assert not win._function_point_editor.active
    current = win.project.model_for(win.active_curve_id).component(component.id)
    for name in current.parameters:
        assert current.parameters[name].value == pytest.approx(preview.parameters[name].value, rel=1e-10)


def test_context_menu_edits_clicked_function_instead_of_current_selection(window):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMenu

    _, win = window
    first = add_points(win)
    second = add_points(win, "cubic_spline")
    win.model_panel.select_component_ref(win.active_curve_id, first.id)
    win._set_component(first.id)
    panel = win.model_panel
    assert not hasattr(panel, "edit_points_button")
    clicked = next(panel.components.item(i) for i in range(panel.components.count())
                   if second.name in panel.components.item(i).text())
    actions = []
    def choose_edit():
        menu = QApplication.activePopupWidget()
        if isinstance(menu, QMenu):
            actions.extend(a for a in menu.actions() if a.text() == "Edit function points…")
            menu.close()
            if actions:
                actions[0].trigger()
    QTimer.singleShot(0, choose_edit)
    panel.components.customContextMenuRequested.emit(panel.components.visualItemRect(clicked).center())
    assert actions and actions[0].isEnabled()
    assert win._function_point_editor.active
    assert win._function_point_editor.draft.id == second.id


def test_custom_peak_without_center_parameter_keeps_saved_controls():
    from types import SimpleNamespace

    from curvemole.gui.edit_function_points import editable_points

    component = Component.create("gaussian")
    component.parameters["x0"] = component.parameters.pop("center")
    points = [(0., 1.), (1., 2.), (2., 1.)]
    _set_stored_points(component, points)
    registry = SimpleNamespace(get=lambda identifier: SimpleNamespace(kind="peak"))
    assert editable_points(component, registry) == points


def test_spline_mouse_drag_and_finish_button_update_the_rendered_model(window):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    app, win = window
    component = add_points(win, "cubic_spline")
    workspace = win.plot_workspace
    curve = win.project.dataset.curve(win.active_curve_id)
    old_y = workspace._component_items[(curve.id, component.id)].getData()[1].copy()
    win.edit_component_points(component.id)
    workspace.view_box.setRange(xRange=(-.5, 2.5), yRange=(1., 6.), padding=0)
    app.processEvents()
    def screen(x, y):
        return workspace.graphics.mapFromScene(workspace.view_box.mapViewToScene(QPointF(x, y)))
    start, end = screen(1., 3.), screen(1.3, 4.5)
    viewport = workspace.graphics.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    # Move beyond the drag threshold, then continue to the intended position.
    QTest.mouseMove(viewport, start + (end-start)*.5, delay=30)
    QTest.mouseMove(viewport, end, delay=30)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end, delay=30)
    app.processEvents()
    assert workspace._spline_points[1][1] > 4.
    QTest.mouseClick(workspace.finish_placement_button, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert not win._function_point_editor.active
    current = win.project.model_for(curve.id).component(component.id)
    assert current.parameters["y1"].value > 4.
    actual = workspace._component_items[(curve.id, component.id)].getData()[1]
    expected = win.registry.get("cubic_spline").evaluate(curve.x,
        {n: p.value for n, p in current.parameters.items()}, current.metadata)
    np.testing.assert_allclose(actual, expected)
    assert not np.allclose(actual, old_y)


def test_finished_spline_uses_new_parameters_instead_of_an_old_live_fit_snapshot(window):
    _, win = window
    component = add_points(win, "cubic_spline")
    workspace = win.plot_workspace
    curve = win.project.dataset.curve(win.active_curve_id)
    workspace._live_parameter_values = dict(win.project.resolved_parameter_values())
    win.edit_component_points(component.id)
    workspace._spline_points[1] = (1., 7.)
    workspace._render_placement_preview()
    workspace.finish_placement_button.click()
    assert not win._function_point_editor.active
    current = win.project.model_for(curve.id).component(component.id)
    assert current.parameters["y1"].value == 7.
    rendered_x, rendered_y = workspace._component_items[(curve.id, component.id)].getData()
    assert rendered_y[np.argmin(abs(rendered_x-1.))] == pytest.approx(7.)


@pytest.mark.parametrize("function_id", ["cubic_spline", "polynomial", "linear", "gaussian"])
@pytest.mark.parametrize("subtracted", [False, True])
def test_background_edit_updates_existing_subtraction_for_every_function(window, function_id, subtracted):
    _, win = window
    component = add_points(win, function_id, background=True)
    curve = win.project.dataset.curve(win.active_curve_id)
    original = curve.original_y.copy()
    if subtracted:
        definition = win.registry.get(function_id)
        background = definition.evaluate(curve.x, {n: p.value for n, p in component.parameters.items()}, component.metadata)
        apply_background_subtraction(curve, background, method="model_components", description="background",
                                     parameters={"component_ids": [component.id]})
        component.enabled = False
    win.refresh_all()
    win._set_component(component.id)
    old_y = curve.y.copy()
    old_model = win.project.model_for(curve.id).to_dict()
    count = win.undo_stack.count()
    win.edit_component_points(component.id)
    workspace = win.plot_workspace
    workspace._spline_points = [(x, y*1.2) for x, y in workspace._spline_points]
    workspace.finish_placement_button.click()
    assert not win._function_point_editor.active
    current = win.project.model_for(curve.id).component(component.id)
    background = win.registry.get(function_id).evaluate(curve.x,
        {n: p.value for n, p in current.parameters.items()}, current.metadata)
    np.testing.assert_allclose(curve.y, original-background if subtracted else original)
    assert len(curve.transformations) == int(subtracted)
    assert current.enabled is not subtracted
    assert win.undo_stack.count() == count+1
    np.testing.assert_array_equal(curve.original_y, original)
    win.undo_stack.undo()
    np.testing.assert_allclose(curve.y, old_y)
    assert win.project.model_for(curve.id).to_dict() == old_model
    win.undo_stack.redo()
    np.testing.assert_allclose(curve.y, original-background if subtracted else original)


def test_grouped_background_edit_replays_later_processing_and_deletions(window, tmp_path):
    from curvemole.core.data import Transformation

    _, win = window
    spline = add_points(win, "cubic_spline", background=True)
    curve = win.project.dataset.curve(win.active_curve_id)
    constant = Component.create("constant", initial={"offset": .5})
    constant.is_background = True
    model = win.project.model_for(curve.id)
    model.add(constant)
    old_bg = model.background(curve.x, curve_id=curve.id, registry=win.registry)
    apply_background_subtraction(curve, old_bg, method="model_components", description="group",
        parameters={"component_ids": [spline.id, constant.id]})
    spline.enabled = constant.enabled = False
    curve.apply_transformation(Transformation("y_multiply", {"value": 3.}))
    curve.mask_point(.5)
    curve.delete_points([0, 4])
    old_y, original = curve.y.copy(), curve.original_y.copy()
    rows = curve.row_indices.copy()
    excluded = curve.effective_mask.copy()
    win.refresh_all()
    win._set_component(spline.id)
    for height in (4., 5.):
        win.edit_component_points(spline.id)
        win.plot_workspace._spline_points[1] = (1., height)
        win.plot_workspace.finish_placement_button.click()
        assert not win._function_point_editor.active
        current = win.project.model_for(curve.id).component(spline.id)
        bg = win.registry.get("cubic_spline").evaluate(curve.original_x,
            {n: p.value for n, p in current.parameters.items()}, current.metadata)
        np.testing.assert_allclose(curve.y, ((original-bg-.5)*3.)[rows])
        np.testing.assert_array_equal(curve.effective_mask, excluded)
        assert len(curve.transformations) == 3
        assert not current.enabled
        assert not win.project.model_for(curve.id).component(constant.id).enabled
    path = tmp_path / "edited-background.fitproj"
    save_project(win.project, path)
    loaded = load_project(path)
    np.testing.assert_allclose(loaded.dataset.curve(curve.id).y, curve.y)
    win.undo_stack.undo()
    win.undo_stack.undo()
    np.testing.assert_allclose(curve.y, old_y)


def test_failed_background_recalculation_keeps_model_data_and_history_unchanged(window):
    from curvemole.core.data import Transformation

    _, win = window
    component = add_points(win, "cubic_spline", background=True)
    curve = win.project.dataset.curve(win.active_curve_id)
    apply_background_subtraction(curve, np.full(len(curve), 2.), method="model_components", description="background",
        parameters={"component_ids": [component.id]})
    curve.apply_transformation(Transformation("x_add", {"value": 10.}))
    win.refresh_all()
    win._set_component(component.id)
    old_y, old_model = curve.y.copy(), component.to_dict()
    count = win.undo_stack.count()
    win.edit_component_points(component.id)
    win.plot_workspace._spline_points[1] = (1., 7.)
    win.plot_workspace.finish_placement_button.click()
    assert win._function_point_editor.active
    np.testing.assert_array_equal(curve.y, old_y)
    assert win.project.model_for(curve.id).component(component.id).to_dict() == old_model
    assert win.undo_stack.count() == count
    assert len(curve.transformations) == 2
