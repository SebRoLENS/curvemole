"""Functional calibration, persistence, atomicity and plugin-only GUI tests."""
import copy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from curvemole.core.data import Curve, CurveState, Series, Transformation
from curvemole.core.extensions import Contribution, extensions
from curvemole.core.project import Project
from curvemole.core.serialization import load_project, save_project

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SPEC = importlib.util.spec_from_file_location("calibration_plugin", Path(__file__).with_name("x_axis_calibration.py"))
plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plugin)


def profile(offset=10, degree=1):
    return plugin.make_profile("Test", [0, 1, 2, 3], [offset, offset+2, offset+4, offset+6], degree=degree)


def curve():
    return Curve("spectrum", np.array([0., 1., 2., 3.]), np.array([1., 4., 2., 1.]),
                 sigma_x=np.full(4, .1), x_unit="pixel")


@pytest.mark.parametrize("degree", [0, 1, 2, 3])
def test_known_calibrations(degree):
    x = np.array([0., 1., 2., 3., 4.])
    y = x + 4 if degree == 0 else 3*x + 2 + (.1*x*x if degree >= 2 else 0) + (.01*x**3 if degree == 3 else 0)
    p = plugin.make_profile("reference", x, y, degree=degree)
    np.testing.assert_allclose(plugin.evaluate(p, x), y, atol=1e-10)


def test_reapply_replace_restore_mask_ranges_and_sigma():
    c = curve()
    c.fit_ranges = [(1., 2.)]
    c.masks["Default"].excluded[1] = True
    c.masks["Default"].ranges = [(1., 1.)]
    once = plugin.calibrated_curve(c, profile())
    twice = plugin.calibrated_curve(once, profile())
    np.testing.assert_allclose(once.x, [10, 12, 14, 16])
    np.testing.assert_allclose(once.x, twice.x)
    np.testing.assert_array_equal(once.original_x, c.original_x)
    np.testing.assert_array_equal(once.y, c.y)
    np.testing.assert_allclose(twice.sigma_x, .2)
    np.testing.assert_allclose(twice.fit_ranges, [(12., 14.)])
    np.testing.assert_allclose(twice.masks["Default"].ranges, [(12., 12.)])
    assert twice.masks["Default"].excluded[1]
    replaced = plugin.calibrated_curve(twice, profile(20))
    np.testing.assert_allclose(replaced.x, [20, 22, 24, 26])
    restored = plugin.calibrated_curve(replaced, None)
    np.testing.assert_allclose(restored.x, c.x, atol=1e-12)
    np.testing.assert_allclose(restored.sigma_x, c.sigma_x)
    assert restored.x_unit == "pixel"
    assert plugin.TAG not in restored.metadata


def test_later_transform_rejected_without_damage():
    c = plugin.calibrated_curve(curve(), profile())
    c.apply_transformation(Transformation("y_add", {"value": 1}))
    before = c.x.copy()
    with pytest.raises(ValueError, match="undo transformations"):
        plugin.calibrated_curve(c, profile())
    np.testing.assert_array_equal(c.x, before)


def test_invalid_references_and_polynomial_turning_between_samples():
    with pytest.raises(ValueError):
        plugin.make_profile("bad", [0, 0], [1, 2])
    with pytest.raises(ValueError):
        plugin.make_profile("bad", [0, 1], [2, 1])
    with pytest.raises(ValueError):
        plugin.make_profile("bad", [0, 1], [1, np.nan])
    p = {"origin": 0, "scale": 1, "coefficients": [0, .2, -1, 1]}
    with pytest.raises(ValueError, match="increasing"):
        plugin.evaluate(p, [0, 1])


