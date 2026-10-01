from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from curvemole import Component, Fitter, Model, Project
from curvemole.core.data import CurveState
from curvemole.core.export import BundleExportSelection, export_bundle, export_function_parameters
from curvemole.core.serialization import load_project, save_project
from curvemole.core.uncertainty_summary import summarize
from curvemole.gui.main_window import MainWindow
from curvemole.gui.panels import UncertaintyPanel


def setup(gaussian_curve):
    p = Project()
    p.add_curve(gaussian_curve)
    m = Model(components=[Component.create("gaussian", initial={"area": 3, "center": .7, "sigma": .8})])
    p.models[gaussian_curve.id] = m
    baseline = Fitter().fit_single(gaussian_curve, m)
    return p, baseline


@pytest.mark.parametrize("method", ["covariance", "parametric_monte_carlo", "residual_bootstrap", "block_bootstrap", "profile_likelihood"])
def test_every_method_uses_names_confidence_and_reasoned_assessment(gaussian_curve, method):
    p, baseline = setup(gaussian_curve)
    record = baseline.to_dict()
    path = next(iter(record["parameters"]))
    e = record["parameters"][path]
    e.update(value=3., ci_low=2.9, ci_high=3.1, minimum=0., maximum=10., at_bound=False)
    record["correlation"] = None
    if method == "profile_likelihood":
        a = dict(parameter_path=path, interval=[2.9, 3.1], values=[2., 3., 4.], failed_points=0, confidence_level=.9)
    else:
        a = dict(parameter_paths=[path], intervals={path:[2.9, 3.1]}, completed=200, failed=0, confidence_level=.9)
    row = next(r for r in summarize(p, record, a, method) if r["path"] == path)
    assert row["spectrum"] == gaussian_curve.name
    assert row["confidence_level"] == .9
    assert row["status"] in {"OK", "Attention"}
    assert "target" not in row
    if row["status"] == "OK":
        assert "No diagnostic issue" in row["reasons"]


def test_bound_coverage_and_missing_results_never_green(gaussian_curve):
    p, b = setup(gaussian_curve)
    record = b.to_dict()
    path = next(iter(record["parameters"]))
    record["parameters"][path].update(value=.5, minimum=0, maximum=1,
                                      global_minimum=0, global_maximum=1)
    a = dict(parameter_paths=[path], intervals={path:[0., 1.]}, completed=200, failed=0)
    r = summarize(p, record, a, "block_bootstrap")[0]
    assert r["status"] == "Critical" and "80%" in r["reasons"]
    a.update(intervals={}, completed=0, failed=200)
    assert summarize(p, record, a, "residual_bootstrap")[0]["status"] == "Critical"


def test_correlation_and_profile_edge_have_explanations(gaussian_curve):
    p, b = setup(gaussian_curve)
    record = b.to_dict()
    record["correlation"] = np.ones((3,3)).tolist()
    rows = summarize(p, record, {}, "covariance")
    assert all("Strong correlation in" in row["reasons"] for row in rows)
    assert all(any(other["parameter"] in row["reasons"] for other in rows if other is not row)
               for row in rows)
    path = b.free_parameter_paths[0]
    a = dict(parameter_path=path, interval=[1,2], values=[1,2,3], failed_points=0)
    r = summarize(p, record, a, "profile_likelihood")[0]
    assert "scanned range" in r["reasons"]


