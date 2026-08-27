#!/usr/bin/env python3
"""Generate deterministic README screenshots from a real CurveMole fit."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "screenshots"


def _gaussian(x: np.ndarray, area: float, center: float, sigma: float) -> np.ndarray:
    return area * np.exp(-0.5 * ((x - center) / sigma) ** 2) / (sigma * np.sqrt(2 * np.pi))


def _lorentzian(x: np.ndarray, area: float, center: float, gamma: float) -> np.ndarray:
    return area * gamma / (np.pi * ((x - center) ** 2 + gamma**2))


def build_example_project():
    """Create and fit three deterministic Raman-like spectra."""
    from curvemole import Component, Curve, Fitter, Project
    from curvemole.core.data import CurveState

    project = Project("Raman peak-fitting example")
    x = np.linspace(350.0, 1850.0, 1201)
    rng = np.random.default_rng(20260827)
    colours = ("#0072B2", "#D55E00", "#009E73")
    selected_peak_id = ""

    for index, (shift, scale) in enumerate(((-10.0, 0.88), (0.0, 1.0), (13.0, 1.12)), start=1):
        background = 0.13 + 0.00010 * x
        signal = (
            background
            + _gaussian(x, 118.0 * scale, 825.0 + shift, 43.0)
            + _lorentzian(x, 155.0 * scale, 1325.0 + 0.5 * shift, 54.0)
        )
        sigma_y = np.full_like(x, 0.012)
        curve = Curve(
            f"Raman spectrum {index}",
            x,
            signal + rng.normal(0.0, sigma_y),
            sigma_y=sigma_y,
            x_label="Raman shift",
            y_label="Intensity",
            x_unit="cm⁻¹",
            y_unit="a.u.",
            source="Deterministic CurveMole screenshot example",
            colour=colours[index - 1],
        )
        project.add_curve(curve)
        model = project.model_for(curve.id)

        baseline = Component.create(
            "linear",
            name="Linear background",
            initial={"intercept": 0.12, "slope": 0.00012},
        )
        baseline.is_background = True
        gaussian = Component.create(
            "gaussian",
            name="Gaussian peak",
            initial={"area": 105.0 * scale, "center": 810.0 + shift, "sigma": 50.0},
        )
        lorentzian = Component.create(
            "lorentzian",
            name="Lorentzian peak",
            initial={"area": 140.0 * scale, "center": 1310.0, "gamma": 62.0},
        )
        model.add(baseline)
        model.add(gaussian)
        model.add(lorentzian)

        result = Fitter().fit_single(curve, model)
        if not result.success:
            raise RuntimeError(f"Screenshot example fit failed for {curve.name}: {result.message}")
        for path, estimate in result.parameters.items():
            parameter = project.parameter_map()[path]
            parameter.standard_error = estimate.standard_error
            parameter.ci_low = estimate.ci_low
            parameter.ci_high = estimate.ci_high
        curve.state = CurveState.FITTED
        project.results[f"fit:{curve.id}"] = result
        if index == 1:
            project.results["last_fit"] = result
            selected_peak_id = gaussian.id

    project.dirty = False
    return project, selected_peak_id


def _settle(app, rounds: int = 6) -> None:
    for _ in range(rounds):
        app.processEvents()


def _save_window(window, app, filename: str) -> None:
    window.plot_workspace.auto_range()
    _settle(app)
    destination = OUTPUT_DIR / filename
    if not window.grab().save(str(destination), "PNG"):
        raise RuntimeError(f"Could not save screenshot: {destination}")


def render_screenshots() -> None:
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from curvemole.gui.main_window import MainWindow

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication.instance() or QApplication(["curvemole-screenshots"])
    app.setStyle("Fusion")
    app.setFont(QFont("DejaVu Sans", 10))
    QCoreApplication.setOrganizationName("CurveMole screenshots")
    QCoreApplication.setApplicationName("CurveMole screenshots")

    project, selected_peak_id = build_example_project()
    window = MainWindow(project)
    window.autosave_timer.stop()
    window.update_check_timer.stop()
    window.reset_layout()
    window.apply_theme("light")
    window.resize(1440, 900)
    window.selected_component_id = selected_peak_id
    window.refresh_all()
    window.plot_workspace.plot.getAxis("bottom").enableAutoSIPrefix(False)
    window.plot_workspace.residual_plot.getAxis("bottom").enableAutoSIPrefix(False)
    window.plot_workspace.residual_plot.getAxis("left").enableAutoSIPrefix(False)
    window.show()
    window.statusBar().showMessage("Fit completed · Gaussian + Lorentzian peaks with linear background")
    _settle(app)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _save_window(window, app, "fit-overview.png")

    window.selected_component_id = None
    window.curve_tree.select_all_curves()
    window.plot_workspace.display_mode.setCurrentIndex(1)
    window.plot_workspace.set_component_labels_visible(False)
    window.statusBar().showMessage("Three fitted spectra selected · Overlay comparison")
    _settle(app)
    _save_window(window, app, "multi-spectrum-overlay.png")

    project.dirty = False
    window.close()
    _settle(app, 2)


def main() -> int:
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
    with tempfile.TemporaryDirectory(prefix="curvemole-screenshots-") as settings_dir:
        os.environ["XDG_CONFIG_HOME"] = settings_dir
        os.environ.setdefault("MPLCONFIGDIR", settings_dir)
        render_screenshots()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
