"""Exercise custom-formula process workers from the frozen desktop executable."""

from __future__ import annotations

import os

import numpy as np

from curvemole import Component, Curve, Fitter, Model
from curvemole.core import fitting
from curvemole.core.fitting import FitMode, FitPlan, FitSettings
from curvemole.core.functions import builtin_definitions, formula_definition
from curvemole.core.registry import FunctionRegistry
from curvemole.core.uncertainty import UncertaintyAnalyzer


def _marked_fit(curve, model, plan):
    result = fitting._fit_in_process(curve, model, plan)
    result.statistics["packaging_worker_pid"] = os.getpid()
    return result


def run_packaging_smoke() -> None:
    registry = FunctionRegistry()
    registry.extend(builtin_definitions())
    registry.register(formula_definition(
        "packaging_formula", "Packaging formula", "a * exp(-0.5 * ((x - c) / s) ** 2)",
        defaults={"a": 1.0, "c": 0.0, "s": 1.0},
        bounds={"a": (0.01, 10.0), "c": (-3.0, 3.0), "s": (0.1, 2.0)},
    ))
    x = np.linspace(-4.0, 4.0, 51)
    curves = [Curve(f"Packaging {index}", x, 1.5 * np.exp(-0.5 * ((x - index * .1) / .7) ** 2))
              for index in range(2)]
    models = {curve.id: Model(components=[Component.create("packaging_formula", registry=registry)])
              for curve in curves}
    parent = os.getpid()
    pids = []
    # A module-level callable remains importable by PyInstaller's spawned workers.
    original_parallel = fitting._fit_in_process
    fitting._fit_in_process = _marked_fit
    try:
        result = Fitter(registry).fit(
            FitPlan([curve.id for curve in curves], FitMode.INDEPENDENT, FitSettings(workers=2)),
            curves, models,
            on_curve_result=lambda _curve_id, fit: pids.append(fit.statistics["packaging_worker_pid"]),
        )
    finally:
        fitting._fit_in_process = original_parallel
    if not result.success or len(pids) != 2 or parent in pids:
        raise RuntimeError("Frozen custom-formula fitting did not complete in process workers")
    for curve in curves:
        np.testing.assert_allclose(result.curve_outputs[curve.id].fitted, curve.y, rtol=1e-5, atol=1e-7)
    single_plan = FitPlan([curves[0].id])
    baseline = Fitter(registry).fit(single_plan, curves, models)
    resampling = UncertaintyAnalyzer(Fitter(registry)).residual_bootstrap(
        baseline, single_plan, curves, models, replicates=4, workers=2, seed=123,
    )
    if resampling.completed != 4:
        raise RuntimeError("Frozen multicore custom-formula bootstrap failed")
