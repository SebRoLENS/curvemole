"""Ruby fluorescence pressure monitor. Literature references in README.md.

Widths are FREE; pseudo-Voigt mixing eta is FIXED (default 0.5).
No spectrum is ever used to infer a zero-pressure reference or a temperature.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, SimpleQueue

import numpy as np

OWNER = "org.curvemole.community.ruby_fluo_pressure_monitor"
INSTRUMENT_CALIBRATION_NOTE = "Pressure uncertainty excludes the instrument's wavelength calibration uncertainty."
BACKGROUND_REPLICATES = 500
BACKGROUND_SEED = 1729
PRESSURE_WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ruby-pressure")
PENDING_ACQUISITIONS = SimpleQueue()
DEFAULTS = {
    "filename_contains": "ruby",
    "temperature_K": 296.0,
    "reference_temperature_K": 296.0,
    "reference_nm": 694.281,
    "pressure_scale": "mao_1986",
    "A_GPa": 1904.0,
    "B": 7.665,
    "ruby2020_reference_nm": 694.25,
    "ruby2020_A_GPa": 1870.0,
    "ruby2020_B": 5.63,
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
    "full_pressure_uncertainty": False,
    "ragan_coefficients_cm1": [14423.0, 4.49e-2, -4.81e-4, 3.71e-7],
    "datchi_cold_plateau_nm": -0.887,
    "datchi_cold_coefficients_nm": [0.0, 0.00664, 6.76e-6, -2.33e-8],
    "datchi_hot_slope_nm_K": 0.00726,
    "datchi_hot_coefficients_nm": [0.0, 0.00746, -3.01e-6, 8.76e-9],
}
PRESSURE_SCALES = {
    "mao_1986": (
        "Mao–Xu–Bell (1986) — up to 80 GPa",
        "https://doi.org/10.1029/JB091iB05p04673",
    ),
    "ruby2020": (
        "IPPS Ruby2020 — room temperature, up to 150 GPa",
        "https://doi.org/10.1080/08957959.2020.1791107",
    ),
}
SCALE_ACCURACY = {
    "mao_1986": (5.0, 80.0, ("A_GPa", "B"), "https://journals.iucr.org/s/issues/2005/02/00/xg5001/index.html"),
    "ruby2020": (2.5, 150.0, ("ruby2020_A_GPa", "ruby2020_B"), PRESSURE_SCALES["ruby2020"][1]),
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


def uncertainty_settings(data=None):
    defaults = {
        "replicates": BACKGROUND_REPLICATES,
        "block_length": 0,
        "seed": BACKGROUND_SEED,
        "min_success_percent": 90,
        "refit_max_evaluations": 0,
    }
    if data is not None and not isinstance(data, dict):
        raise ValueError("Uncertainty settings must be a mapping.")
    values = {**defaults, **(data or {})}
    limits = {"replicates": (2, 100_000), "block_length": (0, 100_000),
              "seed": (0, 2**31 - 1), "min_success_percent": (1, 100),
              "refit_max_evaluations": (0, 1_000_000)}
    if set(values) != set(defaults) or any(
        type(values[key]) is not int or not low <= values[key] <= high
        for key, (low, high) in limits.items()
    ):
        raise ValueError("Invalid Ruby uncertainty settings.")
    return values


def settings(data=None):
    result = copy.deepcopy(DEFAULTS)
    result.update(data or {})
    result["uncertainty"] = uncertainty_settings(result.get("uncertainty"))
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
    if s["pressure_scale"] not in PRESSURE_SCALES:
        raise ValueError("Unknown pressure scale.")
    if not isinstance(s.get("full_pressure_uncertainty", False), bool):
        raise ValueError("Full pressure uncertainty must be on or off.")
    if not 0 <= s["eta"] <= 1 or not 0 < s["width_min_nm"] < s["width_max_nm"]:
        raise ValueError("Require 0 ≤ eta ≤ 1 and positive, ordered width limits.")
    if (
        not s["search_min_nm"] < s["search_max_nm"]
        or not 0 < s["separation_min_nm"] < s["separation_max_nm"]
    ):
        raise ValueError("Invalid search or peak-separation range.")
    if any(
        s[key] <= 0
        for key in (
            "A_GPa",
            "B",
            "reference_nm",
            "ruby2020_A_GPa",
            "ruby2020_B",
            "ruby2020_reference_nm",
        )
    ):
        raise ValueError("Pressure-scale coefficients and reference wavelengths must be positive.")
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
    """Subtract thermal wavelength shift, then apply the selected pressure scale.

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
    if s["pressure_scale"] == "ruby2020":
        relative_shift = corrected / s["ruby2020_reference_nm"] - 1.0
        value = s["ruby2020_A_GPa"] * relative_shift * (
            1.0 + s["ruby2020_B"] * relative_shift
        )
    else:
        value = s["A_GPa"] / s["B"] * np.expm1(
            s["B"] * np.log(corrected / s["reference_nm"])
        )
    return float(value), shift


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
    corrected = center_nm - shift
    if s["pressure_scale"] == "ruby2020":
        x = corrected / s["ruby2020_reference_nm"] - 1.0
        sensitivity = (
            s["ruby2020_A_GPa"]
            / s["ruby2020_reference_nm"]
            * (1.0 + 2.0 * s["ruby2020_B"] * x)
        )
    else:
        ratio = corrected / s["reference_nm"]
        sensitivity = s["A_GPa"] / s["reference_nm"] * ratio ** (s["B"] - 1)
    output.update(R1_std_nm=float(error), pressure_std_GPa=float(abs(sensitivity) * error))
    return output


