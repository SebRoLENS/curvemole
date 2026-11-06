"""Capture the official cosmic-ray plugin in the real CurveMole interface.

The caller supplies an isolated QApplication/MainWindow and a fresh, unmasked
import of the tutorial's raw Raman data.  This helper deliberately uses the
ordinary manager, trust dialog, plugin host, detection controls and undo service;
it never draws an imitation interface or downloads executable code.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIRECTORY = Path("custom_plugins/by_main_developer/cosmic_ray_removal")
PLUGIN_IDENTIFIER = "org.curvemole.community.cosmic_ray_removal"
PLUGIN_MANIFEST = "cosmic_ray_removal.curvemole-plugin.json"
PLUGIN_FILES = (PLUGIN_MANIFEST, "cosmic_ray_removal.py", "README.md", "LICENSE", "test_plugin.py")


def _official_plugin(source_root: str | Path | None = None) -> tuple[Path, dict]:
    root = Path(source_root or ROOT).resolve()
    directory = (root / PLUGIN_DIRECTORY).resolve()
    if not directory.is_relative_to(root):
        raise ValueError("The tutorial plugin must belong to the selected source checkout.")
    for name in PLUGIN_FILES:
        path = (directory / name).resolve()
        if not path.is_file() or not path.is_relative_to(directory):
            raise ValueError(f"Missing or external official plugin file: {name}")
    metadata = json.loads((directory / PLUGIN_MANIFEST).read_text(encoding="utf-8"))
    if (metadata.get("identifier") != PLUGIN_IDENTIFIER
            or metadata.get("module") != "cosmic_ray_removal.py"
            or metadata.get("capabilities") != ["panels"]):
        raise ValueError("The official cosmic-ray plugin contract changed; review the tutorial.")
    return directory, metadata


def write_plugin_bundle(destination: str | Path, *, source_root: str | Path | None = None) -> dict:
    """Package the exact official plugin used by the captures for offline replay."""
    directory, metadata = _official_plugin(source_root)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in PLUGIN_FILES:
            entry = zipfile.ZipInfo(f"cosmic_ray_removal/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, (directory / name).read_bytes())
    return {
        "identifier": PLUGIN_IDENTIFIER,
        "version": metadata["version"],
        "filename": destination.name,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }


def capture_plugin_steps(window, app, output_dir, capture, *, source_root=None, spike_x=900.0):
    """Capture four real UI states and verify preview, acceptance and Undo/Redo.

    ``capture(widget, filename)`` must save a PNG below ``output_dir``.  Files are
    plugin-manager.png, plugin-trust.png, plugin-review.png and
    plugin-corrected.png.  No data are changed before Accept modifications.
    The supplied window is left on the accepted correction after Undo/Redo has
    been verified.  Plugin loading is restricted to the official local folder
    in ``source_root``; the caller can select the exact stable checkout.
    """
    import numpy as np
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QMessageBox, QPushButton

    from curvemole.core.extensions import extensions
    from curvemole.gui.dialogs import PluginManagerDialog
    from curvemole.version import __version__

    directory, metadata = _official_plugin(source_root)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    curve_id = window.active_curve_id
    if curve_id is None:
        raise ValueError("Select the fresh raw Raman spectrum for the plugin exercise.")
    curve = window.project.dataset.curve(curve_id)
    if np.any(curve.effective_mask) or curve.transformations:
        raise ValueError("The plugin exercise requires a fresh, unmasked, untransformed input curve.")
    original_x = curve.x.copy()
    original_y = curve.y.copy()
    original_imported_y = curve.original_y.copy()
    if not np.array_equal(original_y, original_imported_y):
        raise ValueError("Use the original raw spectrum, rather than a processed copy.")
    spike_index = int(np.argmin(np.abs(original_x - float(spike_x))))
    if not np.isclose(original_x[spike_index], spike_x):
        raise ValueError("The configured tutorial spike is absent from the x grid.")
    if PLUGIN_IDENTIFIER in window.plugin_manager.loaded:
        raise ValueError("Use an isolated tutorial session with this plugin initially unloaded.")

    screenshots = []

    def record(widget, filename):
        capture(widget, filename)
        if not (output_dir / filename).is_file():
            raise RuntimeError(f"The screenshot callback did not save {filename} in {output_dir}.")
        screenshots.append(filename)

    dialog = PluginManagerDialog(window.plugin_manager, directory, window)
    dialog.resize(1100, 690)
    matches = [index for index, candidate in enumerate(dialog.candidates)
               if candidate.metadata.identifier == PLUGIN_IDENTIFIER]
    if len(matches) != 1:
        dialog.close()
        raise RuntimeError("The real Plugin Manager did not discover the official cosmic-ray plugin.")
    dialog.list.setCurrentRow(matches[0])
    dialog.show()
    record(dialog, "plugin-manager.png")

    failures = []
    trust_captured = []
    modal_timer = QTimer(dialog)
    modal_timer.setInterval(35)

    def handle_modal():
        box = app.activeModalWidget()
        if not isinstance(box, QMessageBox):
            return
        modal_timer.stop()
        if box.windowTitle() == "Trust Python plugin" and not trust_captured:
            try:
                record(box, "plugin-trust.png")
                trust_captured.append(True)
                box.button(QMessageBox.StandardButton.Yes).click()
            except Exception as error:
                failures.append(error)
                box.button(QMessageBox.StandardButton.Cancel).click()
        elif box.windowTitle() == "Plugin Manager" and "Plugin loaded:" in box.text():
            box.button(QMessageBox.StandardButton.Ok).click()
        else:
            failures.append(RuntimeError(f"Unexpected plugin dialog: {box.windowTitle()}: {box.text()}"))
            box.reject()
        modal_timer.start()

    modal_timer.timeout.connect(handle_modal)
    modal_timer.start()
    try:
        buttons = [button for button in dialog.findChildren(QPushButton)
                   if button.text() == "Review and trust selected plugin…"]
        if len(buttons) != 1:
            raise RuntimeError("The Plugin Manager's trust control changed; review the capture script.")
        buttons[0].click()
    finally:
        modal_timer.stop()
    if failures:
        dialog.close()
        raise RuntimeError("The official plugin could not be loaded through its real trust dialog.") from failures[0]
    if not trust_captured or PLUGIN_IDENTIFIER not in window.plugin_manager.loaded:
        dialog.close()
        raise RuntimeError("The official plugin did not pass the real manager trust-and-load step.")
    dialog.accept()
    window.plugin_host.refresh()
    window.refresh_all()
    for _ in range(12):
        app.processEvents()

    entries = [entry for entry in extensions.values("panels") if entry.owner == PLUGIN_IDENTIFIER]
    if len(entries) != 1:
        raise RuntimeError("Expected the official plugin's single review panel.")
    entry = entries[0]
    window.plugin_host.run(entry)
    dock = window.plugin_host.dialogs[entry.identifier]
    panel = dock.widget().widget()
    panel.timer.stop()
    window.activate_tool_dock(dock)
    dock.setMinimumWidth(560)
    window.resizeDocks([dock], [610], Qt.Orientation.Horizontal)
    panel.method.setCurrentIndex(0)
    panel.threshold.setValue(10.0)
    panel.window.setValue(11)
    panel.max_width.setValue(5)
    panel.grow.setValue(1)
    window.plot_workspace.auto_range()
    for _ in range(12):
        app.processEvents()

    detect_buttons = [button for button in panel.findChildren(QPushButton)
                      if button.text() == "Detect automatically"]
    if len(detect_buttons) != 1:
        raise RuntimeError("The plugin's automatic-detection control changed.")
    detect_buttons[0].click()
    if len(panel.candidates) != 1:
        raise AssertionError(f"Expected exactly one synthetic spike candidate, found {len(panel.candidates)}.")
    candidate = panel.candidates[0]
    if not (candidate.start <= spike_index <= candidate.end
            and candidate.confidence == "Safe" and candidate.accepted):
        raise AssertionError("The injected spike must be detected as the selected Safe candidate.")
    panel.table.selectRow(0)
    np.testing.assert_array_equal(window.project.dataset.curve(curve_id).y, original_y)
    record(window, "plugin-review.png")

    candidate_report = {
        "x_min": float(original_x[candidate.start]),
        "x_max": float(original_x[candidate.end]),
        "points": candidate.end - candidate.start + 1,
        "score": float(candidate.score),
        "prominence_width_points": float(candidate.peak_width),
        "confidence": candidate.confidence,
    }
    undo_count = window.undo_stack.count()
    panel.accept.click()
    corrected = window.project.dataset.curve(curve_id)
    repaired_y = corrected.y.copy()
    changed = np.flatnonzero(repaired_y != original_y)
    if not len(changed) or np.any((changed < candidate.start) | (changed > candidate.end)):
        raise AssertionError("Only the accepted candidate's samples should change.")
    np.testing.assert_array_equal(corrected.x, original_x)
    np.testing.assert_array_equal(corrected.original_y, original_imported_y)
    if window.undo_stack.count() != undo_count + 1:
        raise AssertionError("Accept modifications must create exactly one Undo step.")
    if not corrected.metadata.get("cosmic_ray_removal", {}).get("history"):
        raise AssertionError("The accepted correction must retain its plugin provenance.")
    record(window, "plugin-corrected.png")

    window.undo_stack.undo()
    panel.refresh()
    np.testing.assert_array_equal(window.project.dataset.curve(curve_id).y, original_y)
    window.undo_stack.redo()
    panel.refresh()
    np.testing.assert_array_equal(window.project.dataset.curve(curve_id).y, repaired_y)

    return {
        "application_version": __version__,
        "identifier": PLUGIN_IDENTIFIER,
        "plugin_version": metadata["version"],
        "source_module_sha256": hashlib.sha256((directory / "cosmic_ray_removal.py").read_bytes()).hexdigest(),
        "settings": {"method": "Single spectrum — modified Z-score", "threshold": 10.0,
                     "median_window_points": 11, "maximum_spike_width_points": 5,
                     "grow_candidate_points": 1},
        "candidate": candidate_report,
        "changed_points": int(len(changed)),
        "original_data_preserved": True,
        "preview_does_not_mutate": True,
        "undo_redo_verified": True,
        "screenshots": screenshots,
    }
