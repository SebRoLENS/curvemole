from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QInputDialog

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
    assert row["status"] == "Not assessed"
    assert row["confidence_level"] == .9
    row = next(r for r in summarize(p, record, a, method, {path:.2}) if r["path"] == path)
    assert row["status"] == "OK"
    row = next(r for r in summarize(p, record, a, method, {path:.01}) if r["path"] == path)
    assert row["status"] == "Attention"


def test_bound_coverage_and_missing_results_never_green(gaussian_curve):
    p, b = setup(gaussian_curve)
    record = b.to_dict()
    path = next(iter(record["parameters"]))
    record["parameters"][path].update(value=.5, minimum=0, maximum=1)
    a = dict(parameter_paths=[path], intervals={path:[0., 1.]}, completed=200, failed=0)
    r = summarize(p, record, a, "block_bootstrap", {path:100})[0]
    assert r["status"] == "Critical" and "80%" in r["reasons"]
    a.update(intervals={}, completed=0, failed=200)
    assert summarize(p, record, a, "residual_bootstrap", {path:100})[0]["status"] == "Critical"


def test_correlation_and_profile_edge_have_explanations(gaussian_curve):
    p, b = setup(gaussian_curve)
    record = b.to_dict()
    record["correlation"] = np.ones((3,3)).tolist()
    rows = summarize(p, record, {}, "covariance")
    assert all("Strong parameter correlation" in row["reasons"] for row in rows)
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
    assert other.uncertainty_panel.results.table.item(0,1).text() == "NH2 stretching α"
    export_bundle(reopened, tmp_path / "export", selection=BundleExportSelection(fit_results=False, uncertainty=True))
    assert "NH2 stretching α" in (tmp_path / "export/uncertainty/parameter_assessments.csv").read_text(encoding="utf-8")
    p.dirty = reopened.dirty = False
    window.close()
    other.close()
    app.processEvents()


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
