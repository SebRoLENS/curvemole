from __future__ import annotations

import cosmic_ray_removal as cosmic
import numpy as np
import pytest

from curvemole import Curve, Project
from curvemole.core.extensions import extensions
from curvemole.core.plugins import PluginManager
from curvemole.gui.plugin_host import PluginContext


def smooth_spectrum():
    x = np.linspace(100.0, 1200.0, 1400)
    y = 30 + 0.01 * x + 400 * np.exp(-0.5 * ((x - 620) / 22) ** 2)
    return x, y


def test_single_spectrum_detects_and_repairs_narrow_spikes_without_flattening_band():
    x, clean = smooth_spectrum()
    measured = clean.copy()
    measured[900] += 900
    candidates = cosmic.detect_single(x, measured)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.start <= 900 <= candidate.end
    assert candidate.confidence == "Safe"
    assert candidate.accepted
    repaired = cosmic.cleaned_values(measured, candidates)
    assert repaired[900] == pytest.approx(clean[900], rel=2e-3)
    assert repaired[np.argmax(clean)] == measured[np.argmax(clean)]


@pytest.mark.parametrize("sigma", [8, 20, 50])
def test_broad_experimental_bands_are_not_cosmic_rays_even_with_large_z_score(sigma):
    x = np.arange(1400, dtype=float)
    broad_band = 30 + 400 * np.exp(-0.5 * ((x - 700) / sigma) ** 2)
    assert cosmic.detect_single(x, broad_band) == []


def test_borderline_width_is_visible_but_not_selected_by_default():
    x, clean = smooth_spectrum()
    measured = clean.copy()
    measured[900:906] += np.array([250.0, 500.0, 700.0, 700.0, 500.0, 250.0])
    candidates = cosmic.detect_single(x, measured, max_width=8)
    assert len(candidates) == 1
    assert candidates[0].confidence in {"Possible", "Uncertain"}
    assert not candidates[0].accepted


def test_confidence_levels_combine_score_and_width():
    assert cosmic._confidence(20, 10, 1, 5) == "Safe"
    assert cosmic._confidence(12, 10, 4, 5) == "Possible"
    assert cosmic._confidence(12, 10, 4.8, 5) == "Uncertain"


def test_two_pixel_flat_topped_cosmic_ray_is_still_detected():
    x = np.arange(200, dtype=float)
    measured = np.zeros_like(x)
    measured[100:102] = 500
    candidates = cosmic.detect_single(x, measured)
    assert len(candidates) == 1
    assert candidates[0].start <= 100
    assert candidates[0].end >= 101


def test_repeated_spectrum_reference_repairs_cosmic_ray_on_real_peak():
    x, clean = smooth_spectrum()
    target_y = clean.copy()
    peak_index = int(np.argmax(clean))
    target_y[peak_index] += 1000
    target = Curve("target", x, target_y)
    repeats = [target]
    for index, factor in enumerate((0.97, 1.03, 1.01)):
        repeats.append(Curve(f"repeat {index}", x, factor * clean + 2 * index))
    candidates = cosmic.detect_ensemble(target, repeats)
    assert any(c.start <= peak_index <= c.end for c in candidates)
    repaired = cosmic.cleaned_values(target_y, candidates)
    assert repaired[peak_index] == pytest.approx(clean[peak_index], rel=0.03)


def test_each_candidate_can_be_rejected_independently():
    x, clean = smooth_spectrum()
    measured = clean.copy()
    measured[300] += 800
    measured[1000] += 700
    candidates = cosmic.detect_single(x, measured)
    assert len(candidates) == 2
    candidates[1].accepted = False
    repaired = cosmic.cleaned_values(measured, candidates)
    assert repaired[300] != measured[300]
    assert repaired[1000] == measured[1000]


def test_manual_interval_uses_shape_preserving_surroundings():
    x, clean = smooth_spectrum()
    measured = clean.copy()
    measured[500:503] += 500
    replacement = cosmic.interpolate_interval(x, measured, 500, 502)
    assert replacement == pytest.approx(clean[500:503], rel=1e-4)


def test_real_plugin_load_and_unload():
    from pathlib import Path

    manager = PluginManager()
    candidate = manager.discover_local(Path(__file__).parent)[0]
    manager.load(candidate, trust=True)
    try:
        entries = [e for e in extensions.entries.values() if e.owner == cosmic.OWNER]
        assert len(entries) == 1 and entries[0].kind == "panels" and entries[0].auto_show
    finally:
        manager.disable(cosmic.OWNER)
    assert not any(e.owner == cosmic.OWNER for e in extensions.entries.values())


