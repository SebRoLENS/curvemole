"""Native background/point edits must survive a plugin replacing project objects."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from curvemole import Component, Curve, Project
from curvemole.core.extensions import Contribution
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.background_navigation import _subtract_all_backgrounds as legacy_subtract_all
from curvemole.gui.dialogs import BackgroundComponentsDialog
from curvemole.gui.manual_points import initialise_component_from_points
from curvemole.gui.manual_points_live import _apply_manual_point_drag, _set_stored_points


@pytest.fixture
def recreation_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    project = Project("Native Undo")
    for index, offset in enumerate((2., 5.)):
        curve = Curve(str(index), np.arange(21.), offset + np.arange(21.))
        project.add_curve(curve)
        component = Component.create("constant", initial={"offset": offset})
        component.is_background = True
        project.model_for(curve.id).add(component)
    window = CurveMoleMainWindow(project)
    yield window
    window.project.dirty = False
    window.close()
    app.processEvents()


def plugin_replace_project(window):
    original = window.project
    count = window.undo_stack.count()

    def action(context):
        context.project.name = "Renamed by plugin"

    window.plugin_host.run(Contribution("test.recreation", "test.recreation:rename", "Rename", "actions", action))
    assert window.undo_stack.count() == count + 1
    assert window.project is not original


def curve_state(window):
    return {
        curve.id: (
            curve.y.copy(),
            [(item.operation, item.created_at) for item in curve.transformations],
            [(item.operation, item.created_at) for item in curve.redo_transformations],
            [(component.id, component.is_background, component.enabled)
             for component in window.project.model_for(curve.id).components],
        )
        for curve in window.project.curves
    }


def assert_state(window, expected, *, include_redo=False):
    actual = curve_state(window)
    assert set(actual) == set(expected)
    for curve_id, (values, transformations, redo, components) in actual.items():
        np.testing.assert_array_equal(values, expected[curve_id][0])
        assert transformations == expected[curve_id][1]
        if include_redo:
            assert redo == expected[curve_id][2]
        assert components == expected[curve_id][3]


@pytest.mark.parametrize("operation", ["current", "all", "revert", "legacy_all"])
def test_background_undo_redo_uses_current_graph_after_plugin(recreation_window, monkeypatch, operation):
    window = recreation_window
    if operation == "revert":
        window.subtract_all_backgrounds()
        window.undo_stack.clear()
    before = curve_state(window)
    if operation == "current":
        monkeypatch.setattr(BackgroundComponentsDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
        window.subtract_background()
    elif operation == "all":
        window.subtract_all_backgrounds()
    elif operation == "legacy_all":
        legacy_subtract_all(window)
    else:
        window.revert_backgrounds([window.active_curve_id])
    after = curve_state(window)
    plugin_replace_project(window)
    for _ in range(3):
        window.undo_stack.undo()  # Plugin snapshot recreates the graph again.
        assert_state(window, after)
        window.undo_stack.undo()
        assert_state(window, before)
        window.undo_stack.redo()
        assert_state(window, after)
        window.undo_stack.redo()
        assert_state(window, after)


def test_manual_point_drag_undo_redo_uses_current_component_after_plugin(recreation_window):
    window = recreation_window
    curve_id = window.active_curve_id
    component = Component.create("linear")
    points = [(0., 1.), (2., 5.)]
    initialise_component_from_points(component, points, registry=window.registry)
    _set_stored_points(component, points)
    for parameter in component.parameters.values():
        parameter.fixed = False
    window.project.model_for(curve_id).components = [component]
    window.refresh_all()
    component_id = component.id
    before = component.to_dict()
    _apply_manual_point_drag(window, component_id, 1, 2., 7.)
    after = window.project.model_for(curve_id).component(component_id).to_dict()
    assert after != before
    plugin_replace_project(window)
    window._set_active_curve(window.project.curves[1].id)
    for _ in range(3):
        window.undo_stack.undo()
        window.undo_stack.undo()
        assert window.project.model_for(curve_id).component(component_id).to_dict() == before
        window.undo_stack.redo()
        assert window.project.model_for(curve_id).component(component_id).to_dict() == after
        window.undo_stack.redo()
        assert window.project.model_for(curve_id).component(component_id).to_dict() == after
