"""Portable, project-scoped X calibrations, with reversible curve provenance."""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import numpy as np
from numpy.polynomial import Polynomial

from curvemole.core.data import CurveState, Transformation

OWNER = "org.curvemole.community.x-axis-calibration"
KEY = "profiles"
TAG = "curvemole_x_calibration"


def make_profile(name, measured, reference, *, degree=1, unit="nm", source=""):
    x, y = np.asarray(measured, float), np.asarray(reference, float)
    if (x.ndim != 1 or x.shape != y.shape or not len(x)
            or not np.all(np.isfinite([x, y]))):
        raise ValueError("Provide matching finite measured and reference positions.")
    if degree not in (0, 1, 2, 3) or len(x) < degree + 1:
        raise ValueError("Not enough references for the selected degree.")
    if len(np.unique(x)) != len(x) or not str(name).strip():
        raise ValueError("Use a name and distinct measured positions.")
    order = np.argsort(x)
    x, y = x[order], y[order]
    if len(y) > 1 and np.any(np.diff(y) <= 0):
        raise ValueError("Reference positions must increase with measured positions.")
    # Normalise before fitting to avoid cancellation at large axis offsets.
    origin, scale = float(np.mean(x)), float(np.ptp(x)) or 1.0
    z = (x - origin) / scale
    coefficients = ([float(np.mean(y - x)) + origin, scale] if degree == 0
                    else Polynomial.fit(z, y, degree).convert().coef.tolist())
    profile = {"id": uuid.uuid4().hex, "name": str(name).strip(), "unit": str(unit),
               "degree": degree, "origin": origin, "scale": scale,
               "coefficients": coefficients, "measured": x.tolist(),
               "reference": y.tolist(), "source": str(source)}
    evaluate(profile, x)
    profile["residuals"] = (evaluate(profile, x) - y).tolist()
    profile["rms"] = float(np.sqrt(np.mean(np.square(profile["residuals"]))))
    return profile


def evaluate(profile, values):
    values = np.asarray(values, float)
    if not np.all(np.isfinite(values)) or not values.size:
        raise ValueError("The X axis must contain finite values.")
    polynomial = Polynomial(profile["coefficients"])
    scale = float(profile["scale"])
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid calibration scale.")
    z = (values - profile["origin"]) / scale
    lo, hi = float(z.min()), float(z.max())
    derivative = polynomial.deriv()
    candidates = [lo, hi]
    for root in derivative.deriv().roots():
        if abs(root.imag) < 1e-10 and lo < root.real < hi:
            candidates.append(float(root.real))
    if np.any(derivative(candidates) <= 0):
        raise ValueError("Calibration is not strictly increasing over this spectrum.")
    result = polynomial(z)
    if not np.all(np.isfinite(result)):
        raise ValueError("Calibration produced non-finite positions.")
    return result


def validate_profile(value):
    """Rebuild from reference pairs; never execute file-supplied expressions."""
    if not isinstance(value, dict):
        raise ValueError("Invalid calibration record.")
    profile = make_profile(value["name"], value["measured"], value["reference"],
                           degree=value["degree"], unit=value.get("unit", ""),
                           source=value.get("source", ""))
    return profile