def test_panel_previews_and_commits_only_checked_candidates():
    from copy import deepcopy

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    x, clean = smooth_spectrum()
    measured = clean.copy()
    measured[300] += 800
    measured[1000] += 700
    project = Project()
    curve = Curve("two cosmic rays", x, measured)
    project.add_curve(curve)

    class Services:
        values = None
        metadata = None

        def snapshot(self):
            return PluginContext(deepcopy(project), curve.id, (curve.id,), cosmic.OWNER)

        def apply_y_replacement(self, curve_id, values, **keywords):
            self.values = np.asarray(values)
            self.metadata = keywords["metadata"]
            project.dataset.curve(curve_id).apply_transformation(
                __import__("curvemole.core.data", fromlist=["Transformation"]).Transformation(
                    "replace_y", operand=self.values
                )
            )

    services = Services()
    context = PluginContext(
        deepcopy(project), curve.id, (curve.id,), cosmic.OWNER, services=services
    )
    panel = cosmic.cosmic_ray_panel(context)
    try:
        for control in (
            panel.method,
            panel.threshold,
            panel.window,
            panel.max_width,
            panel.grow,
            panel.manual,
            panel.remove_manual,
            panel.accept,
        ):
            assert control.toolTip()
        assert not panel.remove_manual.isEnabled()  # Older hosts keep detection available.
        panel.detect()
        assert panel.table.rowCount() == 2
        assert panel.table.item(0, 1).text() == "Safe"
        assert panel.table.item(0, 0).background().color().alpha() > 0
        panel.candidates[1].confidence = "Uncertain"
        panel.select_confidence(False)
        assert panel.candidates[0].accepted
        assert not panel.candidates[1].accepted
        panel.select_confidence(True)
        assert all(candidate.accepted for candidate in panel.candidates)
        panel.candidates[1].accepted = False
        panel.apply()
        assert services.values[300] != measured[300]
        assert services.values[1000] == measured[1000]
        assert len(services.metadata["history"][-1]["intervals"]) == 1
    finally:
        panel.close()
        panel.deleteLater()
        app.processEvents()


def test_remove_manually_uses_native_editor_and_refreshes_after_move_delete_and_undo(tmp_path, monkeypatch):
    from PySide6.QtCore import QPointF, QSettings, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from curvemole.core.data import CurveState
    from curvemole.core.extensions import Contribution
    from curvemole.gui.app import CurveMoleMainWindow
    from curvemole.gui.plugin_services import PluginServices

    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    monkeypatch.setattr('curvemole.gui.main_window.QSettings', lambda *args: settings)
    monkeypatch.setenv('CURVEMOLE_DISABLE_PLUGINS', '1')
    x, clean = smooth_spectrum()
    measured = clean.copy()
    measured[900] += 900
    project = Project('Manual cosmic-ray removal')
    curve = Curve('Measured', x, measured, sigma_y=np.full(len(x), 0.2))
    project.add_curve(curve)
    main = CurveMoleMainWindow(project)
    main.resize(1400, 900)
    main.show()
    app.processEvents()
    monkeypatch.setattr(extensions, 'entries', {
        cosmic.OWNER: Contribution(cosmic.OWNER, cosmic.OWNER, 'Cosmic', 'panels', lambda ctx: None)
    })
    services = PluginServices(main.plugin_host, cosmic.OWNER)
    panel = cosmic.cosmic_ray_panel(services.spectrum_snapshot())
    panel.timer.stop()
    try:
        panel.detect()
        assert len(panel.candidates) == 1
        panel.manual.setChecked(True)
        curve.state = CurveState.FITTED
        assert panel.manual.text() == 'Detect manually'
        assert panel.remove_manual.text() == 'Remove manually'
        assert panel.remove_manual.isEnabled()
        QTest.mouseClick(panel.remove_manual, Qt.MouseButton.LeftButton)
        editor = main.plot_workspace.point_editor
        assert editor.active and editor.axes.currentData() == 'y'
        assert not panel.manual.isChecked()
        assert 'main graph' in panel.status.text()
        assert 'immediately' in panel.status.text()
        assert main.undo_stack.count() == 0
        assert curve.state == CurveState.FITTED
        assert len(panel.candidates) == 1  # Opening the editor has not changed any data.

        workspace = main.plot_workspace
        start = workspace.view_box.mapViewToScene(QPointF(x[900], measured[900]))
        target = workspace.view_box.mapViewToScene(QPointF(x[901], clean[900]))
        assert editor.begin_drag(start)
        editor.end_drag(target)
        panel.refresh()
        assert curve.x[900] == x[900]  # Cosmic-ray cleanup initially preserves X.
        assert curve.y[900] == pytest.approx(clean[900])
        assert main.undo_stack.count() == 1
        assert curve.state == CurveState.MODIFIED
        assert not panel.candidates and not panel.accept.isEnabled()
        np.testing.assert_array_equal(panel.base_y, curve.y)
        editor.delete_button.click()
        panel.refresh()
        assert len(curve) == len(x) - 1
        assert len(curve.current_sigma_y) == len(curve)
        assert len(panel.base_x) == len(curve)
        assert main.undo_stack.count() == 2
        main.undo_stack.undo()
        main.undo_stack.undo()
        panel.refresh()
        np.testing.assert_array_equal(curve.y, measured)
        np.testing.assert_array_equal(curve.original_y, measured)
        np.testing.assert_array_equal(panel.base_y, measured)
        assert curve.state == CurveState.FITTED
        main.undo_stack.redo()
        main.undo_stack.redo()
        panel.refresh()
        assert len(panel.base_y) == len(x) - 1
        editor.done_button.click()
        assert not editor.active
        other = Curve('Other spectrum', x, clean)
        main.project.add_curve(other)
        main.active_curve_id = other.id
        main.refresh_all()
        # The button must target today's selection even before the next preview poll.
        QTest.mouseClick(panel.remove_manual, Qt.MouseButton.LeftButton)
        assert editor.active and panel.curve_id == other.id
        assert workspace._active_curve_id == other.id
        np.testing.assert_array_equal(other.y, clean)
        editor.done_button.click()
        main.active_curve_id = None
        panel.refresh()
        assert not panel.remove_manual.isEnabled()
    finally:
        panel.close()
        panel.deleteLater()
        main.project.dirty = False
        main.close()
        main.deleteLater()
        app.processEvents()


