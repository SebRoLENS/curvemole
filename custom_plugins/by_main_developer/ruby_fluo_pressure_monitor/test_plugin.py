from __future__ import annotations

import numpy as np
import pytest
import ruby_fluo_pressure_monitor as ruby

from curvemole import Curve, Project, Series
from curvemole.core.extensions import Contribution, extensions
from curvemole.core.functions import _pseudo_voigt
from curvemole.core.serialization import load_project, save_project
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.plugin_host import PluginContext


@pytest.fixture(autouse=True)
def qt_cleanup():
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield
    for widget in app.topLevelWidgets():
        if isinstance(widget, CurveMoleMainWindow) and not widget.isVisible():
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("thermal", ["ragan", "datchi", "datchi_hot"])
def test_zero_pressure_and_known_synthetic_pressure(thermal):
    s = ruby.settings(
        {"thermal_model": thermal, "temperature_K": 450.0, "temperature_confirmed": True}
    )
    shift = ruby.thermal_position(450.0, s) - ruby.thermal_position(296.0, s)
    p, _ = ruby.pressure(s["reference_nm"] + shift, s)
    assert p == pytest.approx(0.0, abs=1e-10)
    center = s["reference_nm"] * (1 + 20 * s["B"] / s["A_GPa"]) ** (1 / s["B"]) + shift
    assert ruby.pressure(center, s)[0] == pytest.approx(20.0, abs=1e-9)


def test_ipps_ruby2020_published_equation_and_range():
    s = ruby.settings({"pressure_scale": "ruby2020"})
    x = 0.01
    center = s["ruby2020_reference_nm"] * (1.0 + x)
    expected = 1870.0 * x * (1.0 + 5.63 * x)
    value, shift = ruby.pressure(center, s)
    assert shift == pytest.approx(0.0)
    assert value == pytest.approx(expected)
    metadata = ruby.pressure_scale_metadata(value, s)
    assert metadata["pressure_scale"] == "ruby2020"
    assert metadata["scale_uncertainty_percent"] == 2.5
    assert metadata["scale_uncertainty_GPa"] == pytest.approx(abs(value) * 0.025)
    assert not ruby.pressure_warnings(150.0, s)
    assert "150 GPa" in ruby.pressure_warnings(150.01, s)[0]


def test_published_ragan_wavenumber_and_datchi_branches():
    s = ruby.settings()
    # Independently tabulated evaluation of Ragan's Eq. (3) at 300 K.
    assert ruby.thermal_position(300.0, s) == pytest.approx(1e7 / 14403.197)
    s["thermal_model"] = "datchi"
    assert ruby.thermal_position(15.0, s) == -0.887
    assert ruby.thermal_position(296.0, s) == 0.0
    assert ruby.thermal_position(600.0, s) == pytest.approx(0.00726 * 304.0)
    with pytest.raises(ValueError):
        ruby.thermal_position(601.0, s)
    s["thermal_model"] = "datchi_hot"
    with pytest.raises(ValueError):
        ruby.thermal_position(100.0, s)


def synthetic_curve():
    x = np.linspace(689.0, 701.0, 1801)
    y = 100.0 + 2.0 * (x - 695.0)
    for center, width, area in [(693.8, 0.35, 600.0), (695.2, 0.7, 1100.0)]:
        y += _pseudo_voigt(x, {"area": area, "center": center, "fwhm": width, "eta": 0.5}, {})
    return Curve("ruby_synthetic", x, y, source="ruby_synthetic.txt")


def test_free_widths_fixed_shape_background_and_room_temperature():
    curve = synthetic_curve()
    model, result, meta = ruby.analyse_curve(curve, ruby.settings({"background_fixed": False}))
    assert result.success
    assert meta["R1_nm"] == pytest.approx(695.2, abs=1e-5)
    assert meta["R2_nm"] == pytest.approx(693.8, abs=1e-5)
    assert meta["FWHM_R1_nm"] == pytest.approx(0.7, abs=1e-4)
    assert meta["FWHM_R2_nm"] == pytest.approx(0.35, abs=1e-4)
    assert all(
        c.parameters["eta"].fixed and c.parameters["eta"].value == 0.5 for c in model.components[1:]
    )
    assert all(not c.parameters["fwhm"].fixed for c in model.components[1:])
    assert meta["pressure_GPa"] is not None and meta["temperature_K"] == 296
    assert meta["pressure_std_GPa"] is not None
    assert "Ruby background temporary" not in curve.masks
    for center in [693.8, 695.2]:
        assert not curve.effective_mask[np.argmin(abs(curve.x - center))]
    assert curve.effective_mask[0] and curve.effective_mask[-1]
    assert meta["background_points"] > 8


