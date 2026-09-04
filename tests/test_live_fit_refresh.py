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
