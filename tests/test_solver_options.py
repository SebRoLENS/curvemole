from __future__ import annotations

import json
from dataclasses import asdict

import pytest
from PySide6.QtWidgets import QApplication

from curvemole import Component, Fitter, Model, Project
from curvemole.core.errors import FitError
from curvemole.core.export import BundleExportSelection, export_bundle
from curvemole.core.fitting import FitResult, FitSettings
from curvemole.gui.dialogs import FitPlanDialog


def test_controls_follow_algorithm_loss_and_reset_preserves_selection(gaussian_curve):
    app = QApplication.instance() or QApplication([])
    p = Project()
    p.add_curve(gaussian_curve)
    d = FitPlanDialog(p, {gaussian_curve.id}, FitSettings())
    assert d.plan().settings.solver == "local"
    assert d.plan().settings.loss == "linear"
    assert d.f_scale.isHidden()
    d.loss.setCurrentText("huber")
    assert not d.f_scale.isHidden()
    d.f_scale.setText("2.5")
    d.solver.setCurrentIndex(d.solver.findData("powell"))
    assert not d.solver_options.fields["powell_ftol"].isHidden()
    assert d.solver_options.fields["de_popsize"].isHidden()
    d.solver_options.fields["powell_ftol"].setText("2e-5")
    plan = d.plan()
    assert plan.settings.f_scale == 2.5
    assert plan.settings.powell_ftol == 2e-5
    d.reset_defaults.click()
    plan = d.plan()
    assert plan.curve_ids == [gaussian_curve.id]
    assert plan.settings.solver == "powell" and plan.settings.loss == "huber"
    expected = asdict(FitSettings(solver="powell", loss="huber"))
    assert asdict(plan.settings) == expected
    d.solver.setCurrentIndex(d.solver.findData("differential_evolution"))
    assert not d.solver_options.fields["de_popsize"].isHidden()
    d.close()
    app.processEvents()


@pytest.mark.parametrize("kwargs", [
    {"f_scale": 0}, {"xtol": float("nan")}, {"de_recombination": 1.1},
    {"de_mutation_min": 1.5, "de_mutation_max": 1.0}, {"x_scale": 0},
    {"nm_initial_simplex": [[0, 1]]}, {"minimize_maxiter": -1},
])
def test_invalid_advanced_options_rejected(kwargs):
    with pytest.raises(FitError):
        FitSettings(**kwargs).validate()


@pytest.mark.parametrize("solver,key,value", [
    ("nelder_mead", "xatol", 2e-5),
    ("powell", "xtol", 3e-5),
    ("lbfgsb", "maxls", 30),
])
def test_minimize_options_reach_scipy(monkeypatch, gaussian_curve, solver, key, value):
    from curvemole.core import fitting
    real = fitting.optimize.minimize
    captured = {}

    def run(*args, **kwargs):
        captured.update(kwargs["options"])
        return real(*args, **kwargs)

    monkeypatch.setattr(fitting.optimize, "minimize", run)
    s = FitSettings(solver=solver, nm_xatol=2e-5, powell_xtol=3e-5, lbfgsb_maxls=30,
                    minimize_maxiter=500, max_nfev=3000)
    model = Model(components=[Component.create("gaussian", initial={"area": 3, "center": .7, "sigma": .8})])
    result = Fitter().fit_single(gaussian_curve, model, s)
    assert result.success
    assert captured[key] == value and captured["maxiter"] == 500


def test_de_and_least_squares_options_reach_scipy(monkeypatch, gaussian_curve):
    from curvemole.core import fitting
    real_de, real_ls = fitting.optimize.differential_evolution, fitting.optimize.least_squares
    seen = {}

    def de(*args, **kwargs):
        seen["de"] = kwargs.copy()
        return real_de(*args, **kwargs)

    def ls(*args, **kwargs):
        seen["ls"] = kwargs.copy()
        return real_ls(*args, **kwargs)

    monkeypatch.setattr(fitting.optimize, "differential_evolution", de)
    monkeypatch.setattr(fitting.optimize, "least_squares", ls)
    s = FitSettings(solver="differential_evolution", loss="soft_l1", f_scale=2,
                    de_maxiter=2, de_popsize=5, de_mutation_min=.4, de_mutation_max=.9,
                    de_recombination=.6, de_tol=.02, de_atol=.001, xtol=1e-7)
    model = Model(components=[Component.create("gaussian", initial={"area": 3, "center": .7, "sigma": .8})])
    Fitter().fit_single(gaussian_curve, model, s)
    assert seen["de"]["mutation"] == (.4, .9)
    assert seen["de"]["recombination"] == .6
    assert seen["de"]["tol"] == .02 and seen["de"]["atol"] == .001
    assert seen["ls"]["f_scale"] == 2 and seen["ls"]["xtol"] == 1e-7


def test_all_recorded_settings_export_and_round_trip(gaussian_curve, tmp_path):
    import pandas as pd

    p = Project()
    p.add_curve(gaussian_curve)
    model = Model(components=[Component.create("gaussian", initial={"area": 3, "center": .7, "sigma": .8})])
    p.models[gaussian_curve.id] = model
    settings = FitSettings(loss="soft_l1", f_scale=2.5, de_popsize=19, nm_adaptive=True)
    result = Fitter().fit_single(gaussian_curve, model, settings)
    p.results["last_fit"] = result
    assert asdict(FitResult.from_dict(result.to_dict()).settings) == asdict(settings)
    export_bundle(p, tmp_path / "export", selection=BundleExportSelection(
        fit_settings=True, results_json=True, html_reproducibility=True))
    root = tmp_path / "export"
    df = pd.read_csv(root / "fit_settings.csv", keep_default_na=False)
    exported = {row.setting: json.loads(row.value) for row in df.itertuples()}
    assert exported == asdict(settings)
    payload = json.loads((root / "python/results.json").read_text())
    assert payload["result"]["settings"] == asdict(settings)
    assert "f_scale" in (root / "report/full_reproducibility.html").read_text()
    params = pd.read_csv(root / "fit_results.csv")
    assert set(params.parameter) == {"area", "center", "sigma"}