def test_fit_and_settings_survive_project_save(tmp_path):
    project = Project()
    project.add_series(Series("Test", [synthetic_curve()]))
    context = PluginContext(project, project.curves[0].id, (project.curves[0].id,), ruby.OWNER)
    context.data.update(ruby.settings({"background_fixed": False}))
    text = ruby.process(context)
    assert "GPa" in text
    path = tmp_path / "ruby.fitproj"
    save_project(project, path)
    loaded = load_project(path)
    meta = loaded.curves[0].metadata["ruby_monitor"]
    assert meta["pressure_GPa"] is not None
    assert meta["settings"]["reference_nm"] == 694.281
    assert len(loaded.models[loaded.curves[0].id].components) == 3
    assert loaded.models[loaded.curves[0].id].components[1].parameters["eta"].fixed


def test_failed_analysis_does_not_report_a_pressure():
    project = Project()
    project.add_curve(Curve("ruby_bad", [690.0, 691.0, 692.0], [0.0, 0.0, 0.0]))
    context = PluginContext(project, project.curves[0].id, (), ruby.OWNER)
    ruby.process(context)
    assert project.curves[0].metadata["ruby_monitor"]["pressure_GPa"] is None
    assert "error" in project.curves[0].metadata["ruby_monitor"]


def test_folder_to_plugin_to_main_plot(tmp_path):
    import time

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    window = CurveMoleMainWindow(Project())
    identifier = ruby.OWNER + ":test_processor"
    extensions.entries[identifier] = Contribution(
        ruby.OWNER, identifier, "Ruby test", "import_processors", ruby.process
    )
    window.project.ui_state["plugin_data"] = {
        ruby.OWNER: ruby.settings({"temperature_confirmed": True})
    }
    controller = window.folder_import
    controller.start(tmp_path, "ruby", processor=identifier, settle=0.1)
    curve = synthetic_curve()
    np.savetxt(tmp_path / "ruby.0", np.column_stack([curve.x, curve.y]))
    deadline = time.monotonic() + 10
    try:
        while not window.project.curves and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert len(window.project.curves) == 1
        imported = window.project.curves[0]
        assert imported.metadata["ruby_monitor"]["pressure_GPa"] is not None
        assert set(window.plot_workspace._data_items) == {imported.id}
        assert len(window.project.models[imported.id].components) == 3
        assert window.project.results["last_fit"].success
        window.undo_stack.undo()
        assert not window.project.curves
        assert "last_fit" not in window.project.results
        window.undo_stack.redo()
        assert len(window.project.curves) == 1
    finally:
        controller.stop()
        window.project.dirty = False
        window.close()
        extensions.entries.pop(identifier, None)


def test_real_plugin_load_and_unload():
    from pathlib import Path

    from curvemole.core.plugins import PluginManager

    manager = PluginManager()
    candidate = manager.discover_local(Path(__file__).parent)[0]
    manager.load(candidate, trust=True)
    try:
        assert ruby.OWNER + ":automatic" in extensions.entries
        assert len([e for e in extensions.entries.values() if e.owner == ruby.OWNER]) == 5
    finally:
        manager.disable(ruby.OWNER)
    assert not any(e.owner == ruby.OWNER for e in extensions.entries.values())