def test_names_are_undoable_and_survive_reopen_and_reports(gaussian_curve, monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    p, b = setup(gaussian_curve)
    curve_id = gaussian_curve.id
    component_id = p.models[curve_id].components[0].id
    p.results["last_fit"] = b
    window = MainWindow(p)
    before = p.models[curve_id].components[0].name
    state = gaussian_curve.state
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: ("NH2 stretching α", True))
    window.rename_function(curve_id, component_id)
    assert p.models[curve_id].components[0].name == "NH2 stretching α"
    assert gaussian_curve.state == state
    window.undo_stack.undo()
    assert p.models[curve_id].components[0].name == before
    window.undo_stack.redo()
    window._uncertainty_baseline = b
    window._uncertainty_finished(b)
    path = tmp_path / "names.fitproj"
    save_project(p, path)
    reopened = load_project(path)
    other = MainWindow(reopened)
    assert reopened.models[curve_id].components[0].name == "NH2 stretching α"
    other.uncertainty_panel.method.setCurrentIndex(other.uncertainty_panel.method.findData("covariance"))
    other.uncertainty_panel.results.set_project(reopened)
    assert other.uncertainty_panel.results.table.rowCount() == 4
    assert other.uncertainty_panel.results.table.columnCount() == 5
    assert other.uncertainty_panel.results.table.horizontalHeaderItem(4).text() == "Assessment"
    results = other.uncertainty_panel.results
    assert "Click to see" in results.table.item(1, 4).toolTip()
    assert not hasattr(results, "target_button")
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.informativeText()))
    results._cell_clicked(1, 4)
    assert len(shown) == 1 and "diagnostic issue" in shown[0]
    assert other.uncertainty_panel.results.table.item(0,0).text() == "NH2 stretching α"
    assert other.uncertainty_panel.results.table.item(1,0).text() in {"area", "center", "sigma"}
    export_bundle(reopened, tmp_path / "export", selection=BundleExportSelection(fit_results=False, uncertainty=True))
    assert "NH2 stretching α" in (tmp_path / "export/uncertainty/parameter_assessments.csv").read_text(encoding="utf-8")
    assert "target" not in (tmp_path / "export/uncertainty/parameter_assessments.csv").read_text(encoding="utf-8").splitlines()[0]
    p.dirty = reopened.dirty = False
    window.close()
    other.close()
    app.processEvents()


def test_spectrum_state_shows_uncertainty_only_when_an_analysis_exists(gaussian_curve):
    app = QApplication.instance() or QApplication([])
    project, baseline = setup(gaussian_curve)
    window = MainWindow(project)
    state_item = window.curve_tree.topLevelItem(0).child(0)

    assert state_item.text(2) == "Fitted"
    assert state_item.toolTip(2) == ""

    window._uncertainty_finished(baseline)
    state_item = window.curve_tree.topLevelItem(0).child(0)
    assert state_item.text(2) == "Fitted  ·  Uncertainty analysed"
    assert state_item.toolTip(2) == "Saved uncertainty analyses: Fit covariance"

    gaussian_curve.state = CurveState.MODIFIED
    window.curve_tree.populate(project, gaussian_curve.id)
    assert "Uncertainty analysis outdated" in window.curve_tree.topLevelItem(0).child(0).text(2)
    project.dirty = False
    window.close()
    app.processEvents()


def test_resampling_correlation_identifies_other_parameter_and_coefficient(gaussian_curve):
    p, baseline = setup(gaussian_curve)
    paths = baseline.free_parameter_paths[:2]
    baseline_record = baseline.to_dict()
    baseline_record["correlation"] = None
    analysis = dict(parameter_paths=paths, intervals={
        path: [baseline_record["parameters"][path]["value"] - .1,
               baseline_record["parameters"][path]["value"] + .1] for path in paths
    }, completed=200, failed=0, sample_correlation=[[1., -.97], [-.97, 1.]])
    rows = summarize(p, baseline_record, analysis, "block_bootstrap")
    assert len(rows) == 2
    assert rows[1]["parameter"] in rows[0]["reasons"]
    assert rows[0]["parameter"] in rows[0]["reasons"]
    assert gaussian_curve.name in rows[0]["reasons"]
    assert "r=-0.970" in rows[0]["reasons"]


def test_correlation_names_both_functions_and_preserves_custom_name(gaussian_curve):
    p, baseline = setup(gaussian_curve)
    model = p.model_for(gaussian_curve.id)
    model.components[0].name = "Gaussian2"
    paths = baseline.free_parameter_paths[:2]
    record = baseline.to_dict()
    record["correlation"] = [[1., -.954], [-.954, 1.]]
    record["free_parameter_paths"] = paths
    rows = summarize(p, record, {}, "covariance")
    assert (f"Strong correlation in {gaussian_curve.name}: Gaussian 2 "
            f"{rows[0]['parameter']} ↔ Gaussian 2 {rows[1]['parameter']} "
            "(r=-0.954)") in rows[0]["reasons"]
    model.components[0].name = "NH2 custom"
    model.components[0].metadata["custom_name"] = True
    rows = summarize(p, record, {}, "covariance")
    assert "NH2 custom" in rows[0]["reasons"]


