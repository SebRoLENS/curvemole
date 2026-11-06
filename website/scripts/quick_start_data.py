"""Deterministic Raman-like data for the website's reproducible quick start.

This module needs NumPy only and does not import the application or GUI. It can
also be run directly to regenerate the downloadable CSVs and ground-truth record.
The independent Gaussian noise is deliberately simple; these synthetic bands are
an instructional example, not a model of every Raman instrument or material.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

SEED = 1729
NOISE_SIGMA = 2.0
MASK_INTERVAL = (894.0, 906.0)
ANCHOR_X = (260.0, 850.0, 1720.0)
BANDS = (
    {"name": "Isolated band", "area": 12000.0, "center": 500.0, "sigma": 18.0},
    {"name": "Overlap A", "area": 14000.0, "center": 1190.0, "sigma": 30.0},
    {"name": "Overlap B", "area": 11000.0, "center": 1260.0, "sigma": 30.0},
)
BASELINE_CAVEAT = (
    "The quadratic background is estimated from three observed control points, "
    "then held fixed and subtracted. Fit and resampling uncertainties are "
    "conditional on this chosen background; its estimation uncertainty is not "
    "propagated into the band parameters."
)


def make_dataset() -> dict:
    """Return new arrays and JSON-compatible metadata for the tutorial.

    ``y`` is the primary observed spectrum, including a one-sample positive
    artifact at 900 cm^-1. ``y_clean`` has the identical noise realization but no
    added artifact; ``y_cosmic`` is an explicit alias copy of the primary data for
    the optional plugin exercise. ``mask`` is True for observations excluded from
    the fit (894--906 cm^-1 inclusive).

    ``anchors`` is a (3, 2) array of exact X and *observed* Y coordinates, read
    from the primary spectrum. Their three distinct X positions define a degree-2
    polynomial. ``background_coefficients`` uses CurveMole's ascending c0,c1,c2
    convention; ``estimated_background`` evaluates this polynomial on ``x``.
    ``background`` and ``components`` (3 by N) are noiseless ground truth only.
    """
    x = np.arange(200.0, 1800.0 + 1.0, 2.0)
    background = 70.0 + 0.018 * (x - 200.0) + 0.000025 * (x - 900.0) ** 2
    components = np.asarray([
        band["area"] / (band["sigma"] * np.sqrt(2.0 * np.pi))
        * np.exp(-0.5 * ((x - band["center"]) / band["sigma"]) ** 2)
        for band in BANDS
    ])
    signal = components.sum(axis=0)
    noise = np.random.default_rng(SEED).normal(0.0, NOISE_SIGMA, len(x))
    y_clean = background + signal + noise
    artifact = np.zeros_like(x)
    artifact[x == 900.0] = 180.0
    y = y_clean + artifact
    sigma_y = np.full_like(x, NOISE_SIGMA)
    mask = (x >= MASK_INTERVAL[0]) & (x <= MASK_INTERVAL[1])
    anchors = np.asarray([(value, y[np.flatnonzero(x == value)[0]]) for value in ANCHOR_X])
    polynomial = np.polynomial.Polynomial.fit(anchors[:, 0], anchors[:, 1], 2).convert()
    estimated_background = polynomial(x)
    metadata = {
        "title": "Three-band Raman-like quick-start spectrum",
        "synthetic": True,
        "x_label": "Raman shift",
        "x_unit": "cm^-1",
        "y_label": "Intensity",
        "y_unit": "arbitrary units",
        "samples": len(x),
        "x_start": float(x[0]),
        "x_stop": float(x[-1]),
        "x_step": float(x[1] - x[0]),
        "noise": {"distribution": "independent Gaussian", "sigma_y": NOISE_SIGMA,
                  "seed": SEED, "generator": "NumPy default_rng (PCG64)"},
        "bands": [dict(band) for band in BANDS],
        "peak_parameterization": "Gaussian area is signed integrated area; sigma is standard deviation",
        "true_background": {
            "formula": "70 + 0.018*(x - 200) + 0.000025*(x - 900)**2",
            "coefficient_order": ["c0", "c1", "c2"],
            "coefficients": [86.65, -0.027, 0.000025],
        },
        "background_anchors": [
            {"x": float(point[0]), "observed_y": float(point[1])} for point in anchors
        ],
        "estimated_background_coefficients": polynomial.coef.tolist(),
        "estimated_background_degree": 2,
        "artifact": {"x": 900.0, "height_added": 180.0, "samples": 1,
                     "purpose": "Synthetic narrow artifact for masking and optional cosmic-removal exercise"},
        "fit_mask": {"excluded_interval": list(MASK_INTERVAL), "excluded_samples": int(mask.sum())},
        "fit_settings": {"model": "three Gaussian bands", "use_data_errors": True,
                         "absolute_sigma": True, "loss": "linear"},
        "uncertainty_caveat": BASELINE_CAVEAT,
        "interpretation": (
            "The overlapping bands' areas can compensate each other, producing a strong "
            "negative parameter correlation even when the total fitted curve follows the data. "
            "Gaussian line shapes are chosen for this demonstration, not inferred as universal Raman profiles."
        ),
    }
    return {
        "x": x, "y": y, "y_clean": y_clean, "y_cosmic": y.copy(),
        "sigma_y": sigma_y, "background": background, "components": components,
        "signal": signal, "noise": noise, "artifact": artifact, "mask": mask,
        "anchors": anchors, "background_coefficients": polynomial.coef,
        "estimated_background": estimated_background,
        "corrected_y": y - estimated_background,
        "metadata": metadata,
    }


def write_dataset(output_dir: str | Path) -> dict[str, Path]:
    """Write repeatable inputs/ground truth and return named output paths.

    Keys are ``spectrum``, ``clean``, ``cosmic``, ``truth``, ``reference`` and
    ``readme``. The first three CSVs contain only X, measured Y and absolute sigma_y,
    so they can be imported without any hidden model columns. ``cosmic`` repeats
    the primary spectrum under a separate name for the optional plugin exercise.
    """
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    data = make_dataset()
    paths = {
        "spectrum": destination / "raman-spectrum.csv",
        "clean": destination / "raman-clean.csv",
        "cosmic": destination / "raman-with-cosmic.csv",
        "truth": destination / "raman-truth.csv",
        "reference": destination / "reference.json",
        "readme": destination / "README.txt",
    }
    for name, values in (("spectrum", data["y"]), ("clean", data["y_clean"]),
                         ("cosmic", data["y_cosmic"])):
        np.savetxt(
            paths[name], np.column_stack((data["x"], values, data["sigma_y"])),
            delimiter=",", header="raman_shift_cm-1,intensity,sigma_y", comments="",
            fmt=("%.1f", "%.12g", "%.3f"),
        )
    truth = np.column_stack((
        data["x"], data["background"], *data["components"], data["signal"],
        data["noise"], data["y_clean"], data["y"], data["estimated_background"],
        data["mask"].astype(int),
    ))
    np.savetxt(
        paths["truth"], truth, delimiter=",", fmt="%.12g", comments="",
        header=("raman_shift_cm-1,true_background,isolated_band,overlap_A,overlap_B,"
                "true_signal,noise,observed_clean,observed_with_cosmic,"
                "estimated_background,fit_mask_excluded"),
    )
    paths["reference"].write_text(json.dumps(data["metadata"], indent=2) + "\n", encoding="utf-8")
    paths["readme"].write_text(
        "CurveMole website quick-start data\n\n"
        "Synthetic Raman-like data: three area-normalised Gaussian bands, a quadratic\n"
        "background, and independent Gaussian noise with known sigma_y = 2.\n"
        "No experimental measurements or software-validation claims are implied.\n\n"
        "raman-spectrum.csv: primary tutorial input; includes a one-sample +180 artifact\n"
        "at 900 cm^-1. Exclude 894--906 cm^-1 before fitting.\n"
        "raman-clean.csv: identical underlying signal and noise without the artifact.\n"
        "raman-with-cosmic.csv: same values as the primary input, saved separately for\n"
        "the optional cosmic-removal plugin exercise. Work on a separate imported copy.\n"
        "Each input CSV has X, observed intensity and absolute one-standard-deviation\n"
        "sigma_y columns. The original input files must remain unchanged.\n\n"
        "raman-truth.csv: noiseless components, noise, original observations, the\n"
        "three-point background estimate, and the fit-exclusion mask. This file is\n"
        "ground truth for inspection, not the tutorial's fitting input.\n"
        "reference.json: generation parameters, exact observed anchor coordinates,\n"
        "mask interval and scientific conventions.\n\n"
        + BASELINE_CAVEAT + "\n",
        encoding="utf-8",
    )
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    for key, path in write_dataset(arguments.output).items():
        print(f"{key}: {path}")
