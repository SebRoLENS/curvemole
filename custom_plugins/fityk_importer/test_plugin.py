"""Functional saved-state and safety tests for the Fityk importer."""

import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from curvemole.core.project import Project
from curvemole.core.registry import default_registry

MODULE = Path(__file__).with_name("fityk_importer.py")
SPEC = importlib.util.spec_from_file_location("fityk_importer", MODULE)
plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plugin)


def test_saved_state_import_and_undoable_snapshot(tmp_path):
    source = tmp_path / "saved.fit"
    source.write_text(
        "# Fityk 1.3.1\nuse @0\ntitle = 'first'\nM=3\n"
        "X[0]=0, Y[0]=1, S[0]=1, A[0]=1\n"
        "X[1]=1, Y[1]=2, S[1]=1, A[1]=0\n"
        "X[2]=2, Y[2]=1, S[2]=1, A[2]=1\n"
        "@+ = 0\nuse @1\ntitle = 'second'\nM=2\n"
        "X[0]=0, Y[0]=2, S[0]=1, A[0]=1\n"
        "X[1]=1, Y[1]=3, S[1]=1, A[1]=1\n"
        "$height = ~10[0:20]\n$ctr = ~1\n$width = ~0.5[0.1:2]\n"
        "%p = PseudoVoigt($height, $ctr, $width, ~0.3)\n"
        "@0: F = %p\n@1: F = %p\n", encoding="utf-8",
    )
    context = SimpleNamespace(path=source, project=Project(), data={})
    plugin.import_fityk(context)
    assert len(context.project.curves) == 2
    a, b = context.project.curves
    assert a.masks["Default"].excluded.tolist() == [False, True, False]
    assert not b.masks["Default"].excluded.any()
    ca = context.project.model_for(a.id).components[0]
    cb = context.project.model_for(b.id).components[0]
    assert ca.id != cb.id
    assert ca.parameters["fwhm"].minimum == pytest.approx(0.2)
    assert ca.parameters["eta"].value == pytest.approx(
        0.3 * math.pi / (0.7 * math.sqrt(math.pi / math.log(2)) + 0.3 * math.pi))
    assert np.isfinite(context.project.model_for(a.id).evaluate(a.x)).all()
    assert context.data["last_import"]["spectra"] == 2


def test_untrusted_commands_never_execute(tmp_path):
    marker = tmp_path / "executed"
    source = tmp_path / "malicious.fit"
    source.write_text(
        "# Fityk 1.3.1\n"
        f"lua io.open('{marker}', 'w'):write('bad')\n"
        "X[0]=0, Y[0]=1, S[0]=1, A[0]=1\n"
        "X[1]=1, Y[1]=2, S[1]=1, A[1]=1\n"
        "%p = Gaussian(__import__('os').system('true'), 0, 1)\n"
        "F = %p\n", encoding="utf-8",
    )
    prepared, warnings = plugin.parse_project(source)
    assert len(prepared) == 1 and not prepared[0][1]
    assert warnings and not marker.exists()


def test_external_text_and_unsupported_function(tmp_path):
    (tmp_path / "data.dat").write_text("0 1\n1 2\n2 1\n")
    source = tmp_path / "project.fit"
    source.write_text(
        "# Fityk 1.3\n@0 < '_SCRIPT_DIR_/data.dat:1:2::'\n"
        "%v = Pearson7(1, 2, 3, 0.5)\nF = %v\n")
    prepared, warnings = plugin.parse_project(source)
    assert len(prepared) == 1 and len(prepared[0][0]) == 3
    assert not prepared[0][1] and "Pearson7" in warnings[0]


def test_real_saved_state_voigt_values_and_area(tmp_path):
    source = tmp_path / "voigt.fit"
    source.write_text(
        "# Fityk 1.3.1. Created: 2026-09-23\n"
        "set verbosity = -1\nreset\n"
        "use @0\ntitle = 'Voigt fit'\nM=3\nX=2# =max(x), prevents sorting.\n"
        "X[0]=0, Y[0]=1, S[0]=1, A[0]=1\n"
        "X[1]=1, Y[1]=2, S[1]=1, A[1]=1\n"
        "X[2]=2, Y[2]=1, S[2]=1, A[2]=1\n"
        "$_1 = ~12.5\n$_2 = ~1.1\n$_3 = ~0.8[0.1:2]\n$_4 = ~0.25[0:1]\n"
        "%_1 = Voigt($_1, $_2, $_3, $_4)\n"
        "$_5 = ~20\n%_2 = VoigtA($_5, $_2, $_3, $_4)\n"
        "@0: F = %_1 + %_2\n")
    prepared, warnings = plugin.parse_project(source)
    curve, components = prepared[0]
    assert not warnings
    assert len(components) == 2
    assert components[0].function_id == "voigt"
    assert components[0].parameters["sigma"].value == pytest.approx(0.8 / math.sqrt(2))
    assert components[0].parameters["gamma"].value == pytest.approx(0.2)
    assert components[0].parameters["sigma"].minimum == pytest.approx(0.1 / math.sqrt(2))
    assert components[0].parameters["area"].value > 0
    assert components[1].parameters["area"].value == pytest.approx(20)
    assert components[1].parameters["center"].link is not None
    peak = default_registry().get("voigt").evaluate(
        np.array([1.1]), {key: p.value for key, p in components[0].parameters.items()})
    assert peak[0] == pytest.approx(12.5, rel=1e-12)
    project = Project()
    project.add_curve(curve)
    for component in components:
        project.add_component(curve.id, component)
    assert np.isfinite(project.model_for(curve.id).evaluate(curve.x, curve_id=curve.id)).all()


def test_saved_state_background_and_area_peak(tmp_path):
    source = tmp_path / "background.fit"
    source.write_text(
        "# Fityk 1.3.1\nuse @0\nM=3\n"
        "X[0]=0, Y[0]=1, S[0]=1, A[0]=1\n"
        "X[1]=1, Y[1]=2, S[1]=1, A[1]=1\n"
        "X[2]=2, Y[2]=1, S[2]=1, A[2]=1\n"
        "$_1 = ~5\n$_2 = ~1\n$_3 = ~0.5\n"
        "%peak = GaussianA($_1, $_2, $_3)\n"
        "%bg = Spline(0, 1, 2, 2)\n@0: F = %bg + %peak\n")
    prepared, warnings = plugin.parse_project(source)
    assert not warnings
    curve, parts = prepared[0]
    assert len(parts) == 2 and parts[0].is_background
    assert parts[1].parameters["area"].value == pytest.approx(5)
    project = Project()
    project.add_curve(curve)
    for part in parts:
        project.add_component(curve.id, part)
    assert np.isfinite(project.model_for(curve.id).evaluate(curve.x, curve_id=curve.id)).all()