def test_default_replicates_and_method_controls():
    app = QApplication.instance() or QApplication([])
    panel = UncertaintyPanel()
    assert panel.replicates.value() == 200
    panel.method.setCurrentIndex(panel.method.findData("profile_likelihood"))
    assert not panel.replicates.isEnabled()
    assert panel.profile_points.value() == 31
    panel.method.setCurrentIndex(panel.method.findData("monte_carlo"))
    assert panel.replicates.isEnabled()
    panel.close()
    app.processEvents()


def test_selected_analysis_adds_asymmetric_errors_without_replacing_fit_sigma(gaussian_curve, tmp_path):
    import csv

    from curvemole.core.uncertainty import ProfileResult, ResamplingResult

    app = QApplication.instance() or QApplication([])
    project, baseline = setup(gaussian_curve)
    curve_id = gaussian_curve.id
    path = baseline.free_parameter_paths[0]
    value = baseline.parameters[path].value
    original_sigma = project.model_for(curve_id).components[0].parameters[path.rsplit(".", 1)[-1]].standard_error
    window = MainWindow(project)
    interval = {path: (value - .2, value + .4)}
    bootstrap = ResamplingResult("residual_bootstrap", 200, 200, 0, 42, [path],
                                 np.array([[value]] * 200), interval, .95, {})
    window._store_uncertainty_result(curve_id, baseline, bootstrap)
    window.uncertainty_panel.set_parameters(project, curve_id)
    window.model_panel.refresh_parameters()
    assert window.uncertainty_panel.display_method.currentData() == "residual_bootstrap"
    assert "Model and parameters" in window.uncertainty_panel.form.labelForField(
        window.uncertainty_panel.display_method).toolTip()
    assert window.model_panel.parameters.item(0, 3).text() == "−0.2 / +0.4"
    assert "Calculated with Residual bootstrap (95.0% confidence)" in (
        window.model_panel.parameters.item(0, 3).toolTip())
    assert window.model_panel.parameters.item(0, 2).text() == f"{original_sigma:.5g}"

    profile = ProfileResult(path, np.array([value]), np.array([0.]), .95,
                            (value - .1, value + .3), 0)
    window._store_uncertainty_result(curve_id, baseline, profile)
    window.uncertainty_panel.set_parameters(project, curve_id)
    window.model_panel.refresh_parameters()
    assert window.model_panel.parameters.item(0, 3).text() == "−0.1 / +0.3"
    window.uncertainty_panel.display_method.setCurrentIndex(
        window.uncertainty_panel.display_method.findData("residual_bootstrap"))
    assert window.model_panel.parameters.item(0, 3).text() == "−0.2 / +0.4"

    export = export_function_parameters(project, tmp_path / "parameters.csv")
    with export.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    minus = rows[1].index("area_analysis_err_minus")
    assert rows[2][minus:minus + 2] == ["0.2", "0.4"]
    assert rows[2][-1] == "Residual bootstrap"
    assert rows[2][rows[1].index("area_err")] == f"{original_sigma:.12g}"

    saved = tmp_path / "saved.fitproj"
    save_project(project, saved)
    restored = load_project(saved)
    assert restored.results["uncertainty_display_method_by_curve"][curve_id] == "residual_bootstrap"
    assert restored.results["uncertainty_reports_by_curve"][curve_id]["profile_likelihood"]
    from curvemole.core.fitting import FitPlan

    window._running_fit_plan = FitPlan([curve_id])
    window._fit_finished(Fitter().fit_single(gaussian_curve, project.model_for(curve_id)))
    assert curve_id not in project.results["uncertainty_display_method_by_curve"]
    assert window.model_panel.parameters.item(0, 3).text() == "—"
    project.dirty = False
    window.close()
    app.processEvents()


