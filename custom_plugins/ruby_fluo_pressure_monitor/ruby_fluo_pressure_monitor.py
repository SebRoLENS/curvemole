"""Ruby fluorescence pressure monitor. Literature references in README.md.

Widths are FREE; pseudo-Voigt mixing eta is FIXED (default 0.5).
No spectrum is ever used to infer a zero-pressure reference or a temperature.
"""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks, peak_widths

OWNER = "org.curvemole.community.ruby_fluo_pressure_monitor"
DEFAULTS = {
    "filename_contains": "ruby",
    "temperature_K": 296.0,
    "reference_temperature_K": 296.0,
    "reference_nm": 694.281,
    "A_GPa": 1904.0,
    "B": 7.665,
    "thermal_model": "ragan",
    "eta": 0.5,
    "width_min_nm": 0.01,
    "width_max_nm": 4.0,
    "search_min_nm": 680.0,
    "search_max_nm": 800.0,
    "separation_min_nm": 0.6,
    "separation_max_nm": 2.5,
    "background_exclusion_widths": 2.0,
    "region_margin_nm": 3.0,
    "prominence_fraction": 0.03,
    "background_fixed": True,
    "ragan_coefficients_cm1": [14423.0, 4.49e-2, -4.81e-4, 3.71e-7],
    "datchi_cold_plateau_nm": -0.887,
    "datchi_cold_coefficients_nm": [0.0, 0.00664, 6.76e-6, -2.33e-8],
    "datchi_hot_slope_nm_K": 0.00726,
    "datchi_hot_coefficients_nm": [0.0, 0.00746, -3.01e-6, 8.76e-9],
}
THERMAL_MODELS = {
    "ragan": (
        "Ragan et al. (1992) — cubic, 15–600 K",
        15.0,
        600.0,
        "https://doi.org/10.1063/1.351951",
    ),
    "datchi": (
        "Datchi et al. (2007) — piecewise, 15–600 K",
        15.0,
        600.0,
        "https://doi.org/10.1080/08957950701659593",
    ),
    "datchi_hot": (
        "Datchi et al. (2007) — high-temperature cubic, 296–600 K",
        296.0,
        600.0,
        "https://doi.org/10.1080/08957950701659593",
    ),
}


def settings(data=None):
    result = copy.deepcopy(DEFAULTS)
    result.update(data or {})
    if "temperature_confirmed" in result:
        # Upgrade the old automatic workflow to fit the line first and hold it.
        result.pop("temperature_confirmed")
        result["background_fixed"] = True
    return result


