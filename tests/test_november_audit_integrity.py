"""Data integrity and bounded-input regressions from the November audit."""

from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import pytest

from curvemole import Component, Curve, Project, Series
from curvemole.core.archive_validation import ArchiveLimits
from curvemole.core.errors import (
    CurveMoleError,
    DataValidationError,
    ExpressionError,
    ProjectFormatError,
)
from curvemole.core.expressions import SafeExpression
from curvemole.core.folder_import import merge_acquisition_results
from curvemole.core.functions import formula_definition
from curvemole.core.plugins import PluginManager
from curvemole.core.registry import default_registry
from curvemole.core.serialization import load_project, save_project, validate_project_archive
from curvemole.core.spectrum_export import export_spectra, spectrum_export_filename


def test_acquisition_merge_preserves_previous_results_and_rejects_cross_curve_records():
    old = {"uncertainty_by_curve": {"old": {"bootstrap": 1}}, "last_fit": "old fit"}
    new = {"uncertainty_by_curve": {"new": {"profile": 2}}, "last_fit": "new fit"}
    merged = merge_acquisition_results(old, new, {"new"})
    assert set(merged["uncertainty_by_curve"]) == {"old", "new"}
    assert merged["import_result_history"] == [{"key": "last_fit", "value": "old fit"}]
    assert old == {"uncertainty_by_curve": {"old": {"bootstrap": 1}}, "last_fit": "old fit"}
    with pytest.raises(ValueError, match="unrelated"):
        merge_acquisition_results(old, new, {"other"})


def test_export_refuses_existing_files_and_links_before_writing_anything(tmp_path):
    p = Project()
    a = Curve("a", [0, 1], [1, 2])
    b = Curve("b", [0, 1], [3, 4])
    p.add_series(Series("s", [a, b]))
    dest = tmp_path / spectrum_export_filename(b)
    dest.write_text("keep this")
    with pytest.raises(FileExistsError):
        export_spectra(p, tmp_path, [a.id, b.id])
    assert not (tmp_path / spectrum_export_filename(a)).exists()
    assert dest.read_text() == "keep this"
    external = tmp_path / "outside.txt"
    external.write_text("external")
    dest.unlink()
    dest.symlink_to(external)
    with pytest.raises(CurveMoleError, match="symbolic"):
        export_spectra(p, tmp_path, [b.id], overwrite=True)
    assert external.read_text() == "external"


def test_export_preserves_float64_values_and_cleans_staging_files(tmp_path):
    p = Project()
    c = Curve("precision", [0, 1], [1.0000000000001, 1.0000000000002])
    p.add_curve(c)
    dest = export_spectra(p, tmp_path, [c.id])[0]
    assert np.loadtxt(dest, skiprows=1)[:, 1] == pytest.approx(c.y, rel=0, abs=0)
    assert list(tmp_path.glob(".curvemole-export-*")) == []
    dest.write_text("old")
    export_spectra(p, tmp_path, [c.id], overwrite=True)
    assert dest.read_text() != "old"


@pytest.mark.parametrize("operation", ["curve", "series", "component", "remove", "snapshot"])
def test_readonly_mutators_are_side_effect_free(operation):
    p = Project()
    c = Curve("c", [0, 1], [1, 2])
    p.add_curve(c)
    p.dirty = False
    p.read_only = True
    revision = p.revision
    model = p.model_for(c.id)
    actions = {
        "curve": lambda: p.add_curve(Curve("new", [0, 1], [2, 3])),
        "series": lambda: p.add_series(Series("new", [])),
        "component": lambda: p.add_component(c.id, Component.create("constant")),
        "remove": lambda: p.remove_curve(c.id),
        "snapshot": lambda: p.snapshot("bad", {}),
    }
    with pytest.raises(PermissionError):
        actions[operation]()
    assert p.curves == [c] and len(p.dataset.series) == 1
    assert model.components == [] and len(p.fit_history) == 0
    assert not p.dirty and p.revision == revision


def test_registry_layers_do_not_leak_and_builtin_collisions_are_rejected():
    base = default_registry().copy()
    session = base.copy()
    session.set_project_functions([{"identifier": "audit_formula", "formula": "2*x"}])
    assert "audit_formula" not in base.identifiers()
    session.set_project_functions([])
    assert "audit_formula" not in session.identifiers()
    with pytest.raises(DataValidationError, match="builtin"):
        session.set_project_functions([{"identifier": "constant", "formula": "100*offset"}])
    assert session.get("constant").evaluate(np.array([0.0]), {"offset": 2}, {}) == [2]
    base.register(formula_definition("audit_layer", "layer", "3*x"))
    session = base.copy()
    session.set_project_functions([{"identifier": "audit_layer", "formula": "4*x"}])
    session.set_project_functions([])
    assert session.get("audit_layer") is base.get("audit_layer")


def test_validator_rejects_malformed_schema_and_load_wraps_errors(tmp_path):
    path = tmp_path / "bad.fitproj"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"schema_version": 3, "project": []}))
    assert validate_project_archive(path, raise_on_error=False)
    with pytest.raises(ProjectFormatError):
        load_project(path)


