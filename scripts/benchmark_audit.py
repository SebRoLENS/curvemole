"""Reproducible, synthetic audit measurements; no timing assertions or real projects."""
from __future__ import annotations

import copy
import json
import os
import pickle
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import numpy as np

from curvemole import Component, Curve, Project
from curvemole.core.background_edit import updated_background_history
from curvemole.core.calculator import apply_background_subtraction, apply_scalar
from curvemole.core.fit_records import baseline_for_curve
from curvemole.core.fitting import (
    CancellationToken,
    CurveFitOutput,
    FitMode,
    FitResult,
    FitSettings,
)
from curvemole.core.matrices import BlockDiagonalMatrix
from curvemole.core.models import Model
from curvemole.core.process_pool import bounded_results
from curvemole.core.registry import default_registry


def measure(operation):
    tracemalloc.start()
    started = time.perf_counter()
    operation()
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"seconds": elapsed, "peak_traced_bytes": peak}


def benchmark():
    count, parameters = 200, 4
    blocks = BlockDiagonalMatrix([np.eye(parameters) for _ in range(count)])
    outputs = {str(i): CurveFitOutput(str(i), np.arange(2), *[np.zeros(2) for _ in range(5)], {})
               for i in range(count)}
    paths = [f"{i}.component.p{j}" for i in range(count) for j in range(parameters)]
    result = FitResult(True, FitMode.INDEPENDENT, "benchmark", 1, 1, {}, outputs, {}, [],
                       FitSettings(), paths, covariance=blocks, correlation=blocks)
    def legacy_dense():
        for i in range(count):
            dense = replace(result, covariance=np.asarray(result.covariance),
                            correlation=np.asarray(result.correlation))
            baseline_for_curve(dense, str(i))
    def block_extraction():
        for i in range(count):
            baseline_for_curve(result, str(i))
    metrics = {"baseline_configuration": {"curves": count, "parameters_per_curve": parameters},
               "baseline_legacy_dense": measure(legacy_dense),
               "baseline_block_extraction": measure(block_extraction)}
    x = np.linspace(-5., 5., 10_001)
    curve = Curve("Synthetic", x, np.exp(-x*x) + 2.)
    component = Component.create("constant", initial={"offset": 2.})
    component.is_background = True
    model = Model(components=[component])
    apply_background_subtraction(curve, np.full(len(x), 2.), method="model", description="Benchmark",
                                 parameters={"component_ids": [component.id]})
    for _ in range(50):
        apply_scalar(curve, "y_add", .01)
    metrics["background_history_51_operations"] = measure(lambda: updated_background_history(
        curve, model, component, values={f"{curve.id}.{component.id}.offset": 2.1},
        registry=default_registry()))
    payload = pickle.dumps((curve, model))
    metrics["worker_payload_bytes"] = len(payload)
    metrics["serialize_100_worker_payloads"] = measure(lambda: [pickle.dumps((curve, model)) for _ in range(100)])
    def queue():
        with ThreadPoolExecutor(max_workers=4) as pool:
            for _ in bounded_results(pool, range(2000), lambda executor, i: executor.submit(int, i),
                                     CancellationToken(), Event(), limit=8):
                pass
    metrics["bounded_queue_2000_trivial_jobs_limit_8"] = measure(queue)
    # Local imports keep headless/CLI benchmark preparation independent of Qt startup.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("CURVEMOLE_DISABLE_UPDATE_CHECK", "1")
    from PySide6.QtWidgets import QApplication

    from curvemole.gui.app import CurveMoleMainWindow
    app = QApplication.instance() or QApplication([])
    project = Project("Synthetic rendering benchmark")
    for i in range(10):
        item = copy.deepcopy(curve)
        item.id += f"_{i}"
        project.add_curve(item)
        project.models[item.id] = Model(components=[Component.create("gaussian"),
            Component.create("gaussian", operator="convolve")])
    window = CurveMoleMainWindow(project)
    try:
        window.plot_workspace.display_mode.setCurrentIndex(1)
        window.show()
        app.processEvents()
        metrics["overlay_10_convolved_curves_10001_points_5_refreshes"] = measure(
            lambda: [window.plot_workspace.refresh() for _ in range(5)])
    finally:
        project.dirty = False
        window.close()
        window.deleteLater()
        app.processEvents()
    return metrics


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory(prefix="curvemole-audit-benchmark-") as directory:
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "APPDATA", "LOCALAPPDATA"):
            os.environ[key] = str(Path(directory) / key)
        print(json.dumps(benchmark(), indent=2))
