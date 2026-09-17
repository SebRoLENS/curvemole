from __future__ import annotations

import cosmic_ray_removal as cosmic
import numpy as np
import pytest

from curvemole import Curve, Project
from curvemole.core.extensions import extensions
from curvemole.core.plugins import PluginManager
from curvemole.gui.plugin_host import PluginContext


def smooth_spectrum():
    x = np.linspace(100.0, 1200.0, 1400)
    y = 30 + 0.01 * x + 400 * np.exp(-0.5 * ((x - 620) / 22) ** 2)
    return x, y


def test_single_spectrum_detects_and_repairs_narrow_spikes_without_flattening_band():
    x, clean = smooth_spectrum()
    measured = clean.copy()
    measured[900] += 900
    candidates = cosmic.detect_single(x, measured)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.start <= 900 <= candidate.end
    repaired = cosmic.cleaned_values(measured, candidates)
    assert repaired[900] == pytest.approx(clean[900], rel=2e-3)
    assert repaired[np.argmax(clean)] == measured[np.argmax(clean)]


def test_repeated_spectrum_reference_repairs_cosmic_ray_on_real_peak():
    x, clean = smooth_spectrum()
    target_y = clean.copy()
    peak_index = int(np.argmax(clean))
    target_y[peak_index] += 1000
    target = Curve("target", x, target_y)
    repeats = [target]
    for index, factor in enumerate((0.97, 1.03, 1.01)):
        repeats.append(Curve(f"repeat {index}", x, factor * clean + 2 * index))
    candidates = cosmic.detect_ensemble(target, repeats)
    assert any(c.start <= peak_index <= c.end for c in candidates)
    repaired = cosmic.cleaned_values(target_y, candidates)
    assert repaired[peak_index] == pytest.approx(clean[peak_index], rel=0.03)


def test_each_candidate_can_be_rejected_independently():
    x, clean = smooth_spectrum()
    measured = clean.copy()
    measured[300] += 800
    measured[1000] += 700
    candidates = cosmic.detect_single(x, measured)
    assert len(candidates) == 2
    candidates[1].accepted = False
    repaired = cosmic.cleaned_values(measured, candidates)
    assert repaired[300] != measured[300]
    assert repaired[1000] == measured[1000]


def test_manual_interval_uses_shape_preserving_surroundings():
    x, clean = smooth_spectrum()
    measured = clean.copy()
    measured[500:503] += 500
    replacement = cosmic.interpolate_interval(x, measured, 500, 502)
    assert replacement == pytest.approx(clean[500:503], rel=1e-4)


def test_real_plugin_load_and_unload():
    from pathlib import Path

    manager = PluginManager()
    candidate = manager.discover_local(Path(__file__).parent)[0]
    manager.load(candidate, trust=True)
    try:
        entries = [e for e in extensions.entries.values() if e.owner == cosmic.OWNER]
        assert len(entries) == 1 and entries[0].kind == "panels" and entries[0].auto_show
    finally:
        manager.disable(cosmic.OWNER)
    assert not any(e.owner == cosmic.OWNER for e in extensions.entries.values())


def test_panel_previews_and_commits_only_checked_candidates():
    from copy import deepcopy

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    x, clean = smooth_spectrum()
    measured = clean.copy()
    measured[300] += 800
    measured[1000] += 700
    project = Project()
    curve = Curve("two cosmic rays", x, measured)
    project.add_curve(curve)

    class Services:
        values = None
        metadata = None

        def snapshot(self):
            return PluginContext(deepcopy(project), curve.id, (curve.id,), cosmic.OWNER)

        def apply_y_replacement(self, curve_id, values, **keywords):
            self.values = np.asarray(values)
            self.metadata = keywords["metadata"]
            project.dataset.curve(curve_id).apply_transformation(
                __import__("curvemole.core.data", fromlist=["Transformation"]).Transformation(
                    "replace_y", operand=self.values
                )
            )

    services = Services()
    context = PluginContext(
        deepcopy(project), curve.id, (curve.id,), cosmic.OWNER, services=services
    )
    panel = cosmic.cosmic_ray_panel(context)
    try:
        panel.detect()
        assert panel.table.rowCount() == 2
        panel.candidates[1].accepted = False
        panel.apply()
        assert services.values[300] != measured[300]
        assert services.values[1000] == measured[1000]
        assert len(services.metadata["history"][-1]["intervals"]) == 1
    finally:
        panel.close()
        panel.deleteLater()
        app.processEvents()
