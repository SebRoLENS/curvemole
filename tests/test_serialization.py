from __future__ import annotations

import zipfile

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Project, Series
from curvemole.core.calculator import apply_scalar
from curvemole.core.errors import ProjectFormatError
from curvemole.core.fitting import FitResult
from curvemole.core.serialization import (
    load_fitmodel,
    load_project,
    save_fitmodel,
    save_project,
    validate_project_archive,
)


def test_project_round_trip(tmp_path) -> None:
    project = Project("Round trip")
    curve = Curve("spectrum", np.arange(8.0), np.arange(8.0) ** 2, sigma_y=np.ones(8))
    curve.mask_interval(2, 3)
    apply_scalar(curve, "y_multiply", 2)
    project.add_series(Series("series", [curve]))
    project.model_for(curve.id).add(Component.create("gaussian"))
    project.results["last_fit"] = Fitter().fit_single(curve, project.model_for(curve.id))
    project.custom_functions.append({"identifier": "example", "formula": "a*x", "kind": "generic"})
    path = save_project(project, tmp_path / "roundtrip.fitproj")
    assert validate_project_archive(path) == []
    restored = load_project(path)
    restored_curve = restored.curves[0]
    assert restored.name == project.name
    assert restored_curve.y.tolist() == curve.y.tolist()
    assert restored_curve.effective_mask.tolist() == curve.effective_mask.tolist()
    assert restored.models[restored_curve.id].components[0].function_id == "gaussian"
    assert isinstance(restored.results["last_fit"], FitResult)
    assert restored.results["last_fit"].curve_outputs[restored_curve.id].residual.shape == (6,)
    with zipfile.ZipFile(path) as archive:
        assert "manifest.json" in archive.namelist()
        assert not any(name.endswith((".pkl", ".pickle")) for name in archive.namelist())


def test_checksum_corruption_is_reported(tmp_path) -> None:
    project = Project("Corrupt")
    curve = Curve("c", np.arange(4.0), np.arange(4.0))
    project.add_series(Series("s", [curve]))
    path = save_project(project, tmp_path / "bad.fitproj")
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(f"data/{curve.id}/original_y.npy", b"broken")
    failures = validate_project_archive(path, raise_on_error=False)
    assert any("Checksum mismatch" in failure or "CRC" in failure for failure in failures)
    with pytest.raises(ProjectFormatError):
        load_project(path)


def test_fitmodel_round_trip(tmp_path) -> None:
    from curvemole import Model

    model = Model(components=[Component.create("lorentzian")])
    path = save_fitmodel(model, tmp_path / "model.fitmodel")
    restored, custom = load_fitmodel(path)
    assert restored.components[0].function_id == "lorentzian"
    assert custom == []
