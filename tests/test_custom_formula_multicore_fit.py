from __future__ import annotations

import copy
import os
import time

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Model
from curvemole.core import fitting
from curvemole.core.errors import FitCancelled
from curvemole.core.fitting import CancellationToken, FitMode, FitPlan, FitSettings
from curvemole.core.functions import (
    FunctionDefinition,
    ParameterSpec,
    builtin_definitions,
    formula_definition,
)
from curvemole.core.registry import FunctionRegistry


def _fit_with_process_marker(curve, model, plan):
    """Record actual executing PIDs, retaining enough overlap to observe the pool."""
    result = fitting._fit_in_process(curve, model, plan)
    result.statistics["test_worker_pid"] = os.getpid()
    time.sleep(.05)
    return result


def _formula_problem(count=3, identifier="custom_fit_peak"):
    registry = FunctionRegistry()
    registry.extend(builtin_definitions())
    formula = formula_definition(
        identifier, "Custom fitting peak", "a * exp(-0.5 * ((x - c) / s) ** 2)",
        defaults={"a": 1., "c": 0., "s": 1.},
        bounds={"a": (.01, 10.), "c": (-3., 3.), "s": (.1, 2.)},
        derived_formulas={"FWHM": "2.354820045 * s"},
    )
    formula.custom_metadata["manual_points_default"] = True
    formula.custom_metadata["peak_roles"] = {"center": "c", "width": "s"}
    registry.register(formula, replace=True)
    x = np.linspace(-4., 4., 101)
    curves, models = [], {}
    for index in range(count):
        center = -.6 + 1.2 * index / max(1, count - 1)
        y = (1.5 * np.exp(-.5 * ((x - center) / .7) ** 2) + .12) * 1.1
        y += .003*np.sin(4*x + index)
        curve = Curve(f"scan {index}", x, y, sigma_y=np.full_like(x, .01))
        peak = Component.create(identifier, registry=registry)
        offset = Component.create("constant", initial={"offset": .1})
        scale = Component.create("constant", initial={"offset": 1.1}, operator="multiply")
        scale.parameters["offset"].fixed = True
        models[curve.id] = Model(components=[peak, offset, scale])
        curves.append(curve)
    return registry, curves, models


@pytest.mark.parametrize("identifier", ["custom_fit_peak", "gaussian"])
def test_custom_formula_multicore_matches_serial_fit_and_covariance(monkeypatch, identifier):
    registry, curves, models = _formula_problem(identifier=identifier)
    serial_models = {key: model.clone() for key, model in models.items()}
    serial = Fitter(registry).fit(
        FitPlan([c.id for c in curves], FitMode.INDEPENDENT, FitSettings(workers=1)),
        copy.deepcopy(curves), serial_models,
    )
    pools = []
    original = fitting.ProcessPoolExecutor

    def capture_pool(*args, **kwargs):
        pools.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(fitting, "ProcessPoolExecutor", capture_pool)
    completed = []
    parallel = Fitter(registry).fit(
        FitPlan([c.id for c in curves], FitMode.INDEPENDENT, FitSettings(workers=2)),
        curves, models, on_curve_result=lambda curve_id, result: completed.append((curve_id, result.success)),
    )
    assert len(pools) == 1  # Detect a silent fallback to the serial fitting path.
    assert identifier in pools[0]["initargs"][1]
    assert parallel.success == serial.success is True
    assert set(completed) == {(curve.id, True) for curve in curves}
    assert parallel.free_parameter_paths == serial.free_parameter_paths
    np.testing.assert_allclose(parallel.covariance, serial.covariance, rtol=1e-10, atol=1e-12)
    for path in serial.parameters:
        assert parallel.parameters[path].value == pytest.approx(serial.parameters[path].value, rel=1e-10)
        assert parallel.parameters[path].standard_error == serial.parameters[path].standard_error
    for curve in curves:
        np.testing.assert_array_equal(parallel.curve_outputs[curve.id].fitted, serial.curve_outputs[curve.id].fitted)
        for path, parameter in models[curve.id].parameter_map(curve.id).items():
            assert parameter.value == parallel.parameters[path].value