def validate(s):
    numeric = [
        key
        for key, value in DEFAULTS.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    if not all(np.isfinite(float(s[key])) for key in numeric):
        raise ValueError("Parameters must be finite numbers.")
    if s["thermal_model"] not in THERMAL_MODELS:
        raise ValueError("Unknown temperature correction.")
    if not 0 <= s["eta"] <= 1 or not 0 < s["width_min_nm"] < s["width_max_nm"]:
        raise ValueError("Require 0 ≤ eta ≤ 1 and positive, ordered width limits.")
    if (
        not s["search_min_nm"] < s["search_max_nm"]
        or not 0 < s["separation_min_nm"] < s["separation_max_nm"]
    ):
        raise ValueError("Invalid search or peak-separation range.")
    if s["A_GPa"] <= 0 or s["B"] <= 0 or s["reference_nm"] <= 0:
        raise ValueError("A, B and the reference wavelength must be positive.")
    if (
        s["region_margin_nm"] <= 0
        or s["background_exclusion_widths"] <= 0
        or not 0 < s["prominence_fraction"] < 1
    ):
        raise ValueError("Invalid peak-detection/background parameters.")
    for key in (
        "ragan_coefficients_cm1",
        "datchi_cold_coefficients_nm",
        "datchi_hot_coefficients_nm",
    ):
        if len(s[key]) != 4 or not np.all(np.isfinite(s[key])):
            raise ValueError(f"{key}: require four finite coefficients, from constant to cubic.")
    if not 15 <= s["temperature_K"] <= 600 or not 15 <= s["reference_temperature_K"] <= 600:
        raise ValueError("Sample and reference temperatures must be between 15 and 600 K.")


def thermal_position(T, s):
    """Ambient-pressure thermal curve in nm; differences remove its offset."""
    name = s["thermal_model"]
    _, lower, upper, _ = THERMAL_MODELS[name]
    if not lower <= T <= upper:
        raise ValueError(
            f"{THERMAL_MODELS[name][0]}: {T:g} K is outside the supported range; extrapolation is disabled."
        )
    if name == "ragan":
        wavenumber = np.polynomial.polynomial.polyval(T, s["ragan_coefficients_cm1"])
        if wavenumber <= 0:
            raise ValueError("Nonpositive thermal wavenumber.")
        return float(1e7 / wavenumber)
    dt = T - 296.0
    if name == "datchi_hot":
        return float(np.polynomial.polynomial.polyval(dt, s["datchi_hot_coefficients_nm"]))
    if T < 50:
        return float(s["datchi_cold_plateau_nm"])
    if T <= 296:
        return float(np.polynomial.polynomial.polyval(dt, s["datchi_cold_coefficients_nm"]))
    return float(s["datchi_hot_slope_nm_K"] * dt)


def pressure(center_nm, s):
    """Subtract thermal wavelength shift, then apply Mao–Xu–Bell (1986).

    Assumes additive wavelength shifts; does not silently replace the pressure
    scale or invent a P–T cross term. Both reference and sample T must be valid.
    """
    validate(s)
    shift = thermal_position(s["temperature_K"], s) - thermal_position(
        s["reference_temperature_K"], s
    )
    corrected = center_nm - shift
    if not np.isfinite(corrected) or corrected <= 0:
        raise ValueError("Invalid temperature-corrected peak center.")
    return float(
        s["A_GPa"] / s["B"] * np.expm1(s["B"] * np.log(corrected / s["reference_nm"]))
    ), shift


def pressure_uncertainty(center_nm, parameter, s):
    """First-order 1-sigma propagation of the fitted R1 center only."""
    error = parameter.standard_error
    note = ("1σ fit uncertainty only; excludes temperature, wavelength calibration and "
            "pressure-scale uncertainty. A fixed background is treated as exact.")
    output = {"R1_std_nm": None, "pressure_std_GPa": None, "uncertainty_note": note}
    if (parameter.fixed and not parameter.link) or error is None or not np.isfinite(error) or error < 0:
        output["uncertainty_note"] = "Fit uncertainty unavailable (fixed R1 or unavailable covariance). " + note
        return output
    _, shift = pressure(center_nm, s)
    ratio = (center_nm - shift) / s["reference_nm"]
    sensitivity = s["A_GPa"] / s["reference_nm"] * ratio ** (s["B"] - 1)
    output.update(R1_std_nm=float(error), pressure_std_GPa=float(abs(sensitivity) * error))
    return output


def pressure_text(meta):
    value = meta["pressure_GPa"]
    error = meta.get("pressure_std_GPa")
    if error is None:
        return f"Pressure: {value:.6g} GPa (fit uncertainty unavailable)"
    return f"Pressure: {value:.6g} ± {error:.2g} GPa (1σ, fit only)"


def analyse_curve(curve, s, cancellation=None):
    from curvemole.core.fitting import FitSettings, Fitter
    from curvemole.core.models import Component, Model

    validate(s)
    x, y = np.asarray(curve.x), np.asarray(curve.y)
    if np.any(np.diff(x) <= 0):
        raise ValueError("The wavelength axis must be increasing and expressed in nm.")
    valid = ~curve.effective_mask & (x >= s["search_min_nm"]) & (x <= s["search_max_nm"])
    if valid.sum() < 30:
        raise ValueError("Fewer than 30 valid points in the wavelength search range.")
    xx, yy = x[valid], y[valid]
    step = float(np.median(np.diff(xx)))
    # Robust baseline seed; no changes to original intensities.
    baseline_points = yy <= np.quantile(yy, 0.5)
    slope, intercept = np.polyfit(xx[baseline_points], yy[baseline_points], 1)
    signal = gaussian_filter1d(yy - (intercept + slope * xx), 1.0)
    prominence = max(float(np.ptp(signal)) * s["prominence_fraction"], np.finfo(float).eps)
    peaks, info = find_peaks(
        signal, prominence=prominence, distance=max(2, int(s["separation_min_nm"] / step / 2))
    )
    widths = peak_widths(signal, peaks, rel_height=0.5)[0] if len(peaks) else np.array([])
    candidates = []
    for i in range(len(peaks)):
        for j in range(i + 1, len(peaks)):
            distance = xx[peaks[j]] - xx[peaks[i]]
            if (
                s["separation_min_nm"] <= distance <= s["separation_max_nm"]
                and min(widths[i], widths[j]) >= 2
            ):
                candidates.append((float(info["prominences"][i] * info["prominences"][j]), i, j))
    if not candidates:
        raise ValueError(
            "Doublet unresolved or not detected: check the search range, separation limits and spectrum."
        )
    _, a, b = max(candidates)
    centers = [float(xx[peaks[a]]), float(xx[peaks[b]])]
    guessed_widths = [
        float(np.clip(widths[i] * step, s["width_min_nm"] * 1.1, s["width_max_nm"] * 0.9))
        for i in (a, b)
    ]
    lo, hi = centers[0] - s["region_margin_nm"], centers[1] + s["region_margin_nm"]
    band_points = np.zeros(x.size, dtype=bool)
    for center, width in zip(centers, guessed_widths, strict=True):
        band_points |= abs(x - center) <= s["background_exclusion_widths"] * width
    band_points &= (x >= max(lo, s["search_min_nm"])) & (x <= min(hi, s["search_max_nm"]))
    bg_points = valid & ~band_points
    if bg_points.sum() < 8:
        raise ValueError(
            "Insufficient background points: increase the region margin or reduce peak exclusion."
        )
    # Stage 1: bands temporarily masked; fit only a straight background.
    original_excluded = curve.effective_mask.copy()
    temporary = curve.add_mask("Ruby background temporary")
    temporary.excluded[:] = ~bg_points
    model = Model(name="Ruby R2 + R1 + linear background")
    bg = Component.create(
        "linear",
        name="Ruby background",
        initial={"intercept": float(intercept), "slope": float(slope)},
    )
    bg.is_background = True
    model.components.append(bg)
    fit_settings = FitSettings(max_nfev=2000)
    try:
        baseline_fit = Fitter().fit_single(curve, model, fit_settings, cancellation=cancellation)
        if not baseline_fit.success:
            raise ValueError("Background fit did not converge.")
    finally:
        curve.masks.pop(temporary.name, None)
    baseline_parameters = {k: p.value for k, p in bg.parameters.items()}
    # Stage 2: invert the band exclusion within the valid search domain.
    local = curve.add_mask("Ruby local fit region")
    local.excluded[:] = ~band_points
    midpoint = sum(centers) / 2
    components = []
    for index, (center, width) in enumerate(zip(centers, guessed_widths, strict=True)):
        height = max(
            float(
                np.interp(center, x, y)
                - baseline_parameters["intercept"]
                - baseline_parameters["slope"] * center
            ),
            np.finfo(float).eps,
        )
        component = Component.create(
            "pseudo_voigt",
            name="R2" if index == 0 else "R1",
            initial={
                "area": height * width * 1.3,
                "center": center,
                "fwhm": width,
                "eta": s["eta"],
            },
        )
        component.parameters["eta"].fixed = True
        component.parameters["fwhm"].set_bounds(s["width_min_nm"], s["width_max_nm"])
        component.parameters["center"].set_bounds(
            max(lo, xx[0]) if index == 0 else midpoint, midpoint if index == 0 else min(hi, xx[-1])
        )
        component.parameters["area"].minimum = 0.0
        components.append(component)
    model.components.extend(components)
    for parameter in bg.parameters.values():
        parameter.fixed = bool(s["background_fixed"])
    result = Fitter().fit_single(curve, model, fit_settings, cancellation=cancellation)
    if not result.success:
        raise ValueError("Doublet fit did not converge: " + result.message)
    centers_fit = [c.parameters["center"].value for c in components]
    widths_fit = [c.parameters["fwhm"].value for c in components]
    if centers_fit[1] <= centers_fit[0]:
        raise ValueError("Invalid R2/R1 peak order.")
    warnings = list(result.warnings)
    for component in components:
        for name in ("center", "fwhm"):
            p = component.parameters[name]
            tolerance = (p.maximum - p.minimum) * 1e-4
            if min(p.value - p.minimum, p.maximum - p.value) < tolerance:
                warnings.append(f"{component.name}: {name} is at its bound; review the fit.")
    if centers_fit[1] - centers_fit[0] < max(widths_fit):
        warnings.append("Peaks strongly overlap: verify their identification and the R1 center.")
    P, shift, pressure_error = None, None, None
    try:
        P, shift = pressure(centers_fit[1], s)
        if P < 0:
            warnings.append("Negative pressure: check the reference and temperature.")
        if P > 80:
            warnings.append("Above 80 GPa: extrapolating the Mao–Xu–Bell 1986 pressure scale.")
        if P > 20 and abs(s["temperature_K"] - s["reference_temperature_K"]) > 1:
            warnings.append(
                "Above 20 GPa: pressure/temperature shift separability is not guaranteed; cross terms may matter."
            )
    except ValueError as exc:
        pressure_error = str(exc)
    metadata = {
        "R2_nm": centers_fit[0],
        "R1_nm": centers_fit[1],
        "FWHM_R2_nm": widths_fit[0],
        "FWHM_R1_nm": widths_fit[1],
        "eta_fixed": s["eta"],
        "pressure_GPa": P,
        "temperature_K": s["temperature_K"],
        "thermal_shift_nm": shift,
        "pressure_error": pressure_error,
        "settings": copy.deepcopy(s),
        "warnings": warnings,
        "background_initial_fit": baseline_parameters,
        "background_points": int(bg_points.sum()),
        "local_fit_points": int((~curve.effective_mask).sum()),
        "background_excluded_intervals_nm": [
            [c - s["background_exclusion_widths"] * w, c + s["background_exclusion_widths"] * w]
            for c, w in zip(centers, guessed_widths, strict=True)
        ],
        "fit_region_nm": [float(lo), float(hi)],
        "original_masked_points": int(original_excluded.sum()),
        "pressure_reference": "https://doi.org/10.1029/JB091iB05p04673",
        "thermal_reference": THERMAL_MODELS[s["thermal_model"]][3],
    }
    if P is not None:
        metadata.update(pressure_uncertainty(centers_fit[1], components[1].parameters["center"], s))
    curve.metadata["ruby_monitor"] = metadata
    return model, result, metadata


def process(context):
    """Headless callback for CurveMole's opt-in automatic import worker."""
    s = settings(context.data)
    summaries = []
    for curve in context.project.curves:
        if (
            s["filename_contains"].casefold()
            not in Path(curve.source or curve.name).name.casefold()
        ):
            raise ValueError(
                f"File ignored: filename does not contain {s['filename_contains']!r}. Set the same filename filter in the File menu."
            )
        try:
            working = copy.deepcopy(curve)
            model, result, meta = analyse_curve(working, s, getattr(context, "cancellation", None))
            curve.masks = working.masks
            curve.active_mask = working.active_mask
            curve.state = working.state
            curve.metadata = working.metadata
            context.project.models[curve.id] = model
            context.project.results[curve.id] = result
            context.project.results["last_fit"] = result
            value = (
                pressure_text(meta)
                if meta["pressure_GPa"] is not None
                else meta["pressure_error"]
            )
            summaries.append(f"{curve.name}: R1 = {meta['R1_nm']:.5f} nm | {value}")
            if meta["warnings"]:
                summaries.extend(meta["warnings"])
        except Exception as exc:
            # Keep the raw acquisition visible on analytical failure, without a pressure.
            from curvemole.core.errors import FitCancelled

            if isinstance(exc, FitCancelled):
                raise
            curve.metadata["ruby_monitor"] = {
                "pressure_GPa": None,
                "error": str(exc),
                "settings": copy.deepcopy(s),
            }
            summaries.append(f"{curve.name}: analysis failed — {exc}")
    return "\n".join(summaries)


def configure(context):
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QDoubleSpinBox,
        QFormLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPlainTextEdit,
        QScrollArea,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )

    context.settings_only = True
    s = settings(context.data)
    dialog = QDialog()
    dialog.setWindowTitle("Ruby fluorescence pressure monitor — settings")
    dialog.resize(760, 670)
    layout = QVBoxLayout(dialog)
    tabs = QTabWidget()
    layout.addWidget(tabs)
    page = QWidget()
    form = QFormLayout(page)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(page)
    tabs.addTab(scroll, "Measurement and fit")
    name = QLineEdit(s["filename_contains"])
    form.addRow("Filename contains", name)
    combos = QComboBox()
    for key, (label, *_rest) in THERMAL_MODELS.items():
        combos.addItem(label, key)
    combos.setCurrentIndex(combos.findData(s["thermal_model"]))
    form.addRow("Temperature correction", combos)
    fields = {}
    labels = {
        "temperature_K": ("Sample temperature [K]", 15.0, 600.0, 3),
        "reference_temperature_K": ("Reference temperature [K]", 15.0, 600.0, 3),
        "reference_nm": ("R1 at ambient pressure [nm]", 600.0, 800.0, 6),
        "A_GPa": ("Mao–Xu–Bell: A [GPa]", 1.0, 10000.0, 4),
        "B": ("Mao–Xu–Bell: B", 0.01, 100.0, 6),
        "eta": ("FIXED shape η (0 = Gaussian; 1 = Lorentzian)", 0.0, 1.0, 3),
        "width_min_nm": ("Minimum FWHM [nm] — FREE width", 0.0001, 20.0, 4),
        "width_max_nm": ("Maximum FWHM [nm]", 0.001, 30.0, 4),
        "search_min_nm": ("Search from [nm]", 100.0, 2000.0, 3),
        "search_max_nm": ("Search to [nm]", 100.0, 2000.0, 3),
        "separation_min_nm": ("Minimum R1−R2 separation [nm]", 0.001, 20.0, 3),
        "separation_max_nm": ("Maximum R1−R2 separation [nm]", 0.002, 30.0, 3),
        "background_exclusion_widths": ("Background exclusion: ± N × FWHM", 0.1, 20.0, 2),
        "region_margin_nm": ("Outer doublet margin [nm]", 0.1, 30.0, 2),
    }
    for key, (label, low, high, decimals) in labels.items():
        box = QDoubleSpinBox()
        box.setRange(low, high)
        box.setDecimals(decimals)
        box.setValue(s[key])
        fields[key] = box
        form.addRow(label, box)
    fixed = QCheckBox("Fix the background after its initial fit (otherwise refine with the peaks)")
    fixed.setChecked(s["background_fixed"])
    form.addRow(fixed)
    info = QLabel(
        "η = 0: Gaussian; η = 1: Lorentzian. Default 0.5, fixed during fitting.\n"
        "Ragan: 15–600 K. Piecewise Datchi: 15–50 K plateau, 50–296 K cubic, 296–600 K linear.\n"
        "High-temperature Datchi cubic: 296–600 K (source extends to 900 K). No thermal extrapolation.\n"
        "Both temperatures must be within the selected model range. λ₀ = 694.281 nm at 296 K\n"
        "is the Datchi (2007) reference; it is not derived from any imported spectrum."
    )
    info.setWordWrap(True)
    layout.addWidget(info)
    advanced = QPlainTextEdit(json.dumps(s, indent=2, ensure_ascii=False))
    tabs.addTab(advanced, "All coefficients (JSON)")

    # On tab changes, keep common controls and the complete editable configuration consistent.
    def from_controls():
        current = json.loads(advanced.toPlainText())
        current.update({key: box.value() for key, box in fields.items()})
        current.update(
            filename_contains=name.text().strip(),
            thermal_model=combos.currentData(),
            background_fixed=fixed.isChecked(),
        )
        return current

    previous_tab = [0]

    def sync_tabs(index):
        try:
            if previous_tab[0] == 0:
                advanced.setPlainText(json.dumps(from_controls(), indent=2, ensure_ascii=False))
            else:
                current = settings(json.loads(advanced.toPlainText()))
                for key, box in fields.items():
                    box.setValue(current[key])
                name.setText(current["filename_contains"])
                combos.setCurrentIndex(combos.findData(current["thermal_model"]))
                fixed.setChecked(current["background_fixed"])
            previous_tab[0] = index
        except Exception as exc:
            QMessageBox.warning(dialog, "Configuration", str(exc))

    tabs.currentChanged.connect(sync_tabs)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
    )
    layout.addWidget(buttons)
    buttons.rejected.connect(dialog.reject)
    output = {}

    def save():
        try:
            current = settings(
                from_controls() if tabs.currentIndex() == 0 else json.loads(advanced.toPlainText())
            )
            validate(current)
            thermal_position(current["temperature_K"], current)
            thermal_position(current["reference_temperature_K"], current)
            output.update(current)
            dialog.accept()
        except Exception as exc:
            QMessageBox.warning(dialog, "Invalid configuration", str(exc))

    buttons.accepted.connect(save)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        context.data.clear()
        context.data.update(output)


