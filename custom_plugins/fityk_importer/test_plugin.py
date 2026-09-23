"""Functional saved-state and safety tests for the Fityk importer."""

import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from curvemole.core.project import Project


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
        "%v = Voigt(1, 2, 3, 0.5)\nF = %v\n")
    prepared, warnings = plugin.parse_project(source)
    assert len(prepared) == 1 and len(prepared[0][0]) == 3
    assert not prepared[0][1] and "Voigt" in warnings[0]