def test_archive_resource_limits_are_checked_before_loading_arrays(tmp_path):
    p = Project()
    p.add_curve(Curve("c", np.arange(20.0), np.arange(20.0)))
    path = save_project(p, tmp_path / "budget.fitproj")
    with pytest.raises(ProjectFormatError, match="budget"):
        load_project(path, limits=ArchiveLimits(expanded_bytes=10))
    with pytest.raises(ProjectFormatError, match="array-size"):
        load_project(path, limits=ArchiveLimits(array_bytes=8))
    assert validate_project_archive(path) == []


def test_forged_array_shape_is_rejected_without_allocating_claimed_memory(tmp_path):
    payload = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        payload, {"descr": "<f8", "fortran_order": False, "shape": (10**12,)}
    )
    path = tmp_path / "forged.fitproj"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"schema_version": 3, "project": {"id": "p"}}))
        archive.writestr("giant.npy", payload.getvalue())
    with pytest.raises(ProjectFormatError, match="array-size"):
        load_project(path)


@pytest.mark.parametrize(
    "source", ["2**100000", "10**(10**10)", "1+" * 3000 + "1", " " * 20000 + "1"]
)
def test_expression_resource_budget_rejects_small_bombs(source):
    with pytest.raises(ExpressionError):
        SafeExpression.compile(source).evaluate()


def test_normal_vectorized_math_still_works():
    x = np.linspace(-2, 2, 101)
    assert SafeExpression.compile("exp(-x**2)+sin(x)").evaluate({"x": x}) == pytest.approx(
        np.exp(-x * x) + np.sin(x)
    )


def test_local_plugin_fingerprint_includes_helpers_but_excludes_manager_state(tmp_path):
    root = tmp_path / "plugin"
    root.mkdir()
    storage = root / "manager-state"
    manager = PluginManager(storage=storage)
    manifest = root / "demo.curvemole-plugin.json"
    manifest.write_text(
        json.dumps(
            {
                "identifier": "demo",
                "version": "1.0.0",
                "api_compatibility": "1",
                "licence": "MIT",
                "capabilities": [],
                "module": "demo.py",
            }
        )
    )
    (root / "demo.py").write_text("def register(api):\n    pass\n")
    helper = root / "helper.py"
    helper.write_text("SCALE=1")
    candidate = manager.discover_local(root)[0]
    first = manager._fingerprint(candidate)
    helper.write_text("SCALE=2")
    second = manager._fingerprint(candidate)
    assert first != second
    (storage / "installed.json").write_text("{}")
    assert manager._fingerprint(candidate) == second


def test_expression_checks_broadcast_size_before_allocating(monkeypatch):
    import curvemole.core.expressions as expressions

    monkeypatch.setattr(expressions, "MAX_ARRAY_ELEMENTS", 100)
    for formula in ("a*b", "where(a>0, a, b)", "(a>0) and (b>0)", "a>b>a"):
        with pytest.raises(ExpressionError, match="broadcast"):
            SafeExpression.compile(formula).evaluate({"a": np.ones((1, 11)), "b": np.ones((11, 1))})


def test_export_works_on_a_filesystem_without_hardlinks(tmp_path, monkeypatch):
    import errno

    def unsupported(*args):
        raise OSError(errno.ENOTSUP, "no hard links")

    monkeypatch.setattr("curvemole.core.spectrum_export.os.link", unsupported)
    p = Project()
    c = Curve("fat", [0, 1], [2, 3])
    p.add_curve(c)
    path = export_spectra(p, tmp_path, [c.id])[0]
    assert path.exists()
    with pytest.raises(FileExistsError):
        export_spectra(p, tmp_path, [c.id])


def test_export_registry_does_not_modify_default_functions():
    from curvemole.core.export import _registry_for_project

    p = Project(custom_functions=[{"identifier": "audit_export_local", "formula": "2*x"}])
    scoped = _registry_for_project(p)
    assert "audit_export_local" in scoped.identifiers()
    assert "audit_export_local" not in default_registry().identifiers()


@pytest.mark.parametrize(
    "section,value",
    [("models", {"components": [None]}), ("masks", [{}]), ("transformations", [{}])],
)
def test_validator_catches_invalid_nested_records(tmp_path, section, value):
    p = Project()
    c = Curve("bad metadata", [0, 1], [2, 3])
    p.add_curve(c)
    path = save_project(p, tmp_path / "nested.fitproj")
    with zipfile.ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(contents["manifest.json"])
    if section == "models":
        manifest["project"]["models"][c.id] = value
    else:
        manifest["project"]["curves"][c.id][section] = value
    contents["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in contents.items():
            archive.writestr(name, payload)
    assert validate_project_archive(path, raise_on_error=False)
    with pytest.raises(ProjectFormatError):
        load_project(path)


def test_acquisition_merge_preserves_display_choices_and_incoming_history():
    old = {
        "uncertainty_display_method_by_curve": {"old": "bootstrap"},
        "import_result_history": [{"key": "old", "value": 1}],
    }
    new = {
        "uncertainty_display_method_by_curve": {"new": "profile"},
        "import_result_history": [{"key": "new", "value": 2}],
    }
    merged = merge_acquisition_results(old, new, {"new"})
    assert merged["uncertainty_display_method_by_curve"] == {"old": "bootstrap", "new": "profile"}
    assert (
        merged["import_result_history"]
        == old["import_result_history"] + new["import_result_history"]
    )
