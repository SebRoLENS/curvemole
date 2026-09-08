from __future__ import annotations

import numpy as np
import pytest

from curvemole import Component, Curve, Model, Project
from curvemole.core.fitting import (
    CancellationToken,
    FitMode,
    FitPlan,
    FitSettings,
    Fitter,
    _Problem,
)
from curvemole.core.registry import default_registry


def test_default_fit_budget_is_1000_evaluations_with_stall_convergence() -> None:
    assert FitSettings().max_nfev == 1000
    assert FitPlan(["curve"]).settings.max_nfev == 1000
    assert FitSettings().xtol == pytest.approx(1e-8)


def test_explicit_fit_budget_and_xtol_are_preserved() -> None:
    settings = FitSettings(max_nfev=321, xtol=1e-12)
    assert settings.max_nfev == 321
    assert settings.xtol == pytest.approx(1e-12)


def test_converged_fit_is_accepted_before_full_evaluation_budget() -> None:
    x = np.linspace(0.0, 1.0, 51)
    curve = Curve("spectrum", x, np.full_like(x, 2.5))
    model = Model(components=[Component.create("constant", initial={"offset": 0.0})])
    settings = FitSettings(max_nfev=1000)

    result = Fitter(default_registry()).fit_single(curve, model, settings)

    assert result.success
    assert result.evaluations < settings.max_nfev
    assert result.parameters


def test_problem_reports_progress_exactly_every_20_evaluations() -> None:
    x = np.linspace(0.0, 1.0, 11)
    curve = Curve("spectrum", x, np.ones_like(x))
    model = Model(components=[Component.create("constant", initial={"offset": 0.0})])
    plan = FitPlan([curve.id], FitMode.INDEPENDENT, FitSettings(max_nfev=1000))
    events: list[tuple[float | None, str]] = []
    problem = _Problem(
        [curve],
        {curve.id: model},
        plan,
        default_registry(),
        CancellationToken(),
        lambda value, text: events.append((value, text)),
    )

    initial = problem.initial
    for _ in range(40):
        problem.residual(initial)

    assert [text for _, text in events] == ["Evaluation 20", "Evaluation 40"]
    assert events[0][0] == pytest.approx(20 / 1000)
    assert events[1][0] == pytest.approx(40 / 1000)


def test_gui_refreshes_plot_on_twentieth_evaluation_and_keeps_zoom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("PySide6", exc_type=ImportError)
    pytest.importorskip("pyqtgraph", exc_type=ImportError)
    from PySide6.QtWidgets import QApplication

    from curvemole.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    project = Project("live-fit-refresh")
    x = np.linspace(0.0, 1.0, 11)
    curve = Curve("spectrum", x, np.ones_like(x))
    project.add_curve(curve)
    project.model_for(curve.id).add(Component.create("constant", initial={"offset": 0.0}))
    project.dirty = False
    window = MainWindow(project)

    view_box = window.plot_workspace.view_box
    view_box.setRange(xRange=(0.2, 0.8), yRange=(-0.5, 1.5), padding=0)
    before = view_box.viewRange()
    refreshes: list[int] = []

    def fake_refresh(*_args: object) -> None:
        refreshes.append(1)
        view_box.setRange(xRange=(-10.0, 10.0), yRange=(-5.0, 5.0), padding=0)

    monkeypatch.setattr(window.plot_workspace, "refresh", fake_refresh)
    window._task_progress(19 / 1000, "Evaluation 19")
    assert not refreshes
    window._task_progress(20 / 1000, "Evaluation 20")

    after = view_box.viewRange()
    assert len(refreshes) == 1
    assert after[0] == pytest.approx(before[0])
    assert after[1] == pytest.approx(before[1])

    window.project.dirty = False
    window.close()
    app.processEvents()


