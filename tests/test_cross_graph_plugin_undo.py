"""Native commands must survive project graph replacement by general plugins."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from curvemole import Component, Curve, Project
from curvemole.core.data import CurveState, Series
from curvemole.core.extensions import Contribution, extensions
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.parameter_copy import copy_parameter_to_refs
from curvemole.gui.plugin_services import PluginServices

OWNER = "test.cross_graph"


@pytest.fixture
def cross_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("CURVEMOLE_DISABLE_PLUGINS", "1")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    entry = Contribution(OWNER, OWNER + ":panel", "Test", "panels", lambda ctx: None)
    monkeypatch.setattr(extensions, "entries", {entry.identifier: entry})
    project = Project("Cross graph Undo")
    curves = [Curve(name, np.arange(9.), [0., 0., 1., 4., 10., 4., 1., 0., 0.])
              for name in ("source", "target")]
    components = []
    for index, curve in enumerate(curves):
        project.add_series(Series(curve.name, [curve]))
        component = Component.create("gaussian", initial={"center": index + 1.25})
        project.model_for(curve.id).add(component)
        curve.state = CurveState.FITTED
        components.append(component)
    project.dirty = False
    window = CurveMoleMainWindow(project)
    yield window, [curve.id for curve in curves], [component.id for component in components]
    window.project.dirty = False
    window.close()
    app.processEvents()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def plugin_checkpoint(window):
    before = window.project
    entry = Contribution(OWNER, OWNER + ":change", "Plugin checkpoint", "actions",
                         lambda context: context.data.update(checkpoint=True))
    window.plugin_host.run(entry)
    assert window.project is not before
    window.undo_stack.undo()
    assert window.project is not before
    assert "checkpoint" not in window.project.ui_state.get("plugin_data", {}).get(OWNER, {})


def test_parameter_copy_undo_targets_current_models_and_preserves_source_fit_state(cross_window):
    window, curves, components = cross_window
    source, target = curves
    result = copy_parameter_to_refs(window, (source, components[0]), [(target, components[1])],
                                    "center", copy_value=True)
    assert result.copied == 1
    assert window.project.dataset.curve(source).state == CurveState.FITTED
    assert window.project.dataset.curve(target).state == CurveState.MODIFIED
    plugin_checkpoint(window)
    window._set_active_curve(source)
    window.undo_stack.undo()
    parameter = window.project.model_for(target).component(components[1]).parameters["center"]
    assert parameter.value == 2.25
    window.undo_stack.redo()
    assert window.project.model_for(target).component(components[1]).parameters["center"].value == 1.25
    window.undo_stack.redo()
    assert window.project.model_for(target).component(components[1]).parameters["center"].value == 1.25


def test_series_deletion_undo_restores_current_data_models_and_scientific_records(cross_window, monkeypatch):
    window, curves, components = cross_window
    source, target = curves
    series_id = window.project.dataset.series_for(source).id
    project = window.project
    project.results[source] = {"direct": "source fit"}
    project.results["fit_by_curve"] = {
        source: {"global_key": "global"}, target: {"global_key": "global"}
    }
    project.results["global_fit_baselines"] = {"global": {"success": True}}
    samples = np.arange(12.).reshape(4, 3)
    project.results["uncertainty_by_curve"] = {source: {"samples": samples}, target: {"samples": samples}}
    project.results["uncertainty_reports_by_curve"] = {source: {"report": 1}, target: {"report": 2}}
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window.delete_series(series_id)
    assert source not in {curve.id for curve in window.project.curves}
    assert window.project.results["fit_by_curve"] == {}
    assert window.project.results["global_fit_baselines"] == {}
    assert window.project.results["uncertainty_by_curve"] == {}
    assert window.project.results["uncertainty_reports_by_curve"] == {}
    plugin_checkpoint(window)
    window.undo_stack.undo()
    assert [curve.id for curve in window.project.curves] == curves
    assert window.project.model_for(source).component(components[0]).parameters["center"].value == 1.25
    assert set(window.project.results["fit_by_curve"]) == set(curves)
    assert set(window.project.results["uncertainty_by_curve"]) == set(curves)
    assert window.project.results["uncertainty_by_curve"][source]["samples"] is samples
    window.undo_stack.redo()
    assert source not in {curve.id for curve in window.project.curves}
    assert window.project.results["uncertainty_by_curve"] == {}
    window.undo_stack.undo()
    assert set(window.project.results["uncertainty_by_curve"]) == set(curves)


def test_peak_search_undo_targets_original_spectrum_after_plugin_and_selection_change(cross_window, monkeypatch):
    window, curves, components = cross_window
    source = curves[0]
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args, **kwargs: ("Positive (default)", True))
    monkeypatch.setattr(QInputDialog, "getInt", lambda *args, **kwargs: (1, True))

    def choose_function(dialog):
        dialog.setTextValue(window.registry.get("lorentzian").display_name)
        return 1

    monkeypatch.setattr(QInputDialog, "exec", choose_function)
    window.find_peaks()
    added = window.project.model_for(source).components[-1]
    assert added.function_id == "lorentzian"
    added_id = added.id
    plugin_checkpoint(window)
    window._set_active_curve(curves[1])
    window.undo_stack.undo()
    assert [component.id for component in window.project.model_for(source).components] == [components[0]]
    window.undo_stack.redo()
    assert [component.id for component in window.project.model_for(source).components] == [components[0], added_id]


@pytest.mark.parametrize("operation", ["settings", "replacement", "mask"])
def test_plugin_services_native_commands_survive_full_graph_restores(cross_window, operation):
    window, curves, _ = cross_window
    curve_id = curves[0]
    curve = window.project.dataset.curve(curve_id)
    curve.add_mask("edited")
    curve.active_mask = "Default"
    service = PluginServices(window.plugin_host, OWNER)
    original = curve.y.copy()
    if operation == "settings":
        service.save_settings({"value": [1]}, metadata_key="own", curve_metadata={curve_id: {"value": 2}})
    elif operation == "replacement":
        service.apply_y_replacement(curve_id, np.full(9, 50.))
    else:
        service.select_masks({curve_id: "edited"})
    plugin_checkpoint(window)
    window._set_active_curve(curves[1])
    window.undo_stack.undo()
    restored = window.project.dataset.curve(curve_id)
    if operation == "settings":
        assert service.settings() == {}
        assert "own" not in restored.metadata
    elif operation == "replacement":
        np.testing.assert_array_equal(restored.y, original)
    else:
        assert restored.active_mask == "Default"
    window.undo_stack.redo()
    restored = window.project.dataset.curve(curve_id)
    if operation == "settings":
        assert service.settings() == {"value": [1]}
        assert restored.metadata["own"] == {"value": 2}
    elif operation == "replacement":
        np.testing.assert_array_equal(restored.y, np.full(9, 50.))
    else:
        assert restored.active_mask == "edited"