def export_profile(profile, path):
    content = {"format": "curvemole-x-calibration", "version": 1,
               "calibration": profile}
    target = Path(path)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(content, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(target)


def import_profile(path):
    if Path(path).stat().st_size > 1_000_000:
        raise ValueError("Calibration file exceeds 1 MB.")
    content = json.loads(Path(path).read_text(encoding="utf-8"))
    if content.get("format") != "curvemole-x-calibration" or content.get("version") != 1:
        raise ValueError("Unsupported calibration file format/version.")
    return validate_profile(content["calibration"])


def profiles(project):
    return project.ui_state.get("plugin_data", {}).get(OWNER, {}).get(KEY, {})


def add_profile(project, profile):
    project.ui_state.setdefault("plugin_data", {}).setdefault(OWNER, {}).setdefault(KEY, {})[profile["id"]] = copy.deepcopy(profile)


def _uncalibrated(curve):
    candidate = copy.deepcopy(curve)
    matches = [i for i, t in enumerate(candidate.transformations) if TAG in t.parameters]
    if matches:
        index = matches[0]
        if len(matches) != 1 or index != len(candidate.transformations) - 1:
            raise ValueError(f"{curve.name}: undo transformations made after calibration first.")
        candidate.transformations.pop()
        candidate._recompute()
    return candidate


def outside_range(curve, profile):
    x = _uncalibrated(curve).x
    return bool(x.min() < min(profile["measured"]) or x.max() > max(profile["measured"]))


def calibrated_curve(curve, profile):
    """Return a detached replacement. Reapplication always starts before calibration."""
    candidate = _uncalibrated(curve)
    base_x = candidate.x.copy()
    new_x = base_x if profile is None else evaluate(profile, base_x)
    old_x = curve.x
    order = np.argsort(old_x)
    if np.any(np.diff(old_x[order]) <= 0):
        raise ValueError(f"{curve.name}: X positions must be distinct.")
    # Fit intervals and mask annotations stay attached to the same data points.
    def map_ranges(ranges):
        return [tuple(float(v) for v in np.interp(pair, old_x[order], new_x[order]))
                for pair in ranges]
    candidate.fit_ranges = map_ranges(curve.fit_ranges)
    for name, mask in candidate.masks.items():
        mask.ranges = map_ranges(curve.masks[name].ranges)
    prior = curve.metadata.get(TAG, {})
    original_unit = prior.get("original_unit", curve.x_unit)
    original_label = prior.get("original_label", curve.x_label)
    original_sigma = prior.get("original_sigma_x", None if curve.sigma_x is None else curve.sigma_x.tolist())
    candidate.sigma_x = None if original_sigma is None else np.asarray(original_sigma, float)
    candidate.x_unit, candidate.x_label = original_unit, original_label
    candidate.metadata.pop(TAG, None)
    if profile is not None:
        origin, scale = profile["origin"], profile["scale"]
        z = f"((x-({origin!r}))/({scale!r}))"
        formula = "+".join(f"({float(c)!r})*{z}**{i}" for i, c in enumerate(profile["coefficients"]))
        candidate.apply_transformation(Transformation(
            "custom_formula", {"axis": "x", "formula": formula, TAG: profile["id"]},
            description="X calibration: " + profile["name"]))
        candidate.x_unit = profile["unit"]
        if candidate.sigma_x is not None:
            slope = Polynomial(profile["coefficients"]).deriv()((base_x-origin)/scale)/scale
            candidate.sigma_x = candidate.sigma_x * np.abs(slope)
        candidate.metadata[TAG] = {"profile": copy.deepcopy(profile),
                                   "original_unit": original_unit, "original_label": original_label,
                                   "original_sigma_x": original_sigma}
    candidate.redo_transformations.clear()
    candidate.state = CurveState.MODIFIED if curve.state == CurveState.FITTED else curve.state
    return candidate


def apply_to_project(project, curve_ids, profile):
    """Validate the entire batch before touching any curve."""
    replacements = {cid: calibrated_curve(project.dataset.curve(cid), profile) for cid in curve_ids}
    for series in project.dataset.series:
        series.curves[:] = [replacements.get(c.id, c) for c in series.curves]
    for cid in replacements:
        project.results.pop(cid, None)
    if profile is not None:
        add_profile(project, profile)


def confirm_extrapolation(parent, curves, profile):
    from PySide6.QtWidgets import QMessageBox
    count = sum(outside_range(c, profile) for c in curves)
    if not count:
        return True
    return QMessageBox.question(
        parent, "Calibration extrapolation",
        f"{count} spectrum/spectra extend beyond the reference range.\n"
        "Calibration outside that range is extrapolated and may be inaccurate. Continue?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes


def _enabled(window):
    from curvemole.core.extensions import extensions
    return (OWNER not in window.plugin_manager.errors
            and any(e.owner == OWNER for e in extensions.entries.values()))


def commit_calibration(window, curve_ids, profile):
    from PySide6.QtWidgets import QMessageBox
    if window._thread is not None or window.project.read_only or not _enabled(window):
        raise ValueError("Wait for the fit to finish and use an editable project with the plugin enabled.")
    if not curve_ids:
        raise ValueError("Select at least one spectrum.")
    curves = [window.project.dataset.curve(cid) for cid in curve_ids]
    if profile is not None and not confirm_extrapolation(window, curves, profile):
        return False
    if (any(window.project.model_for(cid).components for cid in curve_ids)
            and QMessageBox.question(
            window, "Existing fits", "Changing X invalidates existing fits. Models retain their old initial "
            "parameters: review peak positions, bounds and backgrounds before refitting. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes):
        return False
    before = copy.deepcopy(window.project)
    after = copy.deepcopy(before)
    apply_to_project(after, curve_ids, profile)
    def restore(project):
        window.project = copy.deepcopy(project)
    window._push_change("Apply X calibration" if profile else "Restore uncalibrated X",
                        lambda: restore(after), lambda: restore(before), modified_curve_ids=set())
    return True


def create_panel(context):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )

    class CalibrationPanel(QWidget):
        def __init__(self):
            super().__init__()
            self.services = context.services
            # Use the existing native import and undo commands; no host modifications.
            self.window = self.services._window()
            self.project_id = None
            self.signature = None
            layout = QVBoxLayout(self)
            explanation = QLabel("Load a calibrant, fit its peaks in CurveMole, then read their centres here. "
                                 "Enter the known positions and save a calibration.")
            explanation.setWordWrap(True)
            layout.addWidget(explanation)
            form = QFormLayout()
            self.spectrum = QComboBox()
            form.addRow("Calibrant spectrum", self.spectrum)
            self.name = QLineEdit("Calibration 1")
            self.unit = QLineEdit("nm")
            self.method = QComboBox()
            for label, degree in [("Offset only", 0), ("Linear", 1), ("Quadratic", 2), ("Cubic", 3)]:
                self.method.addItem(label, degree)
            self.method.setCurrentIndex(1)
            form.addRow("Profile name", self.name)
            form.addRow("Output X unit", self.unit)
            form.addRow("Correction", self.method)
            layout.addLayout(form)
            self.button(layout, "Load calibrant spectrum…", self.load_calibrant)
            self.button(layout, "Read fitted peak centres", self.read_peaks)
            self.table = QTableWidget(0, 3)
            self.table.setHorizontalHeaderLabels(["Measured centre", "Known position", "Residual"])
            self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            layout.addWidget(self.table)
            row = QHBoxLayout()
            self.button(row, "Add reference", lambda: self.table.insertRow(self.table.rowCount()))
            self.button(row, "Remove selected references", self.remove_rows)
            layout.addLayout(row)
            self.button(layout, "Calculate and save calibration", self.save_profile)
            self.quality = QLabel("Use references spanning the spectrum. Residuals use output X units.")
            self.quality.setWordWrap(True)
            layout.addWidget(self.quality)
            self.saved = QComboBox()
            layout.addWidget(self.saved)
            self.saved.currentIndexChanged.connect(self.show_profile)
            self.button(layout, "Apply to ALL project spectra", lambda: self.apply("all"))
            self.button(layout, "Apply to selected spectra", lambda: self.apply("selected"))
            self.button(layout, "Apply to active spectrum's series", lambda: self.apply("series"))
            self.button(layout, "Restore original X of selected spectra", self.restore_selected)
            row = QHBoxLayout()
            self.button(row, "Export calibration…", self.export)
            self.button(row, "Import calibration…", self.load_profile)
            layout.addLayout(row)
            self.assignments = QLabel()
            self.assignments.setWordWrap(True)
            layout.addWidget(self.assignments)
            layout.addStretch()
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.refresh)
            self.timer.start(500)
            self.refresh()

        def button(self, layout, label, callback):
            button = QPushButton(label)
            def guarded():
                try:
                    self.services._window()
                    callback()
                except Exception as exc:
                    QMessageBox.warning(self, "X calibration", str(exc))
            button.clicked.connect(guarded)
            layout.addWidget(button)

        def refresh(self):
            if not _enabled(self.window):
                self.timer.stop()
                return
            project = self.window.project
            signature = (project.id, tuple((c.id, c.name) for c in project.curves),
                         json.dumps(profiles(project), sort_keys=True),
                         tuple((c.id, c.metadata.get(TAG, {}).get("profile", {}).get("id")) for c in project.curves))
            if signature == self.signature:
                return
            self.signature = signature
            if self.project_id != project.id:
                self.table.setRowCount(0)
                self.quality.setText("Use references spanning the spectrum.")
                self.project_id = project.id
            previous = self.spectrum.currentData()
            self.spectrum.clear()
            for curve in project.curves:
                self.spectrum.addItem(curve.name, curve.id)
            index = self.spectrum.findData(previous or self.window.active_curve_id)
            self.spectrum.setCurrentIndex(max(0, index))
            previous = self.saved.currentData()
            self.saved.blockSignals(True)
            self.saved.clear()
            for profile in profiles(project).values():
                self.saved.addItem(f"{profile['name']} [{profile['unit']}] ({profile['id'][:8]})", profile["id"])
            self.saved.setCurrentIndex(max(0, self.saved.findData(previous)))
            self.saved.blockSignals(False)
            counts = {}
            for c in project.curves:
                name = c.metadata.get(TAG, {}).get("profile", {}).get("name", "Original X")
                counts[name] = counts.get(name, 0) + 1
            self.assignments.setText("Project spectra: " + "; ".join(f"{k}: {v}" for k, v in counts.items()))

        def load_calibrant(self):
            self.window.import_data()
            self.refresh()
            self.spectrum.setCurrentIndex(self.spectrum.findData(self.window.active_curve_id))

        def read_peaks(self):
            curve_id = self.spectrum.currentData()
            if curve_id is None:
                raise ValueError("Load a calibrant first.")
            curve = self.window.project.dataset.curve(curve_id)
            if TAG in curve.metadata:
                raise ValueError("Use an uncalibrated reference spectrum (restore its X first).")
            model = self.window.project.model_for(curve_id)
            values = self.window.project.resolved_parameter_values()
            peaks = [c for c in model.components if not c.is_background and "center" in c.parameters]
            if not peaks:
                raise ValueError("Fit the calibrant peaks in CurveMole, then read their centres.")
            if curve.state != CurveState.FITTED:
                raise ValueError("The calibrant needs an up-to-date successful fit before reading centres.")
            centres = sorted(values[f"{curve_id}.{c.id}.center"] for c in peaks)
            self.table.setRowCount(len(centres))
            for row, centre in enumerate(centres):
                self.table.setItem(row, 0, QTableWidgetItem(f"{centre:.12g}"))
                self.table.setItem(row, 1, QTableWidgetItem(""))

        def remove_rows(self):
            for row in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
                self.table.removeRow(row)

        def save_profile(self):
            from PySide6.QtCore import Qt
            measured, reference = [], []
            for row in range(self.table.rowCount()):
                try:
                    measured.append(float(self.table.item(row, 0).text()))
                    reference.append(float(self.table.item(row, 1).text()))
                except (AttributeError, ValueError) as exc:
                    raise ValueError(f"Reference row {row+1}: enter both numeric positions.") from exc
            p = make_profile(self.name.text(), measured, reference, degree=self.method.currentData(),
                             unit=self.unit.text().strip(), source=self.spectrum.currentText())
            data = copy.deepcopy(self.services.snapshot().data)
            data.setdefault(KEY, {})[p["id"]] = p
            self.services.save_settings(data)
            # Match residuals back to the table's original row order.
            residuals = evaluate(p, measured) - np.asarray(reference)
            for row, residual in enumerate(residuals):
                item = QTableWidgetItem(f"{residual:.6g}")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 2, item)
            self.refresh()
            self.saved.setCurrentIndex(self.saved.findData(p["id"]))
            self.show_profile()

        def profile(self):
            p = profiles(self.window.project).get(self.saved.currentData())
            if p is None:
                raise ValueError("Create or import a calibration first.")
            return p

        def show_profile(self, *_):
            if self.saved.currentData() is None:
                return
            p = self.profile()
            count = len(p["measured"])
            free = 1 if p["degree"] == 0 else p["degree"] + 1
            note = " No redundant references: zero residual does not validate accuracy." if count == free else ""
            self.quality.setText(f"{p['name']}: RMS residual {p['rms']:.6g} {p['unit']}; "
                                 f"{count} references; range {min(p['measured']):.6g} – {max(p['measured']):.6g}." + note)

        def apply(self, scope):
            project = self.window.project
            if scope == "all":
                ids = [c.id for c in project.curves]
            elif scope == "series":
                if self.window.active_curve_id is None:
                    raise ValueError("Select a spectrum first.")
                ids = [c.id for c in project.dataset.series_for(self.window.active_curve_id).curves]
            else:
                ids = list(self.window.curve_tree.selected_curve_ids())
            commit_calibration(self.window, ids, self.profile())
            self.refresh()

        def restore_selected(self):
            ids = [cid for cid in self.window.curve_tree.selected_curve_ids()
                   if TAG in self.window.project.dataset.curve(cid).metadata]
            commit_calibration(self.window, ids, None)
            self.refresh()

        def export(self):
            p = self.profile()
            path, _ = QFileDialog.getSaveFileName(self, "Export calibration", "calibration.cmcal.json", "Calibration (*.json)")
            if path:
                export_profile(p, path)

        def load_profile(self):
            path, _ = QFileDialog.getOpenFileName(self, "Import calibration", "", "Calibration (*.json)")
            if path:
                p = import_profile(path)
                data = copy.deepcopy(self.services.snapshot().data)
                data.setdefault(KEY, {})[p["id"]] = p
                self.services.save_settings(data)
                self.refresh()
                self.saved.setCurrentIndex(self.saved.findData(p["id"]))

    return CalibrationPanel()


def register(api):
    api.add("panels", "calibration", "X-axis calibration", create_panel,
            description="Calibrant peak references, multiple project profiles and explicit application to selected spectra.",
            auto_show=True)