def pressure_scale_metadata(value, s):
    """Describe calibration uncertainty separately from fit covariance."""
    output = {
        "pressure_scale": s["pressure_scale"],
        "pressure_reference": PRESSURE_SCALES[s["pressure_scale"]][1],
        "scale_uncertainty_percent": None,
        "scale_uncertainty_GPa": None,
        "scale_uncertainty_note": None,
    }
    if (s["pressure_scale"] == "ruby2020" and 0 <= value <= 150
            and all(s[key] == DEFAULTS[key] for key in SCALE_ACCURACY["ruby2020"][2])):
        output.update(
            scale_uncertainty_percent=2.5,
            scale_uncertainty_GPa=abs(float(value)) * 0.025,
            scale_uncertainty_note=(
                "Ruby2020 reports a maximum pressure-scale uncertainty of ±2.5% "
                "from 0 to 150 GPa; this is not a 1σ fit uncertainty."
            ),
        )
    return output


def pressure_text(meta):
    value = meta["pressure_GPa"]
    error = meta.get("pressure_std_GPa")
    total = meta.get("pressure_combined_std_GPa")
    if meta.get("uncertainty_pending"):
        text = f"Pressure: {value:.6g} ± ? GPa (calculating uncertainty…)"
    elif total is not None:
        text = f"Pressure: {value:.6g} ± {total:.2g} GPa (combined 1σ)"
        if error is not None:
            text += f"\nFit only: {error:.2g} GPa (1σ)"
    elif error is None:
        text = f"Pressure: {value:.6g} GPa (fit uncertainty unavailable)"
    else:
        text = f"Pressure: {value:.6g} ± {error:.2g} GPa (1σ, fit only)"
    if total is None and not meta.get("uncertainty_pending") and meta.get("settings", {}).get("full_pressure_uncertainty"):
        text += "\nCombined uncertainty unavailable"
    if meta.get("scale_uncertainty_percent") is not None:
        text += f"\nScale: ±{meta['scale_uncertainty_percent']:g}% maximum"
    return text


def pressure_warnings(value, s):
    warnings = []
    if value < 0:
        warnings.append("Negative pressure: check the reference and temperature.")
    limit = 150.0 if s["pressure_scale"] == "ruby2020" else 80.0
    if value > limit:
        label = "IPPS Ruby2020" if s["pressure_scale"] == "ruby2020" else "Mao–Xu–Bell 1986"
        warnings.append(f"Above {limit:g} GPa: extrapolating the {label} pressure scale.")
    if value > 20 and abs(s["temperature_K"] - s["reference_temperature_K"]) > 1:
        warnings.append(
            "Above 20 GPa: pressure/temperature shift separability is not guaranteed; cross terms may matter."
        )
    return warnings