def current_result(context, curve):
    """Derive output from the current fit, retaining this acquisition's temperature."""
    from curvemole.core.data import CurveState

    meta = copy.deepcopy(curve.metadata.get("ruby_monitor", {}))
    if not meta:
        return None
    meta.update(pressure_GPa=None, thermal_shift_nm=None, pressure_std_GPa=None, R1_std_nm=None)
    if curve.state != CurveState.FITTED:
        meta["pressure_error"] = "Fit is not current. Adjust masks/parameters, then run Fit."
        return meta
    model = context.project.models.get(curve.id)
    peaks = [c for c in model.components if c.enabled and c.function_id == "pseudo_voigt"] if model else []
    if len(peaks) != 2:
        meta["pressure_error"] = "The current model must contain exactly two enabled pseudo-Voigt peaks."
        return meta
    try:
        values = context.project.resolved_parameter_values()
        peaks.sort(key=lambda c: values[model.parameter_path(curve.id, c.id, "center")])
        for peak, label in zip(peaks, ("R2", "R1"), strict=True):
            meta[label + "_nm"] = values[model.parameter_path(curve.id, peak.id, "center")]
            meta["FWHM_" + label + "_nm"] = values[model.parameter_path(curve.id, peak.id, "fwhm")]
        s = settings(meta.get("settings"))
        meta["temperature_K"] = s["temperature_K"]
        if meta["R1_nm"] <= meta["R2_nm"]:
            raise ValueError("Invalid R2/R1 peak order.")
        P, shift = pressure(meta["R1_nm"], s)
        meta.update(pressure_GPa=P, thermal_shift_nm=shift, pressure_error=None)
        meta.update(pressure_uncertainty(meta["R1_nm"], peaks[1].parameters["center"], s))
        meta.pop("error", None)
        warnings = []
        if P < 0:
            warnings.append("Negative pressure: check the reference and temperature.")
        if P > 80:
            warnings.append("Above 80 GPa: extrapolating the Mao–Xu–Bell 1986 pressure scale.")
        if P > 20 and abs(s["temperature_K"] - s["reference_temperature_K"]) > 1:
            warnings.append("Above 20 GPa: pressure/temperature cross terms may matter.")
        if meta["R1_nm"] - meta["R2_nm"] < max(meta["FWHM_R1_nm"], meta["FWHM_R2_nm"]):
            warnings.append("Peaks strongly overlap: review their identification.")
        for peak in peaks:
            for key in ("center", "fwhm"):
                param = peak.parameters[key]
                value = values[model.parameter_path(curve.id, peak.id, key)]
                span = param.maximum - param.minimum
                if np.isfinite(span) and min(value - param.minimum, param.maximum - value) < span * 1e-4:
                    warnings.append(f"{peak.name}: {key} is at its bound; review the fit.")
        meta["warnings"] = warnings
        meta["result_source"] = "Current model; acquisition-specific temperature and calibration"
    except (ValueError, KeyError) as exc:
        meta["pressure_error"] = str(exc)
    return meta


