from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QColorDialog

from curvemole import Component, Curve, Project
from curvemole.core.data import CurveState, Series
from curvemole.core.fitting import FitSettings, Fitter
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.colours import (
    MODEL_SUM_COLOUR,
    SERIES_PALETTES,
    spectrum_colour_allowed,
)
from curvemole.gui.main_window import PALETTE, MainWindow


def _gaussian_project() -> tuple[Project, Curve, Component]:
    x = np.linspace(-5.0, 5.0, 301)
    sigma = 0.75
    y = 2.4 * np.exp(-0.5 * ((x - 0.65) / sigma) ** 2) / (sigma * np.sqrt(2 * np.pi))
    curve = Curve("spectrum", x, y)
    project = Project("fit display")
    project.add_curve(curve)
    component = Component.create(
        "gaussian", initial={"area": 1.0, "center": -1.0, "sigma": 1.5}
    )
    project.model_for(curve.id).add(component)
    project.dirty = False
    return project, curve, component


def test_fit_finished_commits_returned_estimates_to_displayed_model() -> None:
    app = QApplication.instance() or QApplication([])
    project, curve, component = _gaussian_project()
    window = MainWindow(project)
    model = project.model_for(curve.id)
    result = Fitter(window.registry).fit_single(
        curve, model, FitSettings(max_nfev=4000)
    )
    assert result.success

    # Simulate the GUI holding the pre-fit values when the worker result arrives.
    component.parameters["area"].value = 1.0
    component.parameters["center"].value = -1.0
    component.parameters["sigma"].value = 1.5
    window._fit_finished(result)

    for path, estimate in result.parameters.items():
        assert project.parameter_map()[path].value == pytest.approx(estimate.value)
    rendered = model.evaluate(
        curve.x,
        curve_id=curve.id,
        values=project.resolved_parameter_values(),
        registry=window.registry,
    )
    output = result.curve_outputs[curve.id]
    np.testing.assert_allclose(rendered[output.indices], output.fitted, rtol=1e-9, atol=1e-11)
    assert curve.state == CurveState.FITTED
    project.dirty = False
    window.close()
    app.processEvents()


def test_fit_refresh_preserves_current_plot_view() -> None:
    app = QApplication.instance() or QApplication([])
    project, curve, _ = _gaussian_project()
    window = CurveMoleMainWindow(project)
    app.processEvents()

    window.plot_workspace.view_box.setRange(
        xRange=[-0.4, 1.4],
        yRange=[0.15, 1.15],
        padding=0,
    )
    before = window.plot_workspace.view_box.viewRange()

    model = project.model_for(curve.id)
    result = Fitter(window.registry).fit_single(
        curve, model, FitSettings(max_nfev=4000)
    )
    assert result.success
    window._fit_finished(result)
    app.processEvents()
    after = window.plot_workspace.view_box.viewRange()

    assert after[0] == pytest.approx(before[0])
    assert after[1] == pytest.approx(before[1])
    project.dirty = False
    window.close()
    app.processEvents()


def test_regular_refresh_preserves_current_plot_view() -> None:
    app = QApplication.instance() or QApplication([])
    project, _, _ = _gaussian_project()
    window = CurveMoleMainWindow(project)
    app.processEvents()

    window.plot_workspace.view_box.setRange(
        xRange=[-1.2, 0.8],
        yRange=[0.05, 0.9],
        padding=0,
    )
    before = window.plot_workspace.view_box.viewRange()
    window.refresh_all()
    app.processEvents()
    after = window.plot_workspace.view_box.viewRange()

    assert after[0] == pytest.approx(before[0])
    assert after[1] == pytest.approx(before[1])
    project.dirty = False
    window.close()
    app.processEvents()


def test_model_sum_red_is_reserved_from_all_builtin_spectrum_palettes() -> None:
    assert MODEL_SUM_COLOUR.upper() == "#D62728"
    assert not spectrum_colour_allowed(MODEL_SUM_COLOUR)
    assert all(spectrum_colour_allowed(colour) for colours in SERIES_PALETTES.values() for colour in colours)
    assert all(colour.upper() != MODEL_SUM_COLOUR.upper() for colour in PALETTE)


def test_series_palette_changes_colours_without_invalidating_fits() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("palette")
    series = Series("series")
    for index in range(4):
        curve = Curve(f"curve {index}", [0.0, 1.0], [float(index), float(index + 1)])
        curve.state = CurveState.FITTED
        series.add(curve)
    project.add_series(series)
    project.dirty = False
    window = MainWindow(project)
    window.apply_series_palette(series.id, "Ocean")
    expected = list(SERIES_PALETTES["Ocean"][:4])
    assert [curve.colour for curve in series.curves] == expected
    assert all(curve.state == CurveState.FITTED for curve in series.curves)
    assert series.metadata["palette"] == "Ocean"
    window.undo_stack.undo()
    assert all(curve.state == CurveState.FITTED for curve in series.curves)
    project.dirty = False
    window.close()
    app.processEvents()


def test_individual_spectrum_colour_picker_changes_non_red_colour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    project, curve, _ = _gaussian_project()
    curve.state = CurveState.FITTED
    project.dirty = False
    window = MainWindow(project)
    monkeypatch.setattr(
        QColorDialog,
        "getColor",
        lambda *args, **kwargs: QColor("#3455AA"),
    )
    window.choose_curve_colour(curve.id)
    assert curve.colour == "#3455AA"
    assert curve.state == CurveState.FITTED
    project.dirty = False
    window.close()
    app.processEvents()


def test_existing_red_spectrum_is_migrated_on_open() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("old red")
    curve = Curve("legacy", [0.0, 1.0], [0.0, 1.0])
    curve.colour = "#FF0000"
    project.add_curve(curve)
    project.dirty = False
    window = MainWindow(project)
    assert spectrum_colour_allowed(curve.colour)
    assert curve.colour.upper() != MODEL_SUM_COLOUR.upper()
    project.dirty = False
    window.close()
    app.processEvents()
