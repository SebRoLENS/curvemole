"""Scientific invariants for the website's independently repeatable input data."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from curvemole import Component, Curve, FitSettings, Fitter, Model

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "quick_start_data", ROOT / "website/scripts/quick_start_data.py")
assert SPEC is not None and SPEC.loader is not None
DATA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DATA)


def test_primary_artifact_and_mask_do_not_change_the_clean_signal() -> None:
    data = DATA.make_dataset()
    repeated = DATA.make_dataset()
    np.testing.assert_array_equal(data["y"], repeated["y"])
    np.testing.assert_array_equal(data["y_clean"], repeated["y_clean"])
    assert data["components"].shape == (3, 801)
    changed = np.flatnonzero(data["y"] != data["y_clean"])
    assert len(changed) == 1
    assert data["x"][changed[0]] == 900.0
    assert data["y"][changed[0]] - data["y_clean"][changed[0]] == pytest.approx(180.0)
    assert data["mask"].sum() == 7
    assert data["mask"][changed[0]]
    np.testing.assert_array_equal(data["y"][~data["mask"]], data["y_clean"][~data["mask"]])


def test_three_observed_background_anchors_define_the_documented_quadratic() -> None:
    data = DATA.make_dataset()
    assert data["anchors"].shape == (3, 2)
    for x, observed_y in data["anchors"]:
        i = np.flatnonzero(data["x"] == x)[0]
        assert observed_y == data["y"][i]
        assert not data["mask"][i]
        assert data["signal"][i] < 1e-8
    estimate = np.polynomial.polynomial.polyval(
        data["anchors"][:, 0], data["background_coefficients"])
    np.testing.assert_allclose(estimate, data["anchors"][:, 1], atol=1e-10)
    assert len(data["background_coefficients"]) == 3
    assert "conditional" in data["metadata"]["uncertainty_caveat"]


def test_masked_fit_exposes_overlap_area_correlation_with_the_real_engine() -> None:
    data = DATA.make_dataset()
    curve = Curve("Quick-start Raman", data["x"], data["corrected_y"], sigma_y=data["sigma_y"])
    curve.mask_interval(*DATA.MASK_INTERVAL)
    model = Model()
    for truth in DATA.BANDS:
        component = Component.create("gaussian", name=truth["name"], initial={
            "area": 0.95 * truth["area"], "center": truth["center"] + 2.0,
            "sigma": 1.05 * truth["sigma"],
        })
        component.parameters["area"].minimum = 0.0
        model.add(component)
    result = Fitter().fit_single(
        curve, model, FitSettings(use_data_errors=True, absolute_sigma=True))
    assert result.success
    assert result.statistics["N"] == 794
    assert result.statistics["degrees_of_freedom"] == 785
    for component, truth in zip(model.components, DATA.BANDS, strict=True):
        assert component.parameters["center"].value == pytest.approx(truth["center"], abs=1.0)
        assert component.parameters["area"].value == pytest.approx(truth["area"], rel=0.04)
    overlap_paths = [model.parameter_path(curve.id, component.id, "area")
                     for component in model.components[1:]]
    positions = [result.free_parameter_paths.index(path) for path in overlap_paths]
    rho = np.asarray(result.correlation)[positions[0], positions[1]]
    assert -1.0 < rho < -0.95
    assert any("correlation" in warning for warning in result.warnings)
    isolated_area = model.parameter_path(curve.id, model.components[0].id, "area")
    isolated_index = result.free_parameter_paths.index(isolated_area)
    assert abs(np.asarray(result.correlation)[isolated_index, positions[0]]) < 0.01


def test_downloads_are_reproducible_and_keep_input_separate_from_truth(tmp_path) -> None:
    paths = DATA.write_dataset(tmp_path / "first")
    again = DATA.write_dataset(tmp_path / "second")
    assert set(paths) == {"spectrum", "clean", "cosmic", "truth", "reference", "readme"}
    for name in paths:
        assert paths[name].read_bytes() == again[name].read_bytes()
    primary = np.loadtxt(paths["spectrum"], delimiter=",", skiprows=1)
    np.testing.assert_allclose(primary[:, 0], DATA.make_dataset()["x"])
    np.testing.assert_allclose(primary[:, 1], DATA.make_dataset()["y"], rtol=1e-10)
    assert primary.shape == (801, 3)
    assert np.all(primary[:, 2] == 2.0)
    metadata = json.loads(paths["reference"].read_text())
    assert metadata["synthetic"] is True
    assert len(metadata["bands"]) == 3
    assert metadata["artifact"]["x"] == 900.0
    assert metadata["fit_mask"]["excluded_interval"] == [894.0, 906.0]