def test_uncertainty_tracks_selected_spectrum_and_batch_survives_reopen(tmp_path):
    from curvemole import Curve
    from curvemole.core.fitting import FitPlan

    app = QApplication.instance() or QApplication([])
    project = Project()
    x = np.linspace(-4, 4, 81)
    curves = [Curve(f"scan {i}", x, np.exp(-.5 * ((x - center) / .7) ** 2))
              for i, center in enumerate((-.5, 1.0, 1.8))]
    for curve in curves:
        project.add_curve(curve)
        project.model_for(curve.id).add(Component.create(
            "gaussian", initial={"area": 1.5, "center": 0, "sigma": 1}))
    window = MainWindow(project)
    for curve in curves:
        window._running_fit_plan = FitPlan([curve.id])
        result = Fitter().fit_single(curve, project.model_for(curve.id))
        window._fit_finished(result)
    first, second, third = (curve.id for curve in curves)
    assert set(project.results["fit_by_curve"]) == {first, second, third}

    window._set_active_curve(first)
    window.start_uncertainty("covariance", 0, None)
    assert window.uncertainty_panel.results.table.rowCount() == 4
    assert window.uncertainty_panel.results.spectrum_heading.text() == "Spectrum: scan 0"
    import time

    window.start_uncertainty("residual_bootstrap", 10, None)
    deadline = time.monotonic() + 10
    while window._thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert window._thread is None
    assert "residual_bootstrap" in project.results["uncertainty_reports_by_curve"][first]
    assert "residual_bootstrap" not in project.results["uncertainty_reports_by_curve"].get(second, {})
    assert window.uncertainty_panel.display_method.currentData() == "residual_bootstrap"
    window._set_active_curve(second)
    assert window.uncertainty_panel.display_method.currentData() == ""
    assert window.uncertainty_panel.results.table.rowCount() == 0
    window.curve_tree.clearSelection()
    window.curve_tree.topLevelItem(0).child(0).setSelected(True)
    window.curve_tree.topLevelItem(0).child(2).setSelected(True)
    assert window.curve_tree.selected_curve_ids() == {first, third}
    window.start_uncertainty("covariance", 0, None, "selected")
    assert set(project.results["uncertainty_reports_by_curve"]) == {first, third}
    assert window.uncertainty_panel.results.table.rowCount() == 0
    window.start_uncertainty("covariance", 0, None, "all")
    assert set(project.results["uncertainty_reports_by_curve"]) == {first, second, third}
    from curvemole.core.export import uncertainty_dataframe

    rows = uncertainty_dataframe(project)
    assert len(rows[rows.method == "covariance"]) == 9
    assert "target" not in rows.columns
    assert window.uncertainty_panel.results.spectrum_heading.text() == "Spectrum: scan 1"
    window._set_active_curve(first)
    assert window.uncertainty_panel.display_method.currentData() == "residual_bootstrap"
    assert window.uncertainty_panel.results.spectrum_heading.text() == "Spectrum: scan 0"

    path = tmp_path / "scans.fitproj"
    save_project(project, path)
    restored = load_project(path)
    other = MainWindow(restored)
    other.uncertainty_panel.method.setCurrentIndex(other.uncertainty_panel.method.findData("covariance"))
    other._set_active_curve(second)
    assert other.uncertainty_panel.results.table.rowCount() == 4
    assert other._fit_for_uncertainty(first)[0].curve_outputs.keys() == {first}
    assert other._fit_for_uncertainty(second)[0].curve_outputs.keys() == {second}
    project.dirty = restored.dirty = False
    window.close()
    other.close()
    app.processEvents()


