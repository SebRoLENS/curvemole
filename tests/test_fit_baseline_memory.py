from __future__ import annotations

import numpy as np
import pytest

from curvemole.core.fit_records import baseline_for_curve
from curvemole.core.fitting import (
    CurveFitOutput,
    FitMode,
    FitResult,
    FitSettings,
    ParameterEstimate,
)


def _result() -> FitResult:
    paths = ["first.peak.area", "second.peak.area", "first.peak.center"]
    outputs = {}
    for name in ("first", "second"):
        arrays = [np.arange(5, dtype=float) + index for index in range(6)]
        outputs[name] = CurveFitOutput(name, *arrays, {"chi_square": 1.25})
    return FitResult(
        True, FitMode.INDEPENDENT, "complete", 2, 91,
        {path: ParameterEstimate(path, 2., .1, 1.8, 2.2, 0., 10., "free", None)
         for path in paths},
        outputs, {"chi_square": 2.5}, ["example warning"], FitSettings(), paths,
        covariance=np.arange(9.).reshape(3, 3),
        correlation=np.eye(3), timestamp="2026-10-21T12:00:00Z",
        elapsed_seconds=4.5, cancelled=True, paused_curve_id="second",
    )


def test_individual_baseline_copies_only_selected_spectrum_and_covariance_block() -> None:
    result = _result()

    class UnselectedArray(np.ndarray):
        def __deepcopy__(self, memo):
            raise AssertionError("unselected spectrum was copied")

    result.curve_outputs["second"].observed = np.arange(5.).view(UnselectedArray)
    baseline = baseline_for_curve(result, "first")
    assert set(baseline.curve_outputs) == {"first"}
    assert set(baseline.parameters) == {"first.peak.area", "first.peak.center"}
    assert baseline.free_parameter_paths == ["first.peak.area", "first.peak.center"]
    np.testing.assert_array_equal(baseline.covariance, result.covariance[np.ix_([0, 2], [0, 2])])
    np.testing.assert_array_equal(baseline.correlation, np.eye(2))
    assert not np.shares_memory(baseline.covariance, result.covariance)
    assert baseline.statistics == {"chi_square": 1.25}
    for field in ("message", "status", "evaluations", "timestamp", "elapsed_seconds",
                  "cancelled", "paused_curve_id"):
        assert getattr(baseline, field) == getattr(result, field)
    original = result.curve_outputs["first"]
    selected = baseline.curve_outputs["first"]
    for field in ("indices", "x", "observed", "fitted", "residual", "weighted_residual"):
        np.testing.assert_array_equal(getattr(selected, field), getattr(original, field))
        assert not np.shares_memory(getattr(selected, field), getattr(original, field))
    selected.observed[0] = -999
    selected.statistics["chi_square"] = -99
    baseline.parameters["first.peak.area"].value = -99
    baseline.warnings.append("new warning")
    baseline.settings.workers = 13
    assert original.observed[0] != -999
    assert original.statistics["chi_square"] == 1.25
    assert result.parameters["first.peak.area"].value == 2.
    assert result.warnings == ["example warning"]
    assert result.settings.workers != 13


def test_global_baseline_preserves_coupling_and_detaches_all_spectra() -> None:
    result = _result()
    result.mode = FitMode.GLOBAL
    baseline = baseline_for_curve(result, "first")
    assert baseline.mode == FitMode.GLOBAL
    assert set(baseline.curve_outputs) == {"first", "second"}
    assert baseline.free_parameter_paths == result.free_parameter_paths
    np.testing.assert_array_equal(baseline.covariance, result.covariance)
    assert not np.shares_memory(baseline.covariance, result.covariance)
    baseline.curve_outputs["second"].observed[0] = -999
    assert result.curve_outputs["second"].observed[0] != -999
    with pytest.raises(KeyError):
        baseline_for_curve(result, "unknown")
