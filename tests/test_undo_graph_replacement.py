"""Native edit commands must survive project/model restoration by plugin Undo."""

from __future__ import annotations

import copy

import numpy as np
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from curvemole import Component, Curve, Project
from curvemole.core.data import CurveState
from curvemole.core.extensions import Contribution
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.dialogs import CopyFitDialog
from curvemole.gui.model_multiselect import _BATCH


@pytest.fixture
def edit_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    project = Project("Undo graph replacement")
    template = [Component.create("gaussian"), Component.create("constant")]
    for index in range(2):
        curve = Curve(str(index), [0., 1., 2.], np.arange(1., 4.) + index * 3.)
        project.add_curve(curve)
        project.model_for(curve.id).components = copy.deepcopy(template)
    project.dirty = False
    window = CurveMoleMainWindow(project)

    def fail(title, error):
        pytest.fail(f"{title}: {error}")

    monkeypatch.setattr(window, "_show_error", fail)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: pytest.fail(str(args)))
    yield window
    window.project.dirty = False
    window.close()
    app.processEvents()


def _plugin_change(window):
    entry = Contribution(
        "test.graph_restore", "test.graph_restore:rename", "Plugin rename", "actions",
        lambda context: setattr(context.project, "name", "Changed by plugin"),
    )
    window.plugin_host.run(entry)
    assert window.project.name == "Changed by plugin"


def _roundtrip(window, before, after):
    assert window.undo_stack.count() == 2
    after()
    # Repeated cycles catch retained state being reused/mutated after the first
    # restoration, as well as callbacks writing into an obsolete project.
    for _ in range(2):
        window.undo_stack.undo()
        before()
        window.undo_stack.undo()
        before()
        window.undo_stack.redo()
        before()
        window.undo_stack.redo()
        after()


@pytest.mark.parametrize("scope", [0, 2])
def test_calculator_undo_redo_targets_current_curves_after_plugin_restore(edit_window, scope):
    window = edit_window
    curve_ids = [curve.id for curve in window.project.curves]
    originals = {curve.id: curve.y.copy() for curve in window.project.curves}
    _plugin_change(window)
    window.apply_calculator({"operation": "y_add", "value": 10., "scope": scope})

    def check(changed):
        for index, curve_id in enumerate(curve_ids):
            offset = 10. if changed and (scope == 2 or index == 0) else 0.
            np.testing.assert_array_equal(window.project.dataset.curve(curve_id).y,
                                          originals[curve_id] + offset)

    _roundtrip(window, lambda: check(False), lambda: check(True))


@pytest.mark.parametrize("field,value", [("value", 8.), ("minimum", -2.),
                                        ("maximum", 20.), ("fixed", True)])
def test_parameter_undo_redo_uses_current_parameter_after_plugin_restore(edit_window, field, value):
    window = edit_window
    curve_id = window.active_curve_id
    other_id = window.project.curves[1].id
    component_id = window.project.model_for(curve_id).components[1].id
    name = "offset"
    original = getattr(window.project.model_for(curve_id).component(component_id).parameters[name], field)
    _plugin_change(window)
    window._set_component_on_curve(curve_id, component_id)
    window.change_parameter(component_id, name, field, value)

    def check(expected):
        parameter = window.project.model_for(curve_id).component(component_id).parameters[name]
        assert getattr(parameter, field) == expected
        assert getattr(window.project.model_for(other_id).component(component_id).parameters[name], field) == original

    _roundtrip(window, lambda: check(original), lambda: check(value))


@pytest.mark.parametrize("operation,field,value", [
    ("enable_component", "enabled", False),
    ("set_component_background", "is_background", True),
    ("set_component_fixed", "fixed", True),
])
@pytest.mark.parametrize("batch", [False, True])
def test_component_flags_survive_plugin_restore_with_shared_component_ids(edit_window, operation, field, value, batch):
    window = edit_window
    curve_ids = [curve.id for curve in window.project.curves]
    component_id = window.project.model_for(curve_ids[0]).components[1].id
    original = not value
    _plugin_change(window)
    if batch:
        panel = window.model_panel
        panel.show_all_functions.setChecked(True)
        panel.components.clearSelection()
        for row in range(panel.components.count()):
            item = panel.components.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == component_id:
                item.setSelected(True)
        assert set(panel.selected_component_refs()) == {(key, component_id) for key in curve_ids}
    else:
        window._set_component_on_curve(curve_ids[0], component_id)
    getattr(window, operation)(_BATCH if batch else component_id, value)

    def check(changed):
        for index, curve_id in enumerate(curve_ids):
            component = window.project.model_for(curve_id).component(component_id)
            target = component.parameters["offset"] if field == "fixed" else component
            assert getattr(target, field) == (value if changed and (batch or index == 0) else original)

    _roundtrip(window, lambda: check(False), lambda: check(True))