def test_batch_atomicity_and_multiple_profiles(tmp_path):
    a, b = curve(), curve()
    project = Project()
    project.add_series(Series("A", curves=[a]))
    project.add_series(Series("B", curves=[b]))
    a.state = CurveState.FITTED
    plugin.apply_to_project(project, [a.id], profile())
    plugin.apply_to_project(project, [b.id], profile(20))
    assert len(plugin.profiles(project)) == 2
    assert project.dataset.curve(a.id).state == CurveState.MODIFIED
    save_project(project, tmp_path / "calibrations.fitproj")
    reopened = load_project(tmp_path / "calibrations.fitproj")
    assert len(plugin.profiles(reopened)) == 2
    np.testing.assert_allclose(reopened.dataset.curve(a.id).x, [10, 12, 14, 16])
    np.testing.assert_allclose(reopened.dataset.curve(b.id).x, [20, 22, 24, 26])
    reopened.dataset.curve(b.id).apply_transformation(Transformation("x_add", {"value": 1}))
    before = reopened.dataset.curve(a.id).x.copy()
    with pytest.raises(ValueError):
        plugin.apply_to_project(reopened, [a.id, b.id], profile(30))
    np.testing.assert_array_equal(reopened.dataset.curve(a.id).x, before)


def test_portable_profile_and_untrusted_coefficients(tmp_path):
    path = tmp_path / "calibration.cmcal.json"
    plugin.export_profile(profile(), path)
    content = json.loads(path.read_text())
    content["calibration"]["coefficients"] = ["bad code"]
    path.write_text(json.dumps(content))
    restored = plugin.import_profile(path)
    np.testing.assert_allclose(plugin.evaluate(restored, [0, 1, 2]), [10, 12, 14])
    assert restored["id"] != content["calibration"]["id"]


def test_large_offset_conditioning_and_descending_axis():
    x = 1e9 + np.arange(5.)
    p = plugin.make_profile("large", x, np.arange(5.) * 2 + 500)
    np.testing.assert_allclose(plugin.evaluate(p, x[::-1]), [508, 506, 504, 502, 500])


def test_gui_manual_application_undo_redo_and_no_import_override(monkeypatch):
    from PySide6.QtWidgets import QApplication, QMainWindow

    from curvemole.gui.plugin_services import PluginServices
    app = QApplication.instance() or QApplication([])
    window = QMainWindow()
    window.project = Project()
    c = curve()
    window.project.add_curve(c)
    window.active_curve_id = c.id
    window.curve_tree = SimpleNamespace(selected_curve_ids=lambda: [c.id])
    window.plugin_manager = SimpleNamespace(errors={})
    window._thread = None
    def native_import():
        pass
    window.import_data = native_import
    changes = []
    def push(label, redo, undo, **kwargs):
        redo()
        changes.append((redo, undo))
    window._push_change = push
    entry = Contribution(plugin.OWNER, plugin.OWNER+":calibration", "Calibration", "panels", plugin.create_panel)
    monkeypatch.setattr(extensions, "entries", {entry.identifier: entry})
    host = SimpleNamespace(window=window)
    services = PluginServices(host, plugin.OWNER)
    host.context = lambda *args, **kwargs: SimpleNamespace(data=copy.deepcopy(
        window.project.ui_state.get("plugin_data", {}).get(plugin.OWNER, {})))
    panel = plugin.create_panel(SimpleNamespace(services=services))
    try:
        assert window.import_data is native_import
        from PySide6.QtWidgets import QTableWidgetItem

        from curvemole.core.models import Component
        for centre in (0., 3.):
            window.project.add_component(c.id, Component.create("gaussian", initial={"center": centre}))
        c.state = CurveState.FITTED
        panel.read_peaks()
        assert panel.table.rowCount() == 2
        panel.table.setItem(0, 1, QTableWidgetItem("10"))
        panel.table.setItem(1, 1, QTableWidgetItem("16"))
        panel.save_profile()
        assert len(plugin.profiles(window.project)) == 1
        window.project.model_for(c.id).components.clear()
        panel.refresh()
        panel.apply("selected")
        np.testing.assert_allclose(window.project.curves[0].x, [10, 12, 14, 16])
        changes[-1][1]()
        np.testing.assert_allclose(window.project.curves[0].x, [0, 1, 2, 3])
        changes[-1][0]()
        np.testing.assert_allclose(window.project.curves[0].x, [10, 12, 14, 16])
        imported = curve()
        window.project.add_curve(imported)
        panel.refresh()
        np.testing.assert_allclose(imported.x, [0, 1, 2, 3])
        extensions.entries.clear()
        panel.refresh()
        assert not panel.timer.isActive()
        assert window.import_data is native_import
    finally:
        panel.close()
        panel.deleteLater()
        window.close()
        app.processEvents()