def background_pressure_bootstrap(curve, model, r1, meta, fit_settings, cancellation):
    """Resample the first-stage line and refit peaks at fixed observed band intensities."""
    from curvemole.core.diagnostics import contiguous_residual_segments
    from curvemole.core.errors import CurveMoleError, FitCancelled
    from curvemole.core.expressions import SafeExpression
    from curvemole.core.fitting import Fitter
    from curvemole.core.uncertainty import _sample_residual_blocks

    backgrounds = [component for component in model.components if component.enabled and component.is_background]
    if (len(backgrounds) != 1 or backgrounds[0].function_id != "linear"
            or any(component.enabled and component.operator != "add" for component in model.components)):
        raise ValueError("Background bootstrap requires the additive ruby model with a single linear background.")
    background = backgrounds[0]
    if any(reference.split(".", 1)[0] != curve.id
           for parameter in model.parameter_map(curve.id).values() if parameter.link
           for reference in SafeExpression.compile(parameter.link).references):
        raise ValueError("Background bootstrap requires a fit without links to other spectra.")
    fixed = [name for name in ("intercept", "slope")
             if background.parameters[name].fixed and not background.parameters[name].link]
    if not fixed:
        return {"pressure_background_std_GPa": 0.0, "background_bootstrap_note":
                "The line is fitted with the peaks, so its uncertainty is already included in fit covariance."}
    if curve.has_correlated_y_errors or (fit_settings.use_data_errors and curve.current_error_y_minus is not None):
        raise ValueError("Background bootstrap requires working data without unknown preprocessing correlations "
                         "and symmetric Y errors if weighted.")

    search = meta.get("background_search_nm")
    if search is None:
        # Older acquisitions recorded the band geometry and settings, but no dedicated search limits.
        acquisition = settings(meta.get("calculated_result", meta).get("settings"))
        search = [acquisition["search_min_nm"], acquisition["search_max_nm"]]
    intervals = meta.get("background_excluded_intervals_nm")
    region = meta.get("fit_region_nm")
    if not intervals or not region:
        raise ValueError("This acquisition has no recorded background region.")
    x = curve.x
    band = np.zeros(len(x), dtype=bool)
    for low, high in intervals:
        band |= (x >= low) & (x <= high)
    band &= (x >= region[0]) & (x <= region[1])
    side = copy.deepcopy(curve)
    mask_id = meta.get("local_fit_mask_id")
    for name, mask in list(side.masks.items()):
        if (mask_id and mask.id == mask_id) or (not mask_id and name == "Ruby local fit region"):
            del side.masks[name]
    side_rows = side.fit_arrays(use_data_errors=fit_settings.use_data_errors)[3]
    peak_rows = curve.fit_arrays(use_data_errors=fit_settings.use_data_errors)[3]
    eligible = ~band & (x >= search[0]) & (x <= search[1])
    eligible[peak_rows] = False
    rows = side_rows[eligible[side_rows]]
    if len(rows) < 8:
        raise ValueError("Fewer than eight usable background points outside the current peak fit.")
    xx, yy = x[rows], curve.y[rows]
    segments = contiguous_residual_segments(curve.row_indices[rows], xx)
    if max(segment.stop - segment.start for segment in segments) < 4:
        raise ValueError("There are too few contiguous background points for block resampling.")
    origin = float(np.mean(xx))
    precision = curve.residual_scale(yy, rows, use_data_errors=fit_settings.use_data_errors)
    if precision is None:
        precision = np.ones(len(rows))
    design = np.column_stack((np.ones(len(rows)), xx - origin)) * precision[:, None]
    coefficients, _, rank, _ = np.linalg.lstsq(design, yy * precision, rcond=None)
    if rank < 2:
        raise ValueError("The background line cannot be identified from its available points.")
    residual = yy * precision - design @ coefficients
    residual -= np.mean(residual)
    estimate_delta = np.linalg.pinv(design)
    s = settings(meta.get("settings"))
    config = s["uncertainty"]
    requested = config["replicates"]
    block = config["block_length"] or max(2, round(len(rows) ** (1 / 3)))
    segment_lengths = [min(block, max(1, (segment.stop - segment.start) // 2)) for segment in segments]
    rng = np.random.default_rng(config["seed"])
    fitter = Fitter(_compute_inference=False)
    trial_settings = copy.deepcopy(fit_settings)
    trial_settings.solver = "local"
    trial_settings.workers = 1
    if config["refit_max_evaluations"]:
        trial_settings.max_nfev = config["refit_max_evaluations"]
    trial_curve = copy.deepcopy(curve)
    pressures = []
    for _ in range(requested):
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        sample = np.concatenate([_sample_residual_blocks(rng, residual[segment], length, circular=False)
                                 for segment, length in zip(segments, segment_lengths, strict=True)])
        at_origin, slope = estimate_delta @ sample
        delta = {"intercept": at_origin - slope * origin, "slope": slope}
        trial_model = model.clone()
        line = trial_model.component(background.id)
        if any(not (p.minimum <= p.value + delta[name] <= p.maximum)
               for name in fixed for p in (line.parameters[name],)):
            continue
        for name in fixed:
            line.parameters[name].value += delta[name]
        try:
            result = fitter.fit_single(trial_curve, trial_model, trial_settings, cancellation=cancellation)
            if result.success:
                center = trial_model.component(r1.id).parameters["center"].value
                pressures.append(pressure(center, s)[0])
        except FitCancelled:
            raise
        except (CurveMoleError, ValueError):
            continue
    required = max(2, (requested * config["min_success_percent"] + 99) // 100)
    if len(pressures) < required:
        raise ValueError(f"Only {len(pressures)} of {requested} background bootstrap fits succeeded "
                         f"({required} required).")
    return {
        "pressure_background_std_GPa": float(np.std(pressures, ddof=1)),
        "background_bootstrap_completed": len(pressures),
        "background_bootstrap_requested": requested,
        "background_bootstrap_block_length": max(segment_lengths),
        "background_bootstrap_seed": config["seed"],
        "background_bootstrap_note": (
            "Contiguous blocks of background residuals were resampled. Peak intensities were held fixed "
            "during each replica to avoid counting peak-fit noise twice."
        ),
    }


def complete_pressure_uncertainty(context, curve, model, r1, meta, s, cancellation=None):
    from curvemole.core.data import CurveState
    from curvemole.core.errors import CurveMoleError, FitCancelled
    from curvemole.core.fitting import FitSettings

    percent, limit, coefficients, source = SCALE_ACCURACY[s["pressure_scale"]]
    value = meta["pressure_GPa"]
    meta["pressure_scale_uncertainty_source"] = source
    if 0 <= value <= limit and all(s[key] == DEFAULTS[key] for key in coefficients):
        meta["pressure_scale_std_GPa"] = value * percent / (100 * np.sqrt(3))
        meta["pressure_scale_component_note"] = (f"Published ±{percent:g}% accuracy treated as a rectangular "
                                                 "Type B bound to estimate a standard uncertainty.")
    else:
        meta["pressure_scale_component_note"] = (
            "Published accuracy applies within the pressure range and with the published scale coefficients."
        )
    if curve.state != CurveState.FITTED or meta.get("pressure_std_GPa") is None:
        meta["full_uncertainty_note"] = ("A current fit with an available R1 covariance is required. "
                                         "Check that R1 is free, refit the spectrum and press Recalculate.")
        return
    record = context.project.results.get("fit_by_curve", {}).get(curve.id, {}).get("plan", {})
    fit_settings = FitSettings(**record.get("settings", {"max_nfev": 2000}))
    if fit_settings.loss != "linear":
        meta["full_uncertainty_note"] = "Full uncertainty requires the linear least-squares loss for the background refit."
        return
    try:
        meta.update(background_pressure_bootstrap(curve, model, r1, meta, fit_settings, cancellation))
    except FitCancelled:
        raise
    except (CurveMoleError, ValueError, np.linalg.LinAlgError) as exc:
        meta["full_uncertainty_note"] = f"Background bootstrap unavailable. {exc}"
        return
    parts = [meta.get(key) for key in ("pressure_std_GPa", "pressure_background_std_GPa", "pressure_scale_std_GPa")]
    if all(part is not None and np.isfinite(part) for part in parts):
        meta["pressure_combined_std_GPa"] = float(np.hypot.reduce(parts))
        meta["full_uncertainty_note"] = ("Fit, background and pressure-scale standard uncertainties combined in "
                                         "quadrature assuming independent contributions. Temperature and reference "
                                         "wavelength uncertainties are excluded.")
    else:
        meta["full_uncertainty_note"] = "Combined uncertainty unavailable because a pressure-scale contribution is missing."


def analyse_curve(curve, s, cancellation=None):
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import find_peaks, peak_widths

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
        warnings.extend(pressure_warnings(P, s))
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
        "background_search_nm": [s["search_min_nm"], s["search_max_nm"]],
        "local_fit_mask_id": local.id,
        "instrument_calibration_note": INSTRUMENT_CALIBRATION_NOTE,
        "thermal_reference": THERMAL_MODELS[s["thermal_model"]][3],
    }
    if P is not None:
        metadata.update(pressure_uncertainty(centers_fit[1], components[1].parameters["center"], s))
        metadata.update(pressure_scale_metadata(P, s))
    curve.metadata["ruby_monitor"] = metadata
    return model, result, metadata


def process(context):
    """Headless callback for CurveMole's opt-in automatic import worker."""
    from curvemole.core.fit_records import plan_to_record
    from curvemole.core.fitting import FitPlan

    s = settings(context.data)
    set_destination = getattr(context, "set_series_destination", None)
    automatic = callable(set_destination)
    if automatic:
        for series in context.project.dataset.series:
            set_destination(series.id, name="Ruby fluorescence")
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
            context.project.results.setdefault("fit_by_curve", {})[curve.id] = {
                "plan": plan_to_record(FitPlan([curve.id], settings=result.settings)),
                "baseline": result,
            }
            context.project.results["last_fit"] = result
            if meta["pressure_GPa"] is not None:
                meta = recalculate_curve(context, curve, getattr(context, "cancellation", None),
                                         defer_uncertainty=automatic)
                if meta.get("uncertainty_pending"):
                    PENDING_ACQUISITIONS.put(curve.id)
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
    pressure_scale = QComboBox()
    for key, (label, _reference) in PRESSURE_SCALES.items():
        pressure_scale.addItem(label, key)
    pressure_scale.setCurrentIndex(pressure_scale.findData(s["pressure_scale"]))
    form.addRow("Pressure scale", pressure_scale)
    fields = {}
    labels = {
        "temperature_K": ("Sample temperature [K]", 15.0, 600.0, 3),
        "reference_temperature_K": ("Reference temperature [K]", 15.0, 600.0, 3),
        "reference_nm": ("R1 at ambient pressure [nm]", 600.0, 800.0, 6),
        "A_GPa": ("Mao–Xu–Bell: A [GPa]", 1.0, 10000.0, 4),
        "B": ("Mao–Xu–Bell: B", 0.01, 100.0, 6),
        "ruby2020_reference_nm": ("Ruby2020: R1 at ambient pressure [nm]", 600.0, 800.0, 6),
        "ruby2020_A_GPa": ("Ruby2020: A [GPa]", 1.0, 10000.0, 4),
        "ruby2020_B": ("Ruby2020: B", 0.01, 100.0, 6),
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
    full = QCheckBox("Calculate full pressure uncertainty")
    full.setChecked(s["full_pressure_uncertainty"])
    full.setToolTip("Combine fit, background and pressure-scale uncertainties. " + INSTRUMENT_CALIBRATION_NOTE)
    form.addRow(full)
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
            pressure_scale=pressure_scale.currentData(),
            background_fixed=fixed.isChecked(),
            full_pressure_uncertainty=full.isChecked(),
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
                pressure_scale.setCurrentIndex(pressure_scale.findData(current["pressure_scale"]))
                fixed.setChecked(current["background_fixed"])
                full.setChecked(current["full_pressure_uncertainty"])
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
        context.data.update(curve_settings(context, curve))
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


def curve_settings(context, curve):
    s = settings(curve.metadata["ruby_monitor"].get("settings"))
    if "uncertainty" in context.data:
        s["uncertainty"] = uncertainty_settings(context.data["uncertainty"])
    return s


def calculate_result(context, curve, cancellation=None, *, defer_uncertainty=False):
    """Derive output from the current fit, retaining this acquisition's temperature."""
    from curvemole.core.data import CurveState

    meta = copy.deepcopy(curve.metadata.get("ruby_monitor", {}))
    previous = meta.get("calculated_result", {})
    meta.pop("calculated_result", None)
    meta.pop("calculation_fingerprint", None)
    if not meta:
        return None
    meta["instrument_calibration_note"] = INSTRUMENT_CALIBRATION_NOTE
    if "background_search_nm" not in meta:
        acquisition = settings(previous.get("settings", meta.get("settings")))
        meta["background_search_nm"] = [acquisition["search_min_nm"], acquisition["search_max_nm"]]
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
        s = curve_settings(context, curve)
        meta["settings"] = s
        meta["temperature_K"] = s["temperature_K"]
        if meta["R1_nm"] <= meta["R2_nm"]:
            raise ValueError("Invalid R2/R1 peak order.")
        P, shift = pressure(meta["R1_nm"], s)
        meta.update(pressure_GPa=P, thermal_shift_nm=shift, pressure_error=None)
        meta.update(pressure_uncertainty(meta["R1_nm"], peaks[1].parameters["center"], s))
        meta.update(pressure_scale_metadata(P, s))
        if curve.state != CurveState.FITTED:
            meta.update(pressure_std_GPa=None, R1_std_nm=None,
                        uncertainty_note="Current model has not been refitted; fit uncertainty unavailable.")
        meta.pop("error", None)
        warnings = pressure_warnings(P, s)
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
        if s["full_pressure_uncertainty"]:
            if defer_uncertainty:
                meta["uncertainty_pending"] = True
            else:
                complete_pressure_uncertainty(context, curve, model, peaks[1], meta, s, cancellation)
        meta["result_source"] = "Current model; acquisition-specific temperature and calibration"
    except (ValueError, KeyError) as exc:
        meta["pressure_error"] = str(exc)
    return meta


def calculation_fingerprint(context, curve):
    """Track all inputs, so reviewing spectra never silently recalculates pressure."""
    model = context.project.models.get(curve.id)
    values = context.project.resolved_parameter_values()
    configuration = curve_settings(context, curve)
    if not configuration["full_pressure_uncertainty"]:
        configuration.pop("uncertainty")
        configuration.pop("full_pressure_uncertainty")  # Preserve fingerprints of existing fit-only calculations.
    payload = {
        "model": model.to_dict() if model else None,
        "resolved": {k: values[k] for k in model.parameter_map(curve.id)} if model else {},
        "settings": configuration,
        "state": str(curve.state), "fit_ranges": curve.fit_ranges,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode())
    digest.update(curve.content_hash.encode())
    return digest.hexdigest()


def recalculate_curve(context, curve, cancellation=None, *, defer_uncertainty=False):
    result = calculate_result(context, curve, cancellation, defer_uncertainty=defer_uncertainty)
    if not result or result.get("pressure_GPa") is None:
        raise ValueError((result or {}).get("pressure_error", "No ruby pressure is available."))
    meta = curve.metadata["ruby_monitor"]
    meta.setdefault("background_search_nm", result["background_search_nm"])
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
    result.setdefault("instrument_calibration_note", INSTRUMENT_CALIBRATION_NOTE)
    try:
        stale = meta.get("calculation_fingerprint") != calculation_fingerprint(context, curve)
    except (ValueError, KeyError):
        stale = True
    result["needs_recalculation"] = stale
    result["pending_temperature_K"] = settings(meta.get("settings"))["temperature_K"]
    return result


def uncertainty_dialog(parent, configuration):
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QSpinBox

    dialog = QDialog(parent)
    dialog.setWindowTitle("Ruby pressure uncertainty")
    form = QFormLayout(dialog)
    controls = {}
    for key, label, minimum, maximum, special in (
        ("replicates", "Bootstrap replicas", 2, 100_000, None),
        ("block_length", "Block length (samples)", 0, 100_000, "Automatic"),
        ("seed", "Random seed", 0, 2**31 - 1, None),
        ("min_success_percent", "Minimum successful replicas (%)", 1, 100, None),
        ("refit_max_evaluations", "Maximum evaluations per refit", 0, 1_000_000, "Use original fit limit"),
    ):
        control = QSpinBox()
        control.setObjectName(key)
        control.setRange(minimum, maximum)
        if special:
            control.setSpecialValueText(special)
        control.setValue(configuration[key])
        controls[key] = control
        form.addRow(label, control)
    note = QLabel("Block length is capped within each uninterrupted background region. "
                  "The combined 1σ uses the fit, background and published pressure-scale uncertainties. "
                  + INSTRUMENT_CALIBRATION_NOTE)
    note.setWordWrap(True)
    form.addRow(note)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return uncertainty_settings({key: control.value() for key, control in controls.items()})
    return None


def monitor_panel(context):
    """Per-spectrum controls; acquisition keeps running independently."""
    from PySide6.QtCore import QSignalBlocker, Qt, QTimer
    from PySide6.QtWidgets import (
        QApplication,
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
    project_id = context.project_id if hasattr(context, "project_id") else context.project.id
    initial_settings = copy.deepcopy(context.data)

    class MonitorPanel(QWidget):
        def __init__(self):
            super().__init__()
            self.project_id = project_id
            self.curve_id = None
            self.loaded_settings = None
            self.show_first = False
            self.temperature_pending = False
            self.pending_calculation = None
            self.waiting_acquisitions = {}
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
            self.full_uncertainty = QCheckBox("Calculate full pressure uncertainty")
            self.full_uncertainty.setObjectName("full_pressure_uncertainty")
            self.full_uncertainty.setToolTip("Apply to the selected ruby and to new acquisitions. "
                                             + INSTRUMENT_CALIBRATION_NOTE)
            self.full_uncertainty.toggled.connect(lambda checked: self.guard(lambda: self.toggle_uncertainty(checked)))
            uncertainty_row = QHBoxLayout()
            uncertainty_row.addWidget(self.full_uncertainty)
            self.configure_uncertainty_button = QPushButton("Configure uncertainty")
            self.configure_uncertainty_button.setObjectName("configure_uncertainty")
            self.configure_uncertainty_button.clicked.connect(lambda: self.guard(self.configure_uncertainty))
            uncertainty_row.addWidget(self.configure_uncertainty_button)
            layout.addLayout(uncertainty_row)
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
            self.folder = QLineEdit(initial_settings.get("monitor_folder", ""))
            self.contains = QLineEdit(settings(initial_settings)["filename_contains"])
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
            help_text = QLabel("Edit this spectrum, run Fit if needed, then Recalculate. Monitoring continues. "
                               + INSTRUMENT_CALIBRATION_NOTE)
            help_text.setWordWrap(True)
            layout.addWidget(help_text)
            self.temperature.valueChanged.connect(lambda *_: self.guard(self.save))
            self.temperature.editingFinished.connect(lambda: self.guard(self.save))
            self.temperature.lineEdit().textEdited.connect(self.temperature_edited)
            self.timer = QTimer(self)
            self.timer.setInterval(300)
            self.timer.timeout.connect(self.refresh)
            self.timer.start()
            self.calculation_timer = QTimer(self)
            self.calculation_timer.setInterval(150)
            self.calculation_timer.timeout.connect(self.poll_uncertainty_safely)
            self.calculation_timer.start()
            QApplication.instance().aboutToQuit.connect(self.cancel_uncertainty)
            self.refresh()

        def guard(self, callback):
            try:
                callback()
                self.refresh()
            except Exception as exc:
                QMessageBox.warning(self, "Ruby fluorescence monitor", str(exc))

        def displayed_curve(self, snapshot):
            return next((c for c in snapshot.project.curves if c.id == self.curve_id), None)

        def snapshot(self):
            # New hosts provide the active data + linked models without copying
            # historical fits/resampling matrices on every timer tick.
            if callable(getattr(services, "active_model_snapshot", None)):
                return services.active_model_snapshot()
            return services.snapshot()

        def showEvent(self, event):
            super().showEvent(event)
            self.timer.start()
            self.refresh()

        def hideEvent(self, event):
            self.timer.stop()
            super().hideEvent(event)

        def temperature_edited(self, _text):
            self.temperature_pending = True
            self.refresh()

        def save(self):
            snapshot = self.snapshot()
            if snapshot.project.id != self.project_id:
                self.refresh()
                return
            curve = self.displayed_curve(snapshot)
            data = copy.deepcopy(snapshot.data)
            s = curve_settings(snapshot, curve) if curve else settings(data)
            s["temperature_K"] = self.temperature.value()
            s["full_pressure_uncertainty"] = self.full_uncertainty.isChecked()
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
            self.recalculate_saved_pressure()

        def toggle_uncertainty(self, checked):
            snapshot = self.snapshot()
            if snapshot.project.id != self.project_id or snapshot.active_curve_id != self.curve_id:
                self.refresh()
                with QSignalBlocker(self.full_uncertainty):
                    self.full_uncertainty.setChecked(checked)
            self.temperature.interpretText()
            self.save()
            if self.curve_id is not None:
                self.recalculate_saved_pressure()

        def recalculate_saved_pressure(self):
            if self.pending_calculation is not None:
                return
            snapshot = self.snapshot()
            curve = self.displayed_curve(snapshot)
            if curve is None:
                raise ValueError("Select a ruby spectrum first.")
            if curve_settings(snapshot, curve)["full_pressure_uncertainty"]:
                snapshot = services.snapshot()  # Preserve the saved fit's weighting and fit limits.
                self.start_uncertainty(snapshot, snapshot.project.dataset.curve(curve.id))
                return
            recalculate_curve(snapshot, curve)
            services.save_settings(snapshot.data, metadata_key="ruby_monitor",
                                   curve_metadata={curve.id: curve.metadata["ruby_monitor"]})

        def configure_uncertainty(self):
            data = services.settings()
            configuration = uncertainty_dialog(self, uncertainty_settings(data.get("uncertainty")))
            if configuration is None or configuration == uncertainty_settings(data.get("uncertainty")):
                return
            data["uncertainty"] = configuration
            services.save_settings(data)
            self.loaded_settings = None
            self.refresh()
            if self.curve_id is not None and self.full_uncertainty.isChecked():
                if self.pending_calculation is None:
                    self.recalculate_saved_pressure()
                else:
                    self.waiting_acquisitions[self.curve_id] = None

        def start_uncertainty(self, snapshot, curve):
            from curvemole.core.fitting import CancellationToken

            preview = recalculate_curve(snapshot, curve, defer_uncertainty=True)
            fingerprint = curve.metadata["ruby_monitor"]["calculation_fingerprint"]
            cancellation = CancellationToken()
            future = PRESSURE_WORKER.submit(recalculate_curve, snapshot, curve, cancellation)
            self.pending_calculation = (future, snapshot.project_id, curve.id, fingerprint,
                                        curve, preview, cancellation)
            self.refresh()

        def cancel_uncertainty(self):
            if self.pending_calculation is not None:
                self.pending_calculation[-1].cancel()

        def poll_uncertainty_safely(self):
            try:
                self.poll_uncertainty()
            except (ValueError, KeyError) as exc:
                self.status.setText(str(exc))

        def poll_uncertainty(self):
            from curvemole.core.data import CurveState

            try:
                while True:
                    self.waiting_acquisitions[PENDING_ACQUISITIONS.get_nowait()] = None
            except Empty:
                pass
            if self.pending_calculation is not None:
                future, project_id, curve_id, fingerprint, curve, preview, cancellation = self.pending_calculation
                if services.active_spectrum_state()[0] != project_id:
                    cancellation.cancel()
                    self.pending_calculation = None
                elif future.done():
                    snapshot = services.snapshot()
                    project = snapshot.project
                    if any(item.state == CurveState.RUNNING for item in project.curves):
                        return  # Wait for the host to accept a metadata write.
                    self.pending_calculation = None
                    current = next((item for item in project.curves if item.id == curve_id), None)
                    if (current and not project.read_only and "ruby_monitor" in current.metadata
                            and calculation_fingerprint(snapshot, current) == fingerprint):
                        try:
                            future.result()
                            output = curve.metadata["ruby_monitor"]
                        except Exception as exc:
                            output = copy.deepcopy(current.metadata["ruby_monitor"])
                            failed = {key: value for key, value in preview.items() if key != "uncertainty_pending"}
                            failed["full_uncertainty_note"] = str(exc)
                            output.update(calculated_result=failed, calculation_fingerprint=fingerprint)
                        services.save_settings(snapshot.data, metadata_key="ruby_monitor",
                                               curve_metadata={curve_id: output})
                    self.refresh()
            if self.pending_calculation is not None or not self.waiting_acquisitions:
                return
            if services.monitor_status()["busy"]:
                return  # The acquisition must be committed before taking its fit snapshot.
            snapshot = services.snapshot()
            curves = {curve.id: curve for curve in snapshot.project.curves}
            for curve_id in tuple(self.waiting_acquisitions):
                self.waiting_acquisitions.pop(curve_id)
                curve = curves.get(curve_id)
                if (curve is not None and "ruby_monitor" in curve.metadata and not snapshot.project.read_only
                        and curve.state != CurveState.RUNNING
                        and curve_settings(snapshot, curve)["full_pressure_uncertainty"]):
                    self.start_uncertainty(snapshot, curve)
                    break

        def start_monitor(self):
            self.temperature.interpretText()
            self.save()
            self.show_first = self.snapshot().active_curve_id is None and not self.follow.isChecked()
            services.start_monitor(self.folder.text(), self.contains.text().strip(),
                                   include_existing=self.existing.isChecked(),
                                   follow=self.follow.isChecked() or self.show_first)

        def configure(self):
            snapshot = self.snapshot()
            before = self.full_uncertainty.isChecked()
            configure(snapshot)
            self.loaded_settings = None
            self.refresh()
            if self.curve_id is not None and before != self.full_uncertainty.isChecked():
                self.recalculate_saved_pressure()

        def refresh(self):
            try:
                status = services.monitor_status()
                snapshot = self.snapshot()
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
                s = curve_settings(snapshot, curve) if curve else settings(snapshot.data)
                curve_id = curve.id if curve else None
                if self.curve_id != curve_id or self.loaded_settings != s:
                    self.curve_id = curve_id
                    self.temperature_pending = False
                    self.loaded_settings = copy.deepcopy(s)
                    self.temperature.blockSignals(True)
                    self.temperature.setValue(s["temperature_K"])
                    self.temperature.blockSignals(False)
                    self.full_uncertainty.blockSignals(True)
                    self.full_uncertainty.setChecked(s["full_pressure_uncertainty"])
                    self.full_uncertainty.blockSignals(False)
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
                self.recalculate.setEnabled(curve is not None and self.pending_calculation is None)
                self.recalculate.setText("Calculating uncertainty…" if self.pending_calculation else "Recalculate")
                self.full_uncertainty.setEnabled(self.pending_calculation is None)
                meta = current_result(snapshot, curve) if curve else None
                active_calculation = (
                    self.pending_calculation is not None
                    and self.pending_calculation[1:3] == (self.project_id, self.curve_id)
                )
                if active_calculation:
                    meta = {**self.pending_calculation[5], "needs_recalculation": False}
                elif (meta and meta.get("uncertainty_pending") and not meta["needs_recalculation"]
                      and not snapshot.project.read_only):
                    self.waiting_acquisitions[self.curve_id] = None
                self.spectrum.setText(curve.name if curve else "No ruby spectrum selected")
                stale = bool(meta and (meta["needs_recalculation"] or self.temperature_pending))
                colour = "background:#fff0bf;color:#654000;" if stale else "background:#155e4b;color:#ffffff;"
                if not meta or meta.get("pressure_GPa") is None:
                    colour = "background:#e2e8f0;color:#334155;"
                self.result.setStyleSheet(colour + "font-size:20px;font-weight:bold;padding:10px;border-radius:5px;")
                self.warning.setText("⚠ Settings, fit or masks changed. Saved pressure needs recalculation." if stale else "")
                if meta and meta.get("pressure_GPa") is not None:
                    self.result.setText(pressure_text(meta))
                    scale_label = PRESSURE_SCALES.get(
                        meta.get("pressure_scale"), (meta.get("pressure_scale", ""), "")
                    )[0]
                    notes = list(meta.get("warnings", []))
                    if meta.get("pressure_std_GPa") is None and meta.get("uncertainty_note"):
                        notes.append(meta["uncertainty_note"])
                    if meta.get("scale_uncertainty_note"):
                        notes.append(meta["scale_uncertainty_note"])
                    if meta.get("settings", {}).get("full_pressure_uncertainty"):
                        if meta.get("background_bootstrap_completed") is not None:
                            notes.append(f"Background block bootstrap: {meta['background_bootstrap_completed']}/"
                                         f"{meta['background_bootstrap_requested']} replicas completed")
                        if meta.get("pressure_background_std_GPa") is not None:
                            notes.append(f"Background 1σ = {meta['pressure_background_std_GPa']:.3g} GPa")
                        if meta.get("pressure_scale_std_GPa") is not None:
                            notes.append(f"Pressure scale 1σ = {meta['pressure_scale_std_GPa']:.3g} GPa")
                        for key in ("background_bootstrap_note", "pressure_scale_component_note", "full_uncertainty_note"):
                            if meta.get(key):
                                notes.append(meta[key])
                    notes.append(meta["instrument_calibration_note"])
                    self.details.setText(
                        f"Last calculation: T = {meta['temperature_K']:.3f} K; "
                        f"R1 = {meta['R1_nm']:.6f} nm.\n{scale_label}\n" + "\n".join(notes)
                    )
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
        "pressure_background_std_GPa",
        "pressure_scale_std_GPa",
        "pressure_combined_std_GPa",
        "pressure_scale_uncertainty_source",
        "pressure_scale_component_note",
        "uncertainty_pending",
        "background_bootstrap_completed",
        "background_bootstrap_requested",
        "background_bootstrap_block_length",
        "background_bootstrap_seed",
        "background_bootstrap_note",
        "full_uncertainty_note",
        "instrument_calibration_note",
        "pressure_scale",
        "scale_uncertainty_percent",
        "scale_uncertainty_GPa",
        "scale_uncertainty_note",
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
                pressure_scale=meta.get("pressure_scale", meta.get("settings", {}).get("pressure_scale")),
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
        description="Two pseudo-Voigt peaks with free FWHM and fixed eta; background and selectable temperature-corrected ruby pressure scale.",
    )