def test_large_project_panel_polls_without_copying_unrelated_spectra(monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication

    from curvemole.core.data import Transformation
    from curvemole.core.extensions import Contribution
    from curvemole.gui.plugin_services import PluginServices

    app = QApplication.instance() or QApplication([])
    project = Project()
    x, y = smooth_spectrum()
    y[900] += 900
    curves = [Curve(str(i), x, y) for i in range(100)]
    for curve in curves:
        project.add_curve(curve)

    class DoNotCopy:
        def __deepcopy__(self, memo):
            raise AssertionError("The preview copied unrelated project data")

    for curve in curves[3:]:
        curve.metadata["unrelated"] = DoNotCopy()
    project.results["large_fit_result"] = DoNotCopy()
    monkeypatch.setattr(extensions, "entries", {
        cosmic.OWNER + ":panel": Contribution(
            cosmic.OWNER, cosmic.OWNER + ":panel", "Cosmic", "panels", lambda ctx: None
        )
    })
    window = SimpleNamespace(
        project=project, active_curve_id=curves[0].id,
        curve_tree=SimpleNamespace(selected_curve_ids=lambda: [c.id for c in curves[:3]]),
        plugin_manager=SimpleNamespace(errors={}),
    )
    # No full-project context method: even one accidental snapshot() must fail.
    services = PluginServices(SimpleNamespace(window=window), cosmic.OWNER)
    requests = []
    original = services.spectrum_snapshot

    def snapshot(*, include_selected=False):
        requests.append(include_selected)
        return original(include_selected=include_selected)

    monkeypatch.setattr(services, "spectrum_snapshot", snapshot)
    context = PluginContext(project, curves[0].id, (), cosmic.OWNER, services=services)
    panel = cosmic.cosmic_ray_panel(context)
    panel.timer.stop()
    try:
        assert requests == [False]
        for _ in range(20):
            panel.refresh()
        assert requests == [False]
        panel.detect()
        assert requests == [False, False]
        assert panel.candidates and panel.accept.isEnabled()
        curves[0].name = "Renamed spectrum"
        panel.refresh()
        assert panel.title.text() == curves[0].name
        assert len(requests) == 2
        curves[0].apply_transformation(Transformation("y_add", parameters={"value": 10}))
        panel.refresh()
        assert requests == [False, False, False]
        assert panel.candidates == []
        assert not panel.accept.isEnabled()
        panel.method.setCurrentIndex(1)
        panel.detect()
        assert requests[-1] is True
        window.active_curve_id = curves[1].id
        panel.refresh()
        assert panel.curve_id == curves[1].id
        panel.hide()
        window.active_curve_id = curves[2].id
        before = len(requests)
        panel.refresh_visible()
        assert len(requests) == before
        panel.show()
        app.processEvents()
        assert panel.curve_id == curves[2].id
    finally:
        panel.close()
        panel.deleteLater()
        app.processEvents()