def test_graphical_parameter_edit_resolves_paths_after_plugin_restore(edit_window):
    window = edit_window
    curve_id = window.active_curve_id
    component_id = window.project.model_for(curve_id).components[0].id
    _plugin_change(window)
    window.drag_peak(component_id, .4, 3., False)
    after = {name: parameter.value for name, parameter in
             window.project.model_for(curve_id).component(component_id).parameters.items()}

    def check(expected):
        actual = {name: parameter.value for name, parameter in
                  window.project.model_for(curve_id).component(component_id).parameters.items()}
        assert actual == expected

    _roundtrip(window, lambda: check({"area": 1., "center": 0., "sigma": 1.}),
               lambda: check(after))


def test_edit_marks_original_target_after_selection_changes(edit_window):
    window = edit_window
    first, second = [curve.id for curve in window.project.curves]
    component_id = window.project.model_for(first).components[1].id
    window._set_component_on_curve(first, component_id)
    window.change_parameter(component_id, "offset", "value", 8.)
    window._set_active_curve(second)
    for curve in window.project.curves:
        curve.state = CurveState.FITTED
    window.undo_stack.undo()
    assert window.project.dataset.curve(first).state == CurveState.MODIFIED
    assert window.project.dataset.curve(second).state == CurveState.FITTED


def test_parameter_edit_survives_native_model_reconstruction(edit_window):
    window = edit_window
    curve_id = window.active_curve_id
    component_id = window.project.model_for(curve_id).components[1].id
    window._set_component_on_curve(curve_id, component_id)
    window.change_parameter(component_id, "offset", "value", 8.)
    window.duplicate_component(component_id)
    window.undo_stack.undo()
    window.undo_stack.undo()
    assert window.project.model_for(curve_id).component(component_id).parameters["offset"].value == 0.
    window.undo_stack.redo()
    assert window.project.model_for(curve_id).component(component_id).parameters["offset"].value == 8.


def test_series_palette_targets_restored_series(edit_window):
    window = edit_window
    series_id = window.project.dataset.series[0].id
    before = [curve.colour for curve in window.project.curves]
    _plugin_change(window)
    from curvemole.gui.main_window import SERIES_PALETTES

    name = next(key for key, palette in SERIES_PALETTES.items()
                if list(palette[:len(before)]) != before)
    window.apply_series_palette(series_id, name)
    after = [curve.colour for curve in window.project.curves]
    assert after != before

    def check(expected):
        assert [curve.colour for curve in window.project.curves] == expected

    _roundtrip(window, lambda: check(before), lambda: check(after))


def test_data_point_edit_targets_restored_curve(edit_window):
    window = edit_window
    curve_id = window.active_curve_id
    _plugin_change(window)
    window.edit_data_points_action.setChecked(True)
    assert window.plot_workspace.point_editor.active
    window._move_data_point(curve_id, 1, 1.25, 9.)

    def check(changed):
        curve = window.project.dataset.curve(curve_id)
        np.testing.assert_array_equal(curve.x, [0., 1.25 if changed else 1., 2.])
        np.testing.assert_array_equal(curve.y, [1., 9. if changed else 2., 3.])

    _roundtrip(window, lambda: check(False), lambda: check(True))


def test_copy_fit_targets_restored_models_and_curves(edit_window, monkeypatch):
    window = edit_window
    source, target = [curve.id for curve in window.project.curves]
    component_id = window.project.model_for(source).components[1].id
    window.project.model_for(source).component(component_id).parameters["offset"].value = 7.
    _plugin_change(window)
    monkeypatch.setattr(CopyFitDialog, "exec", lambda dialog: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(CopyFitDialog, "choices", lambda dialog: ([target], {}))
    window.copy_fit()

    def check(expected):
        assert window.project.model_for(target).component(component_id).parameters["offset"].value == expected
        assert window.project.model_for(source).component(component_id).parameters["offset"].value == 7.

    _roundtrip(window, lambda: check(0.), lambda: check(7.))


def test_parameter_edit_survives_copy_fit_model_reconstruction(edit_window, monkeypatch):
    window = edit_window
    source, target = [curve.id for curve in window.project.curves]
    component_id = window.project.model_for(source).components[1].id
    window._set_component_on_curve(target, component_id)
    window.change_parameter(component_id, "offset", "value", 8.)
    window._set_active_curve(source)
    monkeypatch.setattr(CopyFitDialog, "exec", lambda dialog: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(CopyFitDialog, "choices", lambda dialog: ([target], {}))
    window.copy_fit()
    window.undo_stack.undo()
    assert window.project.model_for(target).component(component_id).parameters["offset"].value == 8.
    window.undo_stack.undo()
    assert window.project.model_for(target).component(component_id).parameters["offset"].value == 0.
    window.undo_stack.redo()
    assert window.project.model_for(target).component(component_id).parameters["offset"].value == 8.
    window.undo_stack.redo()
    assert window.project.model_for(target).component(component_id).parameters["offset"].value == 0.
