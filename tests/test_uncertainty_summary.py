from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from curvemole import Component, Fitter, Model, Project
from curvemole.core.export import BundleExportSelection, export_bundle
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
    record["parameters"][path].update(value=.5, minimum=0, maximum=1)
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
    assert all("Strong correlation with" in row["reasons"] for row in rows)
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
    assert other.uncertainty_panel.results.table.rowCount() == 3
    assert other.uncertainty_panel.results.table.columnCount() == 7
    assert other.uncertainty_panel.results.table.horizontalHeaderItem(6).text() == "Assessment"
    results = other.uncertainty_panel.results
    assert "Click to see" in results.table.item(0, 6).toolTip()
    assert not hasattr(results, "target_button")
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.informativeText()))
    results._cell_clicked(0, 6)
    assert len(shown) == 1 and "diagnostic issue" in shown[0]
    assert other.uncertainty_panel.results.table.item(0,1).text() == "NH2 stretching α"
    export_bundle(reopened, tmp_path / "export", selection=BundleExportSelection(fit_results=False, uncertainty=True))
    assert "NH2 stretching α" in (tmp_path / "export/uncertainty/parameter_assessments.csv").read_text(encoding="utf-8")
    assert "target" not in (tmp_path / "export/uncertainty/parameter_assessments.csv").read_text(encoding="utf-8").splitlines()[0]
    p.dirty = reopened.dirty = False
    window.close()
    other.close()
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
    assert "r=-0.970" in rows[0]["reasons"]


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
    assert window.uncertainty_panel.results.table.rowCount() == 3
    assert {window.uncertainty_panel.results.table.item(i, 0).text() for i in range(3)} == {"scan 0"}
    import time

    window.start_uncertainty("residual_bootstrap", 10, None)
    deadline = time.monotonic() + 10
    while window._thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert window._thread is None
    assert "residual_bootstrap" in project.results["uncertainty_reports_by_curve"][first]
    assert "residual_bootstrap" not in project.results["uncertainty_reports_by_curve"].get(second, {})
    window._set_active_curve(second)
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
    assert {window.uncertainty_panel.results.table.item(i, 0).text() for i in range(3)} == {"scan 1"}
    window._set_active_curve(first)
    assert {window.uncertainty_panel.results.table.item(i, 0).text() for i in range(3)} == {"scan 0"}

    path = tmp_path / "scans.fitproj"
    save_project(project, path)
    restored = load_project(path)
    other = MainWindow(restored)
    other.uncertainty_panel.method.setCurrentIndex(other.uncertainty_panel.method.findData("covariance"))
    other._set_active_curve(second)
    assert other.uncertainty_panel.results.table.rowCount() == 3
    assert other._fit_for_uncertainty(first)[0].curve_outputs.keys() == {first}
    assert other._fit_for_uncertainty(second)[0].curve_outputs.keys() == {second}
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
    assert window.uncertainty_panel.results.table.rowCount() == 3
    saved = dict(project.results)
    second = Fitter().fit_single(gaussian_curve, project.model_for(gaussian_curve.id))
    window._fit_finished(second)
    assert gaussian_curve.id in saved["uncertainty_reports_by_curve"]
    assert gaussian_curve.id not in project.results["uncertainty_reports_by_curve"]
    assert window.uncertainty_panel.results.table.rowCount() == 0
    project.dirty = False
    window.close()
    app.processEvents()