@pytest.mark.parametrize("legacy_project", [False, True])
def test_partial_parallel_batch_preserves_usable_baselines_after_reopen(tmp_path, legacy_project):
    import time

    from curvemole import Curve
    from curvemole.core.data import CurveState
    from curvemole.core.fitting import FitMode, FitPlan, FitSettings

    app = QApplication.instance() or QApplication([])
    project = Project()
    x = np.linspace(-4, 4, 81)
    curves = [Curve(f"scan {index}", x, np.exp(-.5 * ((x - center) / .7) ** 2))
              for index, center in enumerate((-.5, .8, 1.5))]
    for curve in curves:
        project.add_curve(curve)
        project.model_for(curve.id).add(Component.create(
            "gaussian", initial={"area": 1.5, "center": 0, "sigma": 1}))
    plan = FitPlan([curve.id for curve in curves], FitMode.INDEPENDENT,
                   FitSettings(workers=2))
    result = Fitter().fit(plan, curves, project.models)
    assert result.success
    # One failed member makes the merged batch unsuccessful while the other
    # spectra and their output arrays remain valid.
    result.success = False
    curves[-1].state = CurveState.FAILED
    window = MainWindow(project)
    if legacy_project:
        project.results["last_attempt"] = result
    else:
        window._running_fit_plan = plan
        window._fit_finished(result)
        assert set(project.results["fit_by_curve"]) == {curves[0].id, curves[1].id}

    path = tmp_path / "partial.fitproj"
    save_project(project, path)
    restored = load_project(path)
    other = MainWindow(restored)
    for curve in curves[:2]:
        baseline, selected_plan = other._fit_for_uncertainty(curve.id)
        assert baseline.success
        assert selected_plan.curve_ids == [curve.id]
        assert len(baseline.curve_outputs[curve.id].residual) == len(x)
    assert other._fit_for_uncertainty(curves[-1].id) is None
    other.start_uncertainty("residual_bootstrap", 10, None, "all", workers=2)
    deadline = time.monotonic() + 30
    while other._thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert other._thread is None
    assert set(restored.results["uncertainty_reports_by_curve"]) == {curves[0].id, curves[1].id}
    project.dirty = restored.dirty = False
    window.close()
    other.close()
    app.processEvents()


def test_refitting_a_spectrum_invalidates_its_previous_assessment(gaussian_curve):
    from curvemole.core.fitting import FitPlan

    app = QApplication.instance() or QApplication([])
    project = Project()
    project.add_curve(gaussian_curve)
    project.model_for(gaussian_curve.id).add(Component.create("gaussian"))
    window = MainWindow(project)
    window._running_fit_plan = FitPlan([gaussian_curve.id])
    first = Fitter().fit_single(gaussian_curve, project.model_for(gaussian_curve.id))
    window._fit_finished(first)
    window.start_uncertainty("covariance", 0, None)
    assert window.uncertainty_panel.results.table.rowCount() == 4
    saved = dict(project.results)
    second = Fitter().fit_single(gaussian_curve, project.model_for(gaussian_curve.id))
    window._fit_finished(second)
    assert gaussian_curve.id in saved["uncertainty_reports_by_curve"]
    assert gaussian_curve.id not in project.results["uncertainty_reports_by_curve"]
    assert window.uncertainty_panel.results.table.rowCount() == 0
    project.dirty = False
    window.close()
    app.processEvents()


def test_uncertainty_table_groups_parameters_under_each_function(gaussian_curve):
    app = QApplication.instance() or QApplication([])
    project = Project("grouped uncertainty")
    project.add_curve(gaussian_curve)
    model = project.model_for(gaussian_curve.id)
    model.add(Component.create("gaussian", name="First", initial={
        "area": 2, "center": -1, "sigma": 1,
    }))
    model.add(Component.create("gaussian", name="Second", initial={
        "area": 1, "center": 1, "sigma": 1,
    }))
    baseline = Fitter().fit_single(gaussian_curve, model)
    window = MainWindow(project)
    window._uncertainty_finished([(gaussian_curve.id, baseline, baseline)])
    table = window.uncertainty_panel.results.table
    assert window.uncertainty_panel.results.spectrum_heading.text() == (
        "Spectrum: " + gaussian_curve.name
    )
    assert table.rowCount() == 8
    assert table.item(0, 0).text() == model.components[0].name
    assert table.item(4, 0).text() == model.components[1].name
    assert {table.item(i, 0).text() for i in (1, 2, 3, 5, 6, 7)} == {
        "area", "center", "sigma",
    }
    assert table.item(0, 4) is None
    assert table.item(1, 4) is not None
    project.dirty = False
    window.close()
    app.processEvents()
