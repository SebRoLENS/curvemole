"""Ruby fluorescence pressure monitor. Literature references in README.md.

Widths are FREE; pseudo-Voigt mixing eta is FIXED (default 0.5).
No spectrum is ever used to infer a zero-pressure reference or a temperature.
"""

from __future__ import annotations

import copy
import csv
import hashlib
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
    for parameter in bg.parameters.values():
        parameter.fixed = False
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
            if meta["pressure_GPa"] is not None:
                recalculate_curve(context, curve)
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


def configure_dialog(context):
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
        return True
    return False


def configure(context):
    """Configure the active spectrum and defaults for subsequent acquisitions."""
    context.settings_only = True
    original = copy.deepcopy(context.data)
    curve = next((c for c in context.project.curves
                  if c.id == context.active_curve_id and "ruby_monitor" in c.metadata), None)
    if curve:
        context.data.update(settings(curve.metadata["ruby_monitor"].get("settings")))
    if not configure_dialog(context):
        context.data.clear()
        context.data.update(original)
        return
    updates = {}
    if curve:
        curve.metadata["ruby_monitor"]["settings"] = settings(context.data)
        updates[curve.id] = curve.metadata["ruby_monitor"]
    if getattr(context, "services", None):
        context.services.save_settings(context.data, metadata_key="ruby_monitor", curve_metadata=updates)
        if curve:
            context.services.set_follow(False)


def calculate_result(context, curve):
    """Derive output from the current fit, retaining this acquisition's temperature."""
    from curvemole.core.data import CurveState

    meta = copy.deepcopy(curve.metadata.get("ruby_monitor", {}))
    meta.pop("calculated_result", None)
    meta.pop("calculation_fingerprint", None)
    if not meta:
        return None
    meta.update(pressure_GPa=None, thermal_shift_nm=None, pressure_std_GPa=None, R1_std_nm=None)
    if curve.state == CurveState.RUNNING:
        meta["pressure_error"] = "Wait for the fit to finish."
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
        if curve.state != CurveState.FITTED:
            meta.update(pressure_std_GPa=None, R1_std_nm=None,
                        uncertainty_note="Current model has not been refitted; fit uncertainty unavailable.")
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


def calculation_fingerprint(context, curve):
    """Track all inputs, so reviewing spectra never silently recalculates pressure."""
    model = context.project.models.get(curve.id)
    values = context.project.resolved_parameter_values()
    payload = {
        "model": model.to_dict() if model else None,
        "resolved": {k: values[k] for k in model.parameter_map(curve.id)} if model else {},
        "settings": settings(curve.metadata["ruby_monitor"].get("settings")),
        "state": str(curve.state), "fit_ranges": curve.fit_ranges,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode())
    for array in (curve.x, curve.y, curve.effective_mask, curve.weights, curve.sigma_y):
        if array is not None:
            digest.update(np.asarray(array).tobytes())
    return digest.hexdigest()


def recalculate_curve(context, curve):
    result = calculate_result(context, curve)
    if not result or result.get("pressure_GPa") is None:
        raise ValueError((result or {}).get("pressure_error", "No ruby pressure is available."))
    meta = curve.metadata["ruby_monitor"]
    meta["calculated_result"] = result
    meta["calculation_fingerprint"] = calculation_fingerprint(context, curve)
    return result


def current_result(context, curve):
    """Return the last explicit calculation and its freshness, without changing it."""
    meta = curve.metadata.get("ruby_monitor")
    if not meta:
        return None
    result = copy.deepcopy(meta.get("calculated_result", meta))
    result.pop("calculated_result", None)
    result.pop("calculation_fingerprint", None)
    try:
        stale = meta.get("calculation_fingerprint") != calculation_fingerprint(context, curve)
    except (ValueError, KeyError):
        stale = True
    result["needs_recalculation"] = stale
    result["pending_temperature_K"] = settings(meta.get("settings"))["temperature_K"]
    return result