def test_many_custom_formula_spectra_execute_in_distinct_processes(monkeypatch):
    registry, curves, models = _formula_problem(count=30)
    # Use a top-level picklable test wrapper to observe the child processes.
    original_worker = fitting._fit_in_process
    monkeypatch.setattr(fitting, "_fit_in_process", _fit_with_process_marker)
    process_ids = set()
    try:
        result = Fitter(registry).fit(
            FitPlan([curve.id for curve in curves], FitMode.INDEPENDENT, FitSettings(workers=12)),
            curves, models,
            on_curve_result=lambda _curve_id, fit: process_ids.add(fit.statistics["test_worker_pid"]),
        )
    finally:
        monkeypatch.setattr(fitting, "_fit_in_process", original_worker)
    assert result.success
    assert len(result.curve_outputs) == 30
    assert os.getpid() not in process_ids
    if (os.cpu_count() or 1) > 1:
        assert len(process_ids) > 1


def test_cancelling_custom_formula_multicore_fit_stops_workers(monkeypatch):
    registry, curves, models = _formula_problem(count=8)
    token = CancellationToken()
    with pytest.raises(FitCancelled):
        Fitter(registry).fit(
            FitPlan([c.id for c in curves], FitMode.INDEPENDENT, FitSettings(workers=2)),
            curves, models, cancellation=token,
            on_curve_result=lambda *_: token.cancel(),
        )


def test_executable_callback_keeps_existing_serial_fallback(monkeypatch):
    registry = FunctionRegistry()
    registry.register(FunctionDefinition(
        "executable", "Executable", "generic", lambda x, p, m: p["slope"] * x,
        parameter_specs=(ParameterSpec("slope", 1.),),
    ))
    curves = [Curve(str(i), [0., 1., 2.], [0., 2., 4.]) for i in range(2)]
    models = {c.id: Model(components=[Component.create("executable", registry=registry)]) for c in curves}

    def unexpected_pool(*args, **kwargs):
        pytest.fail("Executable callback must retain its registry in the current process")

    monkeypatch.setattr(fitting, "ProcessPoolExecutor", unexpected_pool)
    result = Fitter(registry).fit(
        FitPlan([c.id for c in curves], FitMode.INDEPENDENT, FitSettings(workers=2)), curves, models,
    )
    assert result.success
    assert all(m.components[0].parameters["slope"].value == pytest.approx(2.) for m in models.values())


def test_custom_formula_independent_fit_from_gui(monkeypatch):
    pytest.importorskip("PySide6", exc_type=ImportError)
    pytest.importorskip("pyqtgraph", exc_type=ImportError)
    from PySide6.QtWidgets import QApplication

    from curvemole import Project
    from curvemole.core.data import CurveState
    from curvemole.gui.app import CurveMoleMainWindow

    app = QApplication.instance() or QApplication([])
    registry, curves, models = _formula_problem()
    project = Project("formula multicore GUI")
    definition = registry.get("custom_fit_peak")
    project.custom_functions.append({
        "identifier": definition.identifier, "display_name": definition.display_name,
        "kind": definition.kind, **definition.custom_metadata,
    })
    window = CurveMoleMainWindow(project)
    for curve in curves:
        project.add_curve(curve)
        project.models[curve.id] = models[curve.id]
    window._set_active_curve(curves[0].id)
    window.refresh_all()
    pools = []
    original = fitting.ProcessPoolExecutor

    def capture_pool(*args, **kwargs):
        pools.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(fitting, "ProcessPoolExecutor", capture_pool)
    try:
        window._run_fit(FitPlan([c.id for c in curves], FitMode.INDEPENDENT, FitSettings(workers=2)))
        deadline = time.monotonic() + 20
        while window._thread is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.001)
        assert window._thread is None
        assert len(pools) == 1
        assert pools[0]["max_workers"] == min(2, os.cpu_count() or 1)
        assert all(curve.state == CurveState.FITTED for curve in project.curves)
        assert set(project.results["fit_by_curve"]) == {c.id for c in curves}
        for curve in curves:
            baseline, plan = window._fit_for_uncertainty(curve.id)
            assert baseline.success
            assert plan.curve_ids == [curve.id]
            peak = project.model_for(curve.id).components[0]
            assert peak.parameters["s"].value == pytest.approx(.7, abs=.01)
    finally:
        project.dirty = False
        window.close()
        app.processEvents()