def monitor_panel(context):
    """Nonmodal controls; services never supply the live window/project."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QCheckBox,
        QDoubleSpinBox,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    if getattr(context, "services", None) is None:
        raise ValueError("Update CurveMole to a version with plugin panel services. See README.")
    services = context.services

    class MonitorPanel(QWidget):
        def __init__(self):
            super().__init__()
            self.project_id = context.project.id
            self.setMinimumWidth(300)
            layout = QVBoxLayout(self)
            form = QFormLayout()
            self.temperature = QDoubleSpinBox()
            self.temperature.setObjectName("sample_temperature")
            self.temperature.setRange(15, 600)
            self.temperature.setDecimals(3)
            self.temperature.setSuffix(" K")
            self.folder = QLineEdit()
            browse = QPushButton("Choose folder…")
            def choose():
                path = QFileDialog.getExistingDirectory(self, "Choose acquisition folder", self.folder.text())
                if path:
                    self.folder.setText(path)
            browse.clicked.connect(choose)
            row = QHBoxLayout()
            row.addWidget(self.folder)
            row.addWidget(browse)
            form.addRow("Acquisition folder", row)
            self.contains = QLineEdit()
            form.addRow("Filename contains", self.contains)
            form.insertRow(0, "Sample temperature (K)", self.temperature)
            self.load_settings(context)
            self.temperature.editingFinished.connect(lambda: self.guard(self.save))
            layout.addLayout(form)
            self.apply_selected = QCheckBox("Also apply temperature/calibration to selected spectra")
            layout.addWidget(self.apply_selected)
            apply = QPushButton("Apply temperature")
            apply.setObjectName("apply_temperature")
            apply.clicked.connect(lambda: self.guard(self.save))
            layout.addWidget(apply)
            note = QLabel("Default: room temperature, 296 K (22.85 °C). Temperature is for NEW acquisitions. Existing spectra keep their own temperature unless selected above. Pressure is calculated, not entered.")
            note.setWordWrap(True)
            layout.addWidget(note)
            self.existing = QCheckBox("Also import existing matching files")
            self.follow = QCheckBox("Follow newest spectrum")
            self.follow.setChecked(True)
            self.follow.toggled.connect(lambda checked: self.guard(lambda: services.set_follow(checked)))
            layout.addWidget(self.existing)
            layout.addWidget(self.follow)
            buttons = QHBoxLayout()
            self.start = QPushButton("Start")
            self.start.setObjectName("start_monitor")
            self.stop = QPushButton("Stop")
            self.stop.setObjectName("stop_monitor")
            self.start.clicked.connect(lambda: self.guard(self.start_monitor))
            self.stop.clicked.connect(lambda: self.guard(services.stop_monitor))
            advanced = QPushButton("Advanced settings / calibration…")
            advanced.clicked.connect(lambda: self.guard(self.configure))
            for button in (self.start, self.stop):
                buttons.addWidget(button)
            layout.insertLayout(0, buttons)
            layout.addWidget(advanced)
            self.status = QLabel()
            self.status.setWordWrap(True)
            self.result = QLabel()
            self.result.setObjectName("current_pressure")
            self.result.setWordWrap(True)
            layout.insertWidget(0, self.result)
            layout.insertWidget(0, self.status)
            error_note = QLabel("± is 1σ from the fit only. Temperature/calibration uncertainties are excluded; a fixed background is treated as exact.")
            error_note.setWordWrap(True)
            layout.addWidget(error_note)
            edit_mask = QPushButton("Edit fit mask of selected spectra")
            edit_mask.clicked.connect(lambda: self.guard(self.edit_mask))
            layout.addWidget(edit_mask)
            help_text = QLabel("Manual editing: uncheck Follow newest spectrum, select a spectrum, adjust its masks and model in CurveMole, then run Fit. Pressure below updates from that fit. Monitoring continues. Closing this panel keeps monitoring active; use Stop to end it.")
            help_text.setWordWrap(True)
            layout.addWidget(help_text)
            self.timer = QTimer(self)
            self.timer.setInterval(1000)
            self.timer.timeout.connect(self.refresh)
            self.timer.start()
            self.refresh()

        def guard(self, callback):
            try:
                callback()
                self.refresh()
            except Exception as exc:
                QMessageBox.warning(self, "Ruby fluorescence monitor", str(exc))

        def load_settings(self, snapshot):
            s = settings(snapshot.data)
            self.temperature.setValue(s["temperature_K"])
            self.contains.setText(s["filename_contains"])
            self.folder.setText(snapshot.data.get("monitor_folder", ""))

        def save(self):
            snapshot = services.snapshot()
            s = settings(snapshot.data)
            s.update(temperature_K=self.temperature.value(),
                     filename_contains=self.contains.text().strip(), monitor_folder=self.folder.text())
            validate(s)
            thermal_position(s["temperature_K"], s)
            thermal_position(s["reference_temperature_K"], s)
            updates = {}
            if self.apply_selected.isChecked():
                for curve in snapshot.project.curves:
                    if curve.id in snapshot.selected_curve_ids and "ruby_monitor" in curve.metadata:
                        meta = copy.deepcopy(curve.metadata["ruby_monitor"])
                        meta["settings"] = copy.deepcopy(s)
                        curve.metadata["ruby_monitor"] = meta
                        updates[curve.id] = current_result(snapshot, curve)
            if self.apply_selected.isChecked() and not updates:
                raise ValueError("Select at least one imported ruby spectrum first.")
            services.save_settings(s, metadata_key="ruby_monitor", curve_metadata=updates)

        def edit_mask(self):
            snapshot = services.snapshot()
            ids = snapshot.selected_curve_ids or (snapshot.active_curve_id,)
            masks = {c.id: "Ruby local fit region" for c in snapshot.project.curves
                     if c.id in ids and "ruby_monitor" in c.metadata and "Ruby local fit region" in c.masks}
            if not masks:
                raise ValueError("Select an imported ruby spectrum first.")
            services.select_masks(masks)
            services.set_follow(False)
            self.follow.setChecked(False)

        def start_monitor(self):
            self.save()
            services.start_monitor(self.folder.text(), self.contains.text().strip(),
                                   include_existing=self.existing.isChecked(), follow=self.follow.isChecked())

        def configure(self):
            snapshot = services.snapshot()
            configure(snapshot)
            services.save_settings(snapshot.data)
            self.load_settings(snapshot)

        def refresh(self):
            try:
                status = services.monitor_status()
                snapshot = services.snapshot()
                if snapshot.project.id != self.project_id:
                    self.project_id = snapshot.project.id
                    self.load_settings(snapshot)
                running = status["running"]
                self.status.setText("Running — acquisition and automatic fit active" if running else
                                    "Another automatic import is running" if status["other_running"] else
                                    "Stopping — waiting for the worker" if status["busy"] else "Stopped")
                self.start.setEnabled(not running and not status["busy"] and not status["other_running"])
                self.stop.setEnabled(running)
                for widget in (self.folder, self.contains, self.existing):
                    widget.setEnabled(not running)
                if running:
                    self.folder.setText(status["folder"])
                    self.contains.setText(status["contains"])
                    self.follow.blockSignals(True)
                    self.follow.setChecked(status["follow"])
                    self.follow.blockSignals(False)
                curve = next((c for c in snapshot.project.curves if c.id == snapshot.active_curve_id), None)
                meta = current_result(snapshot, curve) if curve else None
                if not meta:
                    self.result.setText("Select an imported ruby spectrum to see its pressure.")
                elif meta.get("pressure_GPa") is None:
                    self.result.setText(f"{curve.name}: {meta.get('pressure_error', meta.get('error', 'No pressure'))}")
                else:
                    self.result.setText(f"{curve.name}\nR1: {meta['R1_nm']:.6f} nm | Temperature: {meta['temperature_K']:.3f} K\n{pressure_text(meta)}\n" + "\n".join(meta.get("warnings", [])))
            except Exception as exc:
                self.status.setText(str(exc))
                self.start.setEnabled(False)
                self.stop.setEnabled(False)
                self.timer.stop()

    return MonitorPanel()


def report(context):
    results = [
        {"spectrum": c.name, **current_result(context, c)}
        for c in context.project.curves
        if "ruby_monitor" in c.metadata
    ]
    return (
        json.dumps(results, indent=2, ensure_ascii=False, allow_nan=False)
        if results
        else "No ruby analysis is available."
    )


def export(context):
    columns = [
        "spectrum",
        "R1_nm",
        "R2_nm",
        "FWHM_R1_nm",
        "FWHM_R2_nm",
        "temperature_K",
        "pressure_GPa",
        "pressure_std_GPa",
        "R1_std_nm",
        "uncertainty_note",
        "thermal_model",
        "pressure_error",
        "warnings",
    ]
    with Path(context.path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for curve in context.project.curves:
            meta = current_result(context, curve)
            if not meta:
                continue
            row = {key: meta.get(key) for key in columns}
            row.update(
                spectrum=curve.name,
                thermal_model=meta.get("settings", {}).get("thermal_model"),
                pressure_error=meta.get("pressure_error", meta.get("error")),
                warnings="; ".join(meta.get("warnings", [])),
            )
            writer.writerow(row)


def register(api):
    from curvemole.core.extensions import KINDS

    if "import_processors" not in KINDS:
        raise RuntimeError(
            "Requires CurveMole with File > Automatic folder import. See the plugin README."
        )
    api.add("panels", "monitor", "Ruby fluorescence: monitor — temperature / Start / Stop", monitor_panel, auto_show=True)
    api.add("actions", "configure", "Ruby fluorescence: temperature and settings", configure)
    api.add("analysis", "report", "Ruby fluorescence: results and references", report)
    api.add("exporters", "csv", "Ruby fluorescence: export pressures as CSV", export)
    api.add(
        "import_processors",
        "automatic",
        "Ruby fluorescence: doublet → pressure",
        process,
        description="Two pseudo-Voigt peaks with free FWHM and fixed eta; background and temperature-corrected Mao–Xu–Bell pressure.",
    )