def test_english_report_and_csv(tmp_path):
    import csv
    import json

    project = Project()
    project.add_curve(synthetic_curve())
    context = PluginContext(project, project.curves[0].id, (), ruby.OWNER)
    context.data.update(ruby.settings({"background_fixed": False}))
    ruby.process(context)
    report = json.loads(ruby.report(context))
    assert report[0]["pressure_GPa"] is not None
    context.path = str(tmp_path / "pressures.csv")
    ruby.export(context)
    with open(context.path, newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert float(rows[0]["R1_nm"]) == pytest.approx(695.2, abs=1e-5)
    assert float(rows[0]["pressure_GPa"]) == pytest.approx(report[0]["pressure_GPa"])
    assert rows[0]["thermal_model"] == "ragan"
    assert float(rows[0]["pressure_std_GPa"]) == pytest.approx(report[0]["pressure_std_GPa"])


def test_english_settings_save():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QCheckBox, QDialogButtonBox, QTabWidget

    project = Project()
    context = PluginContext(project, None, (), ruby.OWNER)
    observed = {}

    def save_dialog():
        dialog = QApplication.activeModalWidget()
        observed["title"] = dialog.windowTitle()
        observed["tab"] = dialog.findChild(QTabWidget).tabText(0)
        assert not any("Confirm" in box.text() for box in dialog.findChildren(QCheckBox))
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()

    QTimer.singleShot(0, save_dialog)
    ruby.configure(context)
    assert observed["title"] == "Ruby fluorescence pressure monitor — settings"
    assert observed["tab"] == "Measurement and fit"
    assert "temperature_confirmed" not in context.data
    assert context.data["eta"] == 0.5


def test_manual_mask_refit_and_temperature_keep_acquisition_reference(tmp_path):
    import json

    from curvemole.core.data import CurveState, Mask
    from curvemole.core.fitting import FitSettings, Fitter

    project = Project()
    project.add_curve(synthetic_curve())
    curve = project.curves[0]
    context = PluginContext(project, curve.id, (curve.id,), ruby.OWNER)
    context.data.update(ruby.settings({"background_fixed": False}))
    ruby.process(context)
    initial = ruby.current_result(context, curve)
    # A later acquisition temperature must not silently alter this spectrum.
    context.data["temperature_K"] = 450
    assert ruby.current_result(context, curve)["pressure_GPa"] == initial["pressure_GPa"]
    model = project.models[curve.id]
    r1 = model.components[-1]
    r1.parameters["center"].value = 695.3
    r1.parameters["center"].fixed = True
    curve.state = CurveState.MODIFIED
    assert ruby.current_result(context, curve)["needs_recalculation"]
    assert ruby.current_result(context, curve)["pressure_GPa"] == initial["pressure_GPa"]
    mask = curve.effective_mask.copy()
    mask[800:810] = True
    curve.masks["Manual correction"] = Mask("Manual correction", mask)
    result = Fitter().fit_single(curve, model, FitSettings())
    assert result.success
    assert ruby.current_result(context, curve)["needs_recalculation"]
    ruby.recalculate_curve(context, curve)
    updated = json.loads(ruby.report(context))[0]
    assert updated["R1_nm"] == pytest.approx(695.3)
    assert updated["pressure_GPa"] == pytest.approx(ruby.pressure(695.3, ruby.settings())[0])
    assert updated["pressure_GPa"] != initial["pressure_GPa"]
    assert "Manual correction" in curve.masks
    context.path = str(tmp_path / "manual.csv")
    ruby.export(context)
    with open(context.path) as stream:
        assert "695.3" in stream.read()


def test_monitor_controls_settings_and_manual_edit_during_import(tmp_path):
    from PySide6.QtWidgets import QApplication

    from curvemole.core.data import CurveState, Mask

    window = CurveMoleMainWindow(Project())
    identifier = ruby.OWNER + ":automatic"
    extensions.entries[identifier] = Contribution(
        ruby.OWNER, identifier, "Ruby test", "import_processors", ruby.process
    )
    window.project.add_curve(synthetic_curve())
    curve = window.project.curves[0]
    window.active_curve_id = curve.id
    initial = PluginContext(window.project, curve.id, (curve.id,), ruby.OWNER)
    initial.data.update(ruby.settings({"temperature_confirmed": True}))
    ruby.process(initial)
    window.refresh_all()
    window.curve_tree.topLevelItem(0).child(0).setSelected(True)
    context = window.plugin_host.context(ruby.OWNER, with_services=True)
    panel = ruby.monitor_panel(context)
    try:
        def settings_action(snapshot):
            snapshot.settings_only = True
            snapshot.data["temperature_K"] = 310

        window.plugin_host.run(Contribution(ruby.OWNER, ruby.OWNER + ":settings_test",
                                            "Settings", "actions", settings_action))
        assert window.project.dataset.curve(curve.id).state == CurveState.FITTED
        assert window.curve_tree.selected_curve_ids() == {curve.id}
        window.undo_stack.undo()

        panel.folder.setText(str(tmp_path))
        panel.temperature.setValue(350)
        panel.start.click()
        assert window.folder_import.scan is not None
        assert window.project.ui_state["plugin_data"][ruby.OWNER]["temperature_K"] == 350
        assert curve.state == CurveState.FITTED
        # Temperature is explicitly applied to selected existing spectra, undoable.
        panel.refresh()
        assert curve.metadata["ruby_monitor"]["settings"]["temperature_K"] == 350
        window.undo_stack.undo()  # Undo saved acquisition folder/filter.
        window.undo_stack.undo()  # Undo the automatic per-spectrum temperature save.
        assert curve.metadata["ruby_monitor"]["settings"]["temperature_K"] == 296
        assert curve.state == CurveState.FITTED
        panel.follow.setChecked(False)
        assert window.folder_import.follow is False
        window.folder_import.show()
        dialog = window.folder_import.dialog
        assert dialog.folder.text() == str(tmp_path)
        assert dialog.processor.currentData() == identifier
        assert dialog.stop_button.isEnabled() and not dialog.start_button.isEnabled()
        assert dialog.follow.isEnabled() and not dialog.follow.isChecked()
        dialog.follow.setChecked(True)
        assert window.folder_import.follow is True
        dialog.follow.setChecked(False)
        dialog.hide()
        selected = window.curve_tree.selected_curve_ids()
        # A background acquisition must retain the spectrum being edited and its masks.
        curve.masks["manual"] = Mask("manual", np.zeros(curve.x.size, dtype=bool))
        curve.masks["manual"].excluded[400:420] = True
        curve.state = CurveState.MODIFIED
        acquisition = Project()
        acquisition.add_curve(synthetic_curve())
        ruby.process(PluginContext(acquisition, acquisition.curves[0].id, (), ruby.OWNER))
        window.folder_import.commit(acquisition)
        assert window.active_curve_id == curve.id
        assert window.curve_tree.selected_curve_ids() == selected
        assert window.project.dataset.curve(curve.id).masks["manual"].excluded[410]
        panel.refresh()
        assert "needs recalculation" in panel.warning.text()
        assert window.folder_import.scan is not None
        panel.stop.click()
        assert window.folder_import.scan is None
        assert panel.start.isEnabled()
        assert len(window.project.curves) == 2
        # Service use is forbidden after unloading; read-only hook snapshots have no service.
        assert window.plugin_host.context(ruby.OWNER).services is None
        extensions.entries.pop(identifier)
        with pytest.raises(ValueError, match="disabled"):
            context.services.start_monitor(tmp_path, "ruby")
    finally:
        panel.timer.stop()
        panel.deleteLater()
        window.folder_import.stop()
        window.project.dirty = False
        window.close()
        QApplication.processEvents()
        extensions.entries.pop(identifier, None)


@pytest.mark.parametrize("scale", ["mao_1986", "ruby2020"])
def test_pressure_uncertainty_matches_numerical_derivative(scale):
    from curvemole.core.parameters import Parameter

    s = ruby.settings({"temperature_K": 450, "pressure_scale": scale})
    center = 696.2
    parameter = Parameter("center", center, standard_error=0.012)
    # Compare the analytical propagation with an independent central difference.
    h = 1e-4
    derivative = (ruby.pressure(center + h, s)[0] - ruby.pressure(center - h, s)[0]) / (2 * h)
    meta = ruby.pressure_uncertainty(center, parameter, s)
    assert meta["pressure_std_GPa"] == pytest.approx(abs(derivative) * 0.012, rel=1e-7)
    assert "1σ" in ruby.pressure_text({"pressure_GPa": 5, **meta})
    parameter.fixed = True
    assert ruby.pressure_uncertainty(center, parameter, s)["pressure_std_GPa"] is None
    parameter.fixed = False
    parameter.standard_error = None
    assert ruby.pressure_uncertainty(center, parameter, s)["pressure_std_GPa"] is None


def test_exact_background_mask_inversion_and_gui_unmask_undo(monkeypatch, tmp_path):
    from curvemole.core.fitting import Fitter

    snapshots = []
    fit = Fitter.fit_single

    def record(self, curve, model, *args, **kwargs):
        snapshots.append((curve.effective_mask.copy(), model.components[0].parameters["slope"].fixed))
        return fit(self, curve, model, *args, **kwargs)

    monkeypatch.setattr(Fitter, "fit_single", record)
    project = Project()
    project.add_curve(synthetic_curve())
    curve = project.curves[0]
    context = PluginContext(project, curve.id, (curve.id,), ruby.OWNER)
    context.data.update({"temperature_confirmed": False})  # Legacy flag never gates pressure.
    ruby.process(context)
    assert len(snapshots) == 2
    np.testing.assert_array_equal(snapshots[0][0], ~snapshots[1][0])
    assert snapshots[0][1] is False and snapshots[1][1] is True
    assert curve.metadata["ruby_monitor"]["temperature_K"] == 296
    assert curve.metadata["ruby_monitor"]["pressure_GPa"] is not None
    assert curve.active_mask == "Ruby local fit region"
    assert all(not p.fixed for p in project.models[curve.id].components[0].parameters.values())
    window = CurveMoleMainWindow(project)
    try:
        window.active_curve_id = curve.id
        window.refresh_all()
        window.curve_tree.topLevelItem(0).child(0).setSelected(True)
        assert curve.effective_mask[0]
        window.folder_import.start(tmp_path, "ruby", follow=False)
        window.mask_point(curve.x[0], unmask=True)
        assert not curve.effective_mask[0]
        window.mask_point(curve.x[0])
        assert curve.effective_mask[0]
        window.folder_import.stop()
        window.mask_range(curve.x[0], curve.x[4], unmask=True)
        assert not curve.effective_mask[:5].any()
        window.undo_stack.undo()
        assert curve.effective_mask[:5].all()
        window.undo_stack.redo()
        assert not curve.effective_mask[:5].any()
        window.mask_range(curve.x[1], curve.x[3])
        assert curve.effective_mask[1:4].all()
    finally:
        project.dirty = False
        window.close()


def test_auto_docked_panel_and_temperature_autosave(tmp_path):
    from PySide6.QtWidgets import QApplication, QCheckBox, QDockWidget

    window = CurveMoleMainWindow(Project())
    processor_id, panel_id = ruby.OWNER + ":automatic", ruby.OWNER + ":monitor"
    extensions.entries[processor_id] = Contribution(ruby.OWNER, processor_id, "Ruby", "import_processors", ruby.process)
    extensions.entries[panel_id] = Contribution(ruby.OWNER, panel_id, "Ruby", "panels", ruby.monitor_panel, auto_show=True)
    try:
        window.plugin_host.refresh()
        QApplication.processEvents()
        dock = window.plugin_host.dialogs[panel_id]
        assert isinstance(dock, QDockWidget) and not dock.isFloating()
        panel = dock.widget().widget()
        assert panel.temperature.value() == 296
        assert not any("Confirm" in box.text() for box in panel.findChildren(QCheckBox))
        panel.temperature.setValue(320)
        panel.temperature.editingFinished.emit()
        assert window.project.ui_state["plugin_data"][ruby.OWNER]["temperature_K"] == 320
        assert "temperature_confirmed" not in window.project.ui_state["plugin_data"][ruby.OWNER]
        window.plugin_host.refresh()
        QApplication.processEvents()
        assert window.plugin_host.dialogs[panel_id] is dock
        # Automatically opening the panel must not automatically start acquisition.
        assert window.folder_import.scan is None
        extensions.entries.pop(panel_id)
        window.plugin_host.refresh()
        assert not dock.isVisible()
    finally:
        extensions.entries.pop(panel_id, None)
        extensions.entries.pop(processor_id, None)
        window.project.dirty = False
        window.close()


def test_per_spectrum_review_recalculate_and_persistence(tmp_path, monkeypatch):
    import copy

    from PySide6.QtWidgets import QPushButton

    from curvemole.core.data import CurveState

    window = CurveMoleMainWindow(Project())
    identifier = ruby.OWNER + ":automatic"
    extensions.entries[identifier] = Contribution(ruby.OWNER, identifier, "Ruby", "import_processors", ruby.process)
    acquisitions = []
    for temperature in (296, 360):
        project = Project()
        project.add_curve(synthetic_curve())
        context = PluginContext(project, project.curves[0].id, (), ruby.OWNER)
        context.data.update(ruby.settings({"temperature_K": temperature}))
        ruby.process(context)
        acquisitions.append(project)
    window.folder_import.follow = False
    window.folder_import.commit(acquisitions[0])
    first = window.project.curves[0]
    window.active_curve_id = first.id
    window.refresh_all()
    panel = ruby.monitor_panel(window.plugin_host.context(ruby.OWNER, with_services=True))
    try:
        labels = {button.text() for button in panel.findChildren(QPushButton)}
        assert "Recalculate" in labels
        assert "Apply temperature" not in labels
        assert not any("Edit fit mask" in label for label in labels)
        assert panel.temperature.value() == 296
        saved = copy.deepcopy(first.metadata["ruby_monitor"]["calculated_result"])
        panel.temperature.setValue(320)
        panel.refresh()
        assert first.metadata["ruby_monitor"]["settings"]["temperature_K"] == 320
        assert first.metadata["ruby_monitor"]["calculated_result"] == saved
        assert "needs recalculation" in panel.warning.text()
        assert "#fff0bf" in panel.result.styleSheet()
        panel.recalculate.click()
        updated = first.metadata["ruby_monitor"]["calculated_result"]
        assert updated["temperature_K"] == 320
        assert updated["pressure_GPa"] != saved["pressure_GPa"]
        assert not panel.warning.text()
        assert "#155e4b" in panel.result.styleSheet()
        # Acquisition commits preserve all edits and the current selection.
        window.folder_import.start(tmp_path, "ruby", processor=identifier, follow=False)
        window.mask_range(first.x[0], first.x[5], unmask=True)
        assert not first.effective_mask[:6].any()
        window.folder_import.commit(acquisitions[1])
        second = window.project.curves[1]
        assert window.active_curve_id == first.id
        assert first.metadata["ruby_monitor"]["settings"]["temperature_K"] == 320
        assert not first.effective_mask[:6].any()
        window.active_curve_id = second.id
        panel.refresh()
        assert panel.temperature.value() == 360
        assert second.name in panel.spectrum.text()
        assert not panel.warning.text()
        window.active_curve_id = first.id
        panel.refresh()
        assert panel.temperature.value() == 320
        assert "needs recalculation" in panel.warning.text()
        # A direct model edit remains local and can be explicitly evaluated.
        r1 = window.project.models[first.id].components[-1]
        r1.parameters["center"].value += 0.02
        first.state = CurveState.MODIFIED
        panel.recalculate.click()
        assert not panel.warning.text()
        assert first.metadata["ruby_monitor"]["calculated_result"]["pressure_std_GPa"] is None
        assert second.metadata["ruby_monitor"]["settings"]["temperature_K"] == 360
        last_pressure = first.metadata["ruby_monitor"]["calculated_result"]["pressure_GPa"]
        def edit_calibration(snapshot):
            snapshot.data["A_GPa"] = 1950.0
            return True
        monkeypatch.setattr(ruby, "configure_dialog", edit_calibration)
        panel.configure()
        panel.refresh()
        assert first.metadata["ruby_monitor"]["settings"]["A_GPa"] == 1950.0
        assert second.metadata["ruby_monitor"]["settings"]["A_GPa"] == 1904.0
        assert first.metadata["ruby_monitor"]["calculated_result"]["pressure_GPa"] == last_pressure
        assert "needs recalculation" in panel.warning.text()
        panel.recalculate.click()
        assert not panel.warning.text()
        assert first.metadata["ruby_monitor"]["calculated_result"]["pressure_GPa"] != last_pressure
        path = tmp_path / "per-spectrum.fitproj"
        save_project(window.project, path)
        loaded = load_project(path)
        ctx = PluginContext(loaded, first.id, (), ruby.OWNER)
        assert not ruby.current_result(ctx, loaded.dataset.curve(first.id))["needs_recalculation"]
        assert loaded.dataset.curve(first.id).metadata["ruby_monitor"]["settings"]["temperature_K"] == 320
        assert not loaded.dataset.curve(first.id).effective_mask[:6].any()
        assert loaded.dataset.curve(second.id).metadata["ruby_monitor"]["settings"]["temperature_K"] == 360
    finally:
        panel.timer.stop()
        panel.deleteLater()
        window.folder_import.stop()
        window.project.dirty = False
        window.close()
        extensions.entries.pop(identifier, None)
