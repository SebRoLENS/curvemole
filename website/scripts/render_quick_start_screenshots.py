#!/usr/bin/env python3
"""Replay the website tutorial in the actual stable CurveMole GUI.

No interface is drawn or retouched here: every PNG is a QWidget.grab() from
CurveMole. The same GUI commands import, mask, initialise, subtract, fit, analyse
and export the data that accompany the page. Publication verifies the app source
SHA and version; --app-source permits a read-only release checkout for previews.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def render(output: Path, app_source: Path | None = None) -> dict:
    if app_source is not None:
        sys.path.insert(0, str(app_source.resolve() / "src"))
    import numpy as np
    import scipy
    from PySide6 import __version__ as qt_version
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QFileDialog, QMessageBox
    from quick_start_data import BANDS, BASELINE_CAVEAT, MASK_INTERVAL, make_dataset, write_dataset
    from quick_start_plugin import capture_plugin_steps, write_plugin_bundle

    import curvemole
    from curvemole import Curve, Project
    from curvemole.core.serialization import load_project, save_project
    from curvemole.core.spectrum_export import SpectrumExportOptions, export_spectra
    from curvemole.gui.app import CurveMoleMainWindow, _configure_gui_defaults
    from curvemole.gui.dialogs import (
        BackgroundComponentsDialog,
        ExportBundleDialog,
        ImportMappingDialog,
    )
    from curvemole.gui.spectrum_export_ui import SpectrumExportDialog
    from curvemole.version import __version__

    source_root = Path(curvemole.__file__).resolve().parents[2]
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source_root, text=True,
    ).strip()
    expected_sha = os.environ.get("CURVEMOLE_SCREENSHOT_SOURCE_SHA")
    if expected_sha and source_sha != expected_sha:
        raise RuntimeError("The imported app does not match the verified stable source")
    if not re.fullmatch(r"\d+\.\d+\.\d+", __version__):
        raise RuntimeError("The tutorial requires a final stable CurveMole version")

    output = output.resolve()
    images = output / "assets/quick-start"
    downloads = output / "quick-start-data"
    images.mkdir(parents=True, exist_ok=True)
    downloads.mkdir(parents=True, exist_ok=True)
    paths = write_dataset(downloads)
    data = make_dataset()
    _configure_gui_defaults()
    app = QApplication.instance() or QApplication(["curvemole-quick-start-captures"])
    app.setStyle("Fusion")
    app.setFont(QFont("DejaVu Sans", 10))
    QCoreApplication.setOrganizationName("CurveMole website screenshots")
    QCoreApplication.setApplicationName("Reproducible Raman quick start")
    captured: list[str] = []

    def settle(rounds=20):
        for _ in range(rounds):
            app.processEvents()

    def capture(widget, filename):
        settle()
        if not widget.isVisible():
            raise RuntimeError(f"Cannot capture a hidden tutorial widget: {filename}")
        if not widget.grab().save(str(images / filename), "PNG"):
            raise RuntimeError(f"Cannot capture {filename}")
        captured.append(filename)
        print(filename, flush=True)

    def fail_gui(title, error):
        raise RuntimeError(f"{title}: {error}") from error

    def new_window(project):
        window = CurveMoleMainWindow(project)
        window._show_error = fail_gui
        window.autosave_timer.stop()
        window.reset_layout()
        window.apply_theme("dark")
        window.resize(1600, 1000)
        window.model_panel.setMinimumWidth(440)
        window.show()
        settle()
        return window

    @contextmanager
    def shown_dialog(dialog_class, filename, configure=None):
        def execute(dialog):
            if configure is not None:
                configure(dialog)
            dialog.show()
            capture(dialog, filename)
            dialog.accept()
            return QDialog.DialogCode.Accepted
        with patch.object(dialog_class, "exec", execute):
            yield

    def wait_for_task(window, timeout=150):
        start = time.monotonic()
        while window._thread is not None:
            settle(3)
            if time.monotonic() - start > timeout:
                raise RuntimeError("Tutorial GUI calculation timed out")
            time.sleep(0.005)
        settle()

    def view(window, status=None):
        window.refresh_all()
        window.plot_workspace.auto_range()
        window.plot_workspace.plot.getAxis("bottom").enableAutoSIPrefix(False)
        window.plot_workspace.plot.getAxis("left").enableAutoSIPrefix(False)
        window.plot_workspace.residual_plot.getAxis("bottom").enableAutoSIPrefix(False)
        if status:
            window.statusBar().showMessage(status)
        settle()

    window = new_window(Project("Raman quick start"))

    def configure_import(dialog):
        dialog.resize(1060, 980)
        dialog.series_name.setText("Raman practice")
        dialog.x_column.setCurrentText("raman_shift_cm-1")
        for i in range(dialog.y_columns.count()):
            item = dialog.y_columns.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.text() == "intensity"
                               else Qt.CheckState.Unchecked)
        dialog.uncertainty_kind.setCurrentText("sigma_y")
        dialog.uncertainty_column.setCurrentIndex(dialog.uncertainty_column.findData("sigma_y"))
        assert dialog.mapping().sigma_y == "sigma_y"
        # The real dialog normally schedules this on its 120 ms debounce timer.
        # Run the same method before grabbing so the import plot is never blank.
        dialog.spectrum_preview.refresh()
        if not dialog.spectrum_preview.graph.listDataItems():
            raise RuntimeError("The real import dialog did not render the input spectrum")

    with shown_dialog(ImportMappingDialog, "01-import-dialog.png", configure_import):
        window.import_data([str(paths["spectrum"])])
    if len(window.project.curves) != 1:
        raise RuntimeError("The tutorial import must create exactly one curve")
    curve = window.project.curves[0]
    curve.name = "Raman spectrum"
    curve.x_label, curve.x_unit = "Raman shift / cm⁻¹", ""
    curve.y_label, curve.y_unit = "Intensity", "a.u."
    curve.source = "raman-spectrum.csv"
    original = curve.original_y.copy()
    view(window)
    capture(window, "02-imported-spectrum.png")
    save_project(window.project, downloads / "01-imported.fitproj", portable=True,
                 update_project_path=False)

    # This is the same range-mask operation emitted by the graphical Mask tool.
    window.plot_workspace.mask_action.setChecked(True)
    window.mask_range(*MASK_INTERVAL)
    if int(curve.effective_mask.sum()) != 7:
        raise RuntimeError("The documented mask no longer excludes seven points")
    view(window)
    window.plot_workspace.plot.setXRange(840, 960, padding=0)
    window.plot_workspace.plot.setYRange(55, 280, padding=0)
    capture(window, "03-mask-spectrum.png")
    window.plot_workspace.mask_action.setChecked(False)
    view(window)

    selector = window.quick_function_selector
    selector.setCurrentIndex(selector.findData("polynomial"))
    window.quick_add_manual_points.setChecked(True)
    window.quick_add_background.setChecked(True)
    window.quick_peak()
    if not window._pending_manual_points:
        raise RuntimeError("Polynomial point placement did not start")
    for x, y in data["anchors"]:
        window.plot_workspace._add_spline_point(float(x), float(y))
    capture(window, "04-background-points.png")
    window.plot_workspace.finish_placement()
    model = window.project.model_for(curve.id)
    background = model.components[0]
    if background.function_id != "polynomial" or len(background.parameters) != 3:
        raise RuntimeError("Three point selections must produce a quadratic background")
    if not all(p.fixed for p in background.parameters.values()):
        raise RuntimeError("Point-estimated background must remain fixed")
    estimated_background = model.background(
        curve.x, curve_id=curve.id, values=window.project.resolved_parameter_values(),
        registry=window.registry,
    )
    np.testing.assert_allclose(estimated_background, data["estimated_background"], atol=1e-8)
    view(window)
    capture(window, "05-background-model.png")
    with shown_dialog(BackgroundComponentsDialog, "06-subtract-dialog.png"):
        window.subtract_background()
    assert not background.enabled and background.is_background
    np.testing.assert_allclose(curve.y, original - estimated_background)
    np.testing.assert_array_equal(curve.original_y, original)
    view(window)
    capture(window, "07-background-subtracted.png")
    save_project(window.project, downloads / "02-background-subtracted.fitproj", portable=True,
                 update_project_path=False)

    selector.setCurrentIndex(selector.findData("gaussian"))
    window.quick_add_manual_points.setChecked(True)
    window.quick_add_background.setChecked(False)
    for band in BANDS:
        if window._pending_component is None:
            window.quick_peak()
        window.plot_workspace._finish_peak_placement(
            float(band["center"]), 0.0, 2.354820045 * float(band["sigma"]),
        )
        model = window.project.model_for(curve.id)
        component = model.components[-1]
        with patch("PySide6.QtWidgets.QInputDialog.getText", return_value=(band["name"], True)):
            window.rename_function(curve.id, component.id)
        # This ordinary parameter edit keeps the three simulated Raman bands positive.
        window.change_parameter(component.id, "area", "minimum", 0.0)
    window.plot_workspace.finish_placement()
    model = window.project.model_for(curve.id)
    if len(model.components) != 4:
        raise RuntimeError("The tutorial needs one disabled background and three Gaussian bands")
    window._set_component_on_curve(curve.id, model.components[2].id)
    view(window)
    capture(window, "08-peak-model.png")
    save_project(window.project, downloads / "03-initial-model.fitproj", portable=True,
                 update_project_path=False)
    window.fit_settings.use_data_errors = True
    window.quick_fit()
    wait_for_task(window)
    baseline = window._last_fit_result()
    model = window.project.model_for(curve.id)
    background = model.components[0]
    if baseline is None or not baseline.success:
        attempt = window.project.results.get("last_attempt")
        raise RuntimeError(f"The tutorial fit failed: {getattr(attempt, 'message', None)}; "
                           f"results={list(window.project.results)}; log={window.log.toPlainText()}")
    assert baseline.statistics["N"] == 794
    assert baseline.statistics["degrees_of_freedom"] == 785
    view(window)
    capture(window, "10-first-fit.png")

    window._show_uncertainty_analysis()
    dock, panel = window.uncertainty_dock, window.uncertainty_panel
    dock.setFloating(True)
    dock.resize(1140, 1040)
    panel.method.setCurrentIndex(panel.method.findData("covariance"))
    window.start_uncertainty("covariance", 200, None)
    dock.show()
    panel.scroll.verticalScrollBar().setValue(panel.scroll.verticalScrollBar().maximum())
    capture(dock, "11-uncertainty-covariance.png")
    area_path = model.parameter_path(curve.id, model.components[2].id, "area")
    result_table = panel.results.table
    row = next(i for i in range(result_table.rowCount())
               if result_table.item(i, 0) is not None
               and result_table.item(i, 0).data(Qt.ItemDataRole.UserRole) == area_path)
    panel.method.setCurrentIndex(panel.method.findData("monte_carlo"))
    panel.replica_mode.setCurrentIndex(panel.replica_mode.findData("fixed"))
    panel.replicates.setValue(200)
    panel.workers.setValue(1)
    panel.confidence.setValue(95)
    panel.scroll.verticalScrollBar().setValue(0)
    capture(dock, "13-monte-carlo-setup.png")
    window.start_uncertainty("monte_carlo", 200, None, workers=1)
    wait_for_task(window)
    mc = window.project.results.get("uncertainty_by_curve", {}).get(curve.id, {}).get(
        "parametric_monte_carlo")
    if mc is None or mc.completed != 200:
        raise RuntimeError("All 200 tutorial Monte Carlo replicas must complete")
    window._select_uncertainty_display("parametric_monte_carlo")
    panel.scroll.verticalScrollBar().setValue(panel.scroll.verticalScrollBar().maximum())
    capture(dock, "14-monte-carlo-results.png")
    row = next(i for i in range(result_table.rowCount())
               if result_table.item(i, 0) is not None
               and result_table.item(i, 0).data(Qt.ItemDataRole.UserRole) == area_path)
    if result_table.item(row, 4).text() != "Attention":
        raise RuntimeError("The actual Monte Carlo table must flag the overlapping area")
    with shown_dialog(QMessageBox, "12-overlap-correlation.png"):
        panel.results._cell_clicked(row, 4)
    dock.hide()

    export_directory = downloads / "exported-spectra"
    def configure_spectra(dialog):
        dialog.directory.setText(str(export_directory))
        dialog.subtract_background.setChecked(False)
        dialog.unmasked_only.setChecked(False)
        dialog.include_background.setChecked(False)
    with shown_dialog(SpectrumExportDialog, "15-export-curves.png", configure_spectra):
        window.export_spectra_data()
    numeric = list(export_directory.glob("*"))
    if len(numeric) != 1:
        raise RuntimeError("Expected one spectrum export")
    shutil.copyfile(numeric[0], downloads / "fit-curves.csv")
    unmasked = export_spectra(window.project, downloads / "unmasked-spectra", [curve.id],
                             options=SpectrumExportOptions(unmasked_only=True,
                                                           include_background=False))
    shutil.copyfile(unmasked[0], downloads / "fit-curves-unmasked.csv")

    def configure_parameters(dialog):
        dialog.setDirectory(str(downloads))
        dialog.selectFile("fit-parameters.csv")
        covariance = dialog.findChild(QCheckBox, "export_covariance")
        if covariance is None:
            raise RuntimeError("The covariance export option is missing")
        covariance.setChecked(True)
    with shown_dialog(QFileDialog, "16-export-parameters.png", configure_parameters):
        window.export_parameters()

    def configure_bundle(dialog):
        dialog.directory.setText(str(downloads))
        dialog.folder_name.setText("analysis-bundle")
    with shown_dialog(ExportBundleDialog, "17-export-bundle.png", configure_bundle):
        window.export_analysis()
    window.project.notebook.notes = (
        "Synthetic three-band Raman tutorial. Mask 894–906 cm^-1; quadratic background "
        "from observed anchors at260/850/1720 cm^-1; Gaussian peaks and absolute sigma_y=2. "
        + BASELINE_CAVEAT
    )
    save_project(window.project, downloads / "completed-analysis.fitproj", portable=True,
                 update_project_path=False)
    restored = load_project(downloads / "completed-analysis.fitproj")
    np.testing.assert_array_equal(restored.curves[0].effective_mask, curve.effective_mask)
    np.testing.assert_allclose(restored.curves[0].y, curve.y)
    assert "parametric_monte_carlo" in restored.results["uncertainty_reports_by_curve"][curve.id]

    a, b = model.components[2:4]
    indices = [baseline.free_parameter_paths.index(model.parameter_path(curve.id, c.id, "area"))
               for c in (a, b)]
    rho = float(np.asarray(baseline.correlation)[indices[0], indices[1]])
    if not -1 < rho < -0.95:
        raise RuntimeError("The overlap correlation demonstration is no longer valid")
    fit_report = {
        "statistics": baseline.statistics, "overlap_area_correlation": rho,
        "background_coefficients": {k: p.value for k, p in background.parameters.items()},
        "bands": [{"name": c.name, **{k: {"value": p.value, "standard_error": p.standard_error,
                                          "ci_low": p.ci_low, "ci_high": p.ci_high}
                                     for k, p in c.parameters.items()}} for c in model.components[1:]],
        "monte_carlo": {"replicates": mc.completed, "seed": mc.seed, "confidence_level": .95,
                        "overlap_area_correlation": float(np.corrcoef(
                            np.asarray(mc.samples)[:, indices[0]],
                            np.asarray(mc.samples)[:, indices[1]])[0, 1])},
        "monte_carlo_overlap_area_correlation": float(np.corrcoef(
            np.asarray(mc.samples)[:, indices[0]], np.asarray(mc.samples)[:, indices[1]])[0, 1]),
        "uncertainty_caveat": BASELINE_CAVEAT,
    }
    np.savetxt(downloads / "background-reference.csv", np.column_stack((
        curve.x, original, estimated_background, curve.y, curve.effective_mask.astype(int),
    )), delimiter=",", comments="", header="x,original_y,chosen_background,corrected_y,masked",
        fmt="%.12g")
    window.project.dirty = False
    window.close()
    settle()

    plugin_project = Project("Cosmic-ray removal exercise")
    plugin_curve = Curve("Raman spectrum — original with cosmic ray", data["x"], data["y"],
                         sigma_y=data["sigma_y"], x_label="Raman shift / cm⁻¹", x_unit="",
                         y_label="Intensity", y_unit="a.u.", source="raman-with-cosmic.csv")
    plugin_project.add_curve(plugin_curve)
    plugin_window = new_window(plugin_project)
    view(plugin_window)
    plugin_report = capture_plugin_steps(plugin_window, app, images, capture,
                                         source_root=source_root, spike_x=900.0)
    plugin_bundle = write_plugin_bundle(downloads / "cosmic_ray_removal.zip", source_root=source_root)
    plugin_window.project.dirty = False
    plugin_window.close()
    settle()

    # Small independent replotting script: it uses exported columns, not app internals.
    (downloads / "replot.py").write_text('''"""Run beside fit-curves.csv: python replot.py. Requires pandas and matplotlib."""
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
root = Path(__file__).resolve().parent
data = pd.read_csv(root / "fit-curves.csv")
x, y = data.iloc[:, 0], data.iloc[:, 1]
mask_record = pd.read_csv(root / "background-reference.csv").set_index("x")["masked"]
excluded = x.map(mask_record).fillna(0).astype(bool)
fig, (ax, residual) = plt.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3, 1]})
ax.plot(x[~excluded], y[~excluded], ".", ms=2, color="0.45", label="Data after background subtraction")
ax.plot(x[excluded], y[excluded], "x", ms=4, color="0.7", label="Masked / excluded from fit")
for name in data.columns:
    if name.startswith("Component_"):
        ax.plot(x, data[name], lw=1, label=name.replace("Component_", ""))
ax.plot(x, data["Total_fit"], color="black", lw=1.4, label="Total fit")
residual.plot(x[~excluded], data.loc[~excluded, "Residual_data_minus_fit"], ".", ms=2)
residual.axhline(0, color="0.5", lw=.7)
residual.set(xlabel="Raman shift / cm$^{-1}$", ylabel="Residual")
ax.set(ylabel="Intensity / a.u.")
ax.legend(fontsize=7)
fig.tight_layout()
fig.savefig(root / "replotted-fit.png", dpi=160)
print(root / "replotted-fit.png")
''', encoding="utf-8")
    manifest = {
        "version": __version__, "source_sha": source_sha, "theme": "dark", "synthetic": True,
        "dataset_sha256": hashlib.sha256(paths["spectrum"].read_bytes()).hexdigest(),
        "screenshots": captured, "fit": fit_report, "plugin": plugin_report,
        "plugin_bundle": plugin_bundle,
        "environment": {"python": sys.version.split()[0], "numpy": np.__version__,
                        "scipy": scipy.__version__, "PySide6": qt_version},
    }
    paths["reference"].write_text(json.dumps({**data["metadata"], "capture": manifest},
                                           indent=2) + "\n", encoding="utf-8")
    with zipfile.ZipFile(downloads / "practice-pack.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(downloads.rglob("*")):
            if path.is_file() and path.name != "practice-pack.zip":
                archive.write(path, path.relative_to(downloads))
    (images / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Captured {len(captured)} real screenshots with CurveMole {__version__}; rho={rho:.6f}",
          flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "website/dist")
    parser.add_argument("--app-source", type=Path, help="Read-only stable source checkout for previews")
    args = parser.parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    os.environ["CURVEMOLE_DISABLE_UPDATE_CHECK"] = "1"
    with tempfile.TemporaryDirectory(prefix="curvemole-quick-start-") as temp:
        for variable in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "MPLCONFIGDIR"):
            os.environ[variable] = temp
        # Always replay into fresh staging, so exports never ask to overwrite a
        # previous run and a failed capture cannot leave a half-refreshed set.
        staged = Path(temp) / "site"
        render(staged, args.app_source)
        for relative in (Path("assets/quick-start"), Path("quick-start-data")):
            target = args.output.resolve() / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(staged / relative, target, dirs_exist_ok=True)


if __name__ == "__main__":
    main()
