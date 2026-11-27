import hashlib

import numpy as np

from curvemole.core.calculator import apply_curve_operation
from curvemole.core.data import Curve


def _curves():
    x = np.linspace(0, 10, 50)
    target = Curve("signal", x, np.exp(-(x - 5) ** 2), sigma_y=np.full(50, 0.01))
    background = Curve("background", x + 0.05, np.full(50, 0.1), sigma_y=np.full(50, 0.01))
    return target, background


def test_curve_operation_flags_are_plain_python_values():
    target, background = _curves()
    transformation = apply_curve_operation(target, background, "curve_subtract")
    assert type(transformation.parameters["correlated_operand"]) is bool
    assert type(target.has_correlated_y_errors) is bool


def test_fingerprint_matches_legacy_numpy_flag_spelling():
    target, background = _curves()
    apply_curve_operation(target, background, "curve_subtract")
    flags = target._hash_flags(2)
    legacy = target._fit_input_digest(2, None)
    legacy.update(repr((flags[0], flags[1], np.bool_(flags[2]))).encode())
    assert legacy.hexdigest() != target.fit_input_hash()
    assert target.matches_fit_input_hash(legacy.hexdigest())
    assert not target.matches_fit_input_hash(hashlib.sha256(b"other").hexdigest())


def test_fit_after_curve_operation_stays_valid_after_save_and_load(tmp_path):
    from curvemole import Component, Fitter, Project, Series
    from curvemole.core.serialization import load_project, save_project

    rng = np.random.default_rng(1)
    x = np.linspace(-5, 5, 60)
    background = Curve("bg", x, 0.1 + 0.01 * x, sigma_y=np.full(60, 0.02))
    signal = Curve("sig", x, 2 * np.exp(-x ** 2 / 2) + 0.1 + 0.01 * x + 0.02 * rng.normal(size=60),
                   sigma_y=np.full(60, 0.02))
    apply_curve_operation(signal, background, "curve_subtract")
    project = Project("p")
    project.add_series(Series("s", [background, signal]))
    project.model_for(signal.id).add(Component.create("gaussian"))
    project.results["last_fit"] = Fitter().fit_single(signal, project.model_for(signal.id))
    loaded = load_project(save_project(project, tmp_path / "a.fitproj"))
    record = loaded.results["last_fit"]
    curve = loaded.dataset.curve(signal.id)
    assert curve.matches_fit_input_hash(record.provenance["input_hashes"][signal.id],
                                        record.provenance["schema_version"])
    Fitter().replay(record, loaded.curves)