def monitor_panel(context):
    """Per-spectrum controls; acquisition keeps running independently."""
    from PySide6.QtCore import Qt, QTimer
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
        raise ValueError("Update CurveMole to a version with plugin panel services.")
    services = context.services

    class MonitorPanel(QWidget):
        def __init__(self):
            super().__init__()
            self.project_id = context.project.id
            self.curve_id = None
            self.loaded_settings = None
            self.show_first = False
            self.temperature_pending = False
            self.setMinimumWidth(300)
            layout = QVBoxLayout(self)
            layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            self.spectrum = QLabel()
            self.spectrum.setTextFormat(Qt.TextFormat.PlainText)
            self.spectrum.setWordWrap(True)
            layout.addWidget(self.spectrum)
            self.result = QLabel()
            self.result.setObjectName("current_pressure")
            self.result.setWordWrap(True)
            layout.addWidget(self.result)
            self.warning = QLabel()
            self.warning.setWordWrap(True)
            layout.addWidget(self.warning)
            self.temperature = QDoubleSpinBox()
            self.temperature.setObjectName("sample_temperature")
            self.temperature.setRange(15, 600)
            self.temperature.setDecimals(3)
            self.temperature.setSuffix(" K")
            self.temperature.setKeyboardTracking(False)
            form = QFormLayout()
            form.addRow("Sample temperature", self.temperature)
            layout.addLayout(form)
            self.recalculate = QPushButton("Recalculate")
            self.recalculate.setObjectName("recalculate_pressure")
            self.recalculate.clicked.connect(lambda: self.guard(self.recalculate_pressure))
            layout.addWidget(self.recalculate)
            advanced = QPushButton("Calibration and fit settings…")
            advanced.clicked.connect(lambda: self.guard(self.configure))
            layout.addWidget(advanced)
            self.details = QLabel()
            self.details.setWordWrap(True)
            layout.addWidget(self.details)
            self.status = QLabel()
            self.status.setWordWrap(True)
            layout.addWidget(self.status)
            self.folder = QLineEdit(context.data.get("monitor_folder", ""))
            self.contains = QLineEdit(settings(context.data)["filename_contains"])
            browse = QPushButton("Choose folder…")
            def choose():
                path = QFileDialog.getExistingDirectory(self, "Choose acquisition folder", self.folder.text())
                if path:
                    self.folder.setText(path)
            browse.clicked.connect(choose)
            row = QHBoxLayout()
            row.addWidget(self.folder)
            row.addWidget(browse)
            acquisition = QFormLayout()
            acquisition.addRow("Acquisition folder", row)
            acquisition.addRow("Filename contains", self.contains)
            layout.addLayout(acquisition)
            self.existing = QCheckBox("Also import existing matching files")
            self.follow = QCheckBox("Show new spectra automatically")
            self.follow.setChecked(False)
            self.follow.toggled.connect(lambda checked: self.guard(lambda: services.set_follow(checked)))
            layout.addWidget(self.existing)
            layout.addWidget(self.follow)
            row = QHBoxLayout()
            self.start = QPushButton("Start")
            self.stop = QPushButton("Stop")
            self.start.clicked.connect(lambda: self.guard(self.start_monitor))
            self.stop.clicked.connect(lambda: self.guard(services.stop_monitor))
            row.addWidget(self.start)
            row.addWidget(self.stop)
            layout.addLayout(row)
            help_text = QLabel("Edit this spectrum, run Fit if needed, then Recalculate. Monitoring continues. Each spectrum keeps its edits. ± is 1σ fit precision; temperature and calibration errors are excluded.")
            help_text.setWordWrap(True)
            layout.addWidget(help_text)
            self.temperature.valueChanged.connect(lambda *_: self.guard(self.save))
            self.temperature.editingFinished.connect(lambda: self.guard(self.save))
            self.temperature.lineEdit().textEdited.connect(self.temperature_edited)
            self.timer = QTimer(self)
            self.timer.setInterval(300)
            self.timer.timeout.connect(self.refresh)
            self.timer.start()
            self.refresh()

        def guard(self, callback):
            try:
                callback()
                self.refresh()
            except Exception as exc:
                QMessageBox.warning(self, "Ruby fluorescence monitor", str(exc))

        def displayed_curve(self, snapshot):
            return next((c for c in snapshot.project.curves if c.id == self.curve_id), None)

        def temperature_edited(self, _text):
            self.temperature_pending = True
            self.refresh()

        def save(self):
            snapshot = services.snapshot()
            if snapshot.project.id != self.project_id:
                self.refresh()
                return
            curve = self.displayed_curve(snapshot)
            data = copy.deepcopy(snapshot.data)
            s = settings(curve.metadata["ruby_monitor"].get("settings") if curve else data)
            s["temperature_K"] = self.temperature.value()
            validate(s)
            data.update(s, filename_contains=self.contains.text().strip(), monitor_folder=self.folder.text())
            updates = {}
            if curve:
                meta = curve.metadata["ruby_monitor"]
                if settings(meta.get("settings")) != s:
                    meta["settings"] = copy.deepcopy(s)
                    updates[curve.id] = meta
            if data != snapshot.data or updates:
                services.save_settings(data, metadata_key="ruby_monitor", curve_metadata=updates)
            self.loaded_settings = s
            self.temperature_pending = False
            if updates:
                services.set_follow(False)

        def recalculate_pressure(self):
            # Commit any spin-box text before reading this spectrum's settings.
            self.temperature.interpretText()
            self.save()
            snapshot = services.snapshot()
            curve = self.displayed_curve(snapshot)
            if curve is None:
                raise ValueError("Select a ruby spectrum first.")
            recalculate_curve(snapshot, curve)
            services.save_settings(snapshot.data, metadata_key="ruby_monitor",
                                   curve_metadata={curve.id: curve.metadata["ruby_monitor"]})

        def start_monitor(self):
            self.temperature.interpretText()
            self.save()
            self.show_first = services.snapshot().active_curve_id is None and not self.follow.isChecked()
            services.start_monitor(self.folder.text(), self.contains.text().strip(),
                                   include_existing=self.existing.isChecked(),
                                   follow=self.follow.isChecked() or self.show_first)

        def configure(self):
            snapshot = services.snapshot()
            configure(snapshot)
            self.loaded_settings = None

        def refresh(self):
            try:
                status = services.monitor_status()
                snapshot = services.snapshot()
                if snapshot.project.id != self.project_id:
                    self.project_id = snapshot.project.id
                    self.curve_id = None
                    self.loaded_settings = None
                    self.folder.setText(snapshot.data.get("monitor_folder", ""))
                    self.contains.setText(settings(snapshot.data)["filename_contains"])
                curve = next((c for c in snapshot.project.curves
                              if c.id == snapshot.active_curve_id and "ruby_monitor" in c.metadata), None)
                if curve and self.show_first:
                    services.set_follow(False)
                    self.show_first = False
                    status["follow"] = False
                s = settings(curve.metadata["ruby_monitor"].get("settings") if curve else snapshot.data)
                curve_id = curve.id if curve else None
                if self.curve_id != curve_id or self.loaded_settings != s:
                    self.curve_id = curve_id
                    self.temperature_pending = False
                    self.loaded_settings = copy.deepcopy(s)
                    self.temperature.blockSignals(True)
                    self.temperature.setValue(s["temperature_K"])
                    self.temperature.blockSignals(False)
                running = status["running"]
                self.status.setText("Running — new spectra are fitted automatically" if running else
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
                self.recalculate.setEnabled(curve is not None)
                meta = current_result(snapshot, curve) if curve else None
                self.spectrum.setText(curve.name if curve else "No ruby spectrum selected")
                stale = bool(meta and (meta["needs_recalculation"] or self.temperature_pending))
                colour = "background:#fff0bf;color:#654000;" if stale else "background:#155e4b;color:#ffffff;"
                if not meta or meta.get("pressure_GPa") is None:
                    colour = "background:#e2e8f0;color:#334155;"
                self.result.setStyleSheet(colour + "font-size:20px;font-weight:bold;padding:10px;border-radius:5px;")
                self.warning.setText("⚠ Settings, fit or masks changed. Saved pressure needs recalculation." if stale else "")
                if meta and meta.get("pressure_GPa") is not None:
                    self.result.setText(pressure_text(meta))
                    self.details.setText(f"Last calculation: T = {meta['temperature_K']:.3f} K; R1 = {meta['R1_nm']:.6f} nm.\n" + "\n".join(meta.get("warnings", [])) + ("\n" + meta.get("uncertainty_note", "") if meta.get("pressure_std_GPa") is None else ""))
                else:
                    self.result.setText("Pressure unavailable")
                    self.details.setText((meta or {}).get("pressure_error") or (meta or {}).get("error") or "Select an imported ruby spectrum.")
            except Exception as exc:
                self.status.setText(str(exc))
                self.start.setEnabled(False)
                self.stop.setEnabled(False)

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
        "needs_recalculation",
        "pending_temperature_K",
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