@pytest.mark.parametrize("budget", [37, 2501])
def test_progress_uses_explicit_budget_and_reports_exact_limit(budget: int) -> None:
    x = np.arange(5.0)
    curve = Curve("budget", x, x)
    model = Model(components=[Component.create("constant")])
    events = []
    problem = _Problem(
        [curve], {curve.id: model}, FitPlan([curve.id], settings=FitSettings(max_nfev=budget)),
        default_registry(), CancellationToken(), lambda value, text: events.append((value, text)),
    )
    for _ in range(budget):
        problem.residual(problem.initial)
    assert events[-1] == (1.0, f"Evaluation {budget}")
    if budget > 1000:
        assert (1000 / budget, "Evaluation 1000") in events


@pytest.mark.parametrize("method", ["lm", "trf", "dogbox"])
def test_live_evaluation_budget_matches_solver_without_jacobian_probes(monkeypatch, method) -> None:
    from curvemole.core import live_fit_progress

    monkeypatch.setattr(live_fit_progress, "LIVE_REFRESH_EVERY", 1)
    x = np.linspace(-5, 5, 101)
    curve = Curve("budget", x, np.exp(-x * x))
    peak = Component.create("gaussian", initial={"area": 3, "center": 1, "sigma": 2})
    if method == "lm":
        for parameter in peak.parameters.values():
            parameter.minimum, parameter.maximum = -np.inf, np.inf
    events = []
    result = Fitter().fit_single(
        curve, Model(components=[peak]), FitSettings(max_nfev=7, local_method=method),
        progress=lambda value, text: events.append((value, text)),
    )
    evaluations = [(value, int(text.split()[1])) for value, text in events if text.startswith("Evaluation ")]
    assert evaluations[-1] == (result.evaluations / 7, result.evaluations)
    assert all(value == pytest.approx(count / 7) for value, count in evaluations)
    assert max(count for _, count in evaluations) == 7


def test_sequential_progress_credits_early_convergence_and_retains_total(monkeypatch) -> None:
    from curvemole.core import SequentialFitPlan, live_fit_progress

    monkeypatch.setattr(live_fit_progress, "LIVE_REFRESH_EVERY", 1)
    x = np.arange(10.0)
    curves = [Curve(str(i), x, np.full_like(x, float(i + 1))) for i in range(3)]
    models = {curves[0].id: Model(components=[Component.create("constant", initial={"offset": 1})])}
    plan = SequentialFitPlan(
        [curve.id for curve in curves], FitMode.SEQUENTIAL, FitSettings(max_nfev=100),
        monitor_residuals=False, monitor_parameters=False,
    )
    events = []
    result = Fitter().fit(plan, curves, models, progress=lambda value, text: events.append((value, text)))
    assert result.success
    assert result.evaluations < 100
    assert (0.5, "Completed 1") in events
    assert events[0][0] == 0
    assert events[-1][0] == 1
    assert [v for v, _ in events] == sorted(v for v, _ in events)
    assert any(0 < v < 0.5 for v, _ in events)
    assert any(0.5 < v < 1 for v, _ in events)

    plan.curve_ids = [curve.id for curve in curves[1:]]
    plan.progress_completed, plan.progress_total = 1, 2
    events.clear()
    Fitter().fit(plan, curves, models, progress=lambda value, text: events.append((value, text)))
    assert events[0][0] == 0.5
    assert events[-1][0] == 1


def test_sequential_pause_does_not_report_full_completion() -> None:
    from curvemole.core import SequentialFitPlan

    x = np.arange(10.0)
    curves = [Curve(str(i), x, np.full_like(x, float(i * 10 + 1))) for i in range(3)]
    models = {curves[0].id: Model(components=[Component.create("constant", initial={"offset": 1})])}
    plan = SequentialFitPlan(
        [curve.id for curve in curves], FitMode.SEQUENTIAL,
        monitor_residuals=False, parameter_change_limit=0.01,
    )
    events = []
    result = Fitter().fit(plan, curves, models, progress=lambda value, text: events.append((value, text)))
    assert result.paused_curve_id == curves[1].id
    assert events[-1][0] == 0.5
    assert all(value < 1 for value, _ in events)
