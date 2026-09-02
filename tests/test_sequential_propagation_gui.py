from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.core.fitting import FitMode, FitSettings
from curvemole.gui.dialogs import FitPlanDialog


def test_sequential_dialog_exposes_propagation_and_ignore_controls() -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings("CurveMole", "CurveMole")
    for name in (
        "bounds",
        "fixed",
        "links",
        "background",
        "enabled",
        "composition",
    ):
        settings.setValue(f"sequential/propagate_{name}", True)

    project = Project("sequential-options")
    x = np.linspace(-2.0, 2.0, 21)
    first = Curve("source", x, np.exp(-x**2))
    second = Curve("target", x, np.exp(-(x - 0.1) ** 2))
    project.add_curve(first)
    project.add_curve(second)
    peak = Component.create("gaussian")
    background = Component.create("linear")
    background.is_background = True
    project.model_for(first.id).add(peak)
    project.model_for(first.id).add(background)

    dialog = FitPlanDialog(project, {first.id, second.id}, FitSettings())
    dialog.mode.setCurrentIndex(dialog.mode.findData(FitMode.SEQUENTIAL))
    dialog.sequential_source.setCurrentIndex(dialog.sequential_source.findData(first.id))

    assert dialog.sequential_propagate_bounds.isChecked()
    assert dialog.sequential_propagate_fixed.isChecked()
    assert dialog.sequential_propagate_links.isChecked()
    assert dialog.sequential_propagate_background.isChecked()
    assert dialog.sequential_propagate_enabled.isChecked()
    assert dialog.sequential_propagate_composition.isChecked()
    assert dialog.sequential_ignored_functions.count() == 2

    dialog.sequential_ignored_functions.item(0).setCheckState(Qt.CheckState.Checked)
    plan = dialog.plan()
    assert plan.ignored_component_ids == (peak.id,)

    dialog.close()
    app.processEvents()
