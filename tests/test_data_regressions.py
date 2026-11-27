"""Regression tests for data (formerly grouped by audit)."""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import runpy
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from curvemole import Component, Curve, Model, Project, Series, Transformation
from curvemole.cli import EXIT_DATA, main
from curvemole.core.calculator import (
    apply_custom_formula,
    apply_scalar,
)
from curvemole.core.data import CurveState
from curvemole.core.diagnostics import contiguous_residual_segments, residual_diagnostics
from curvemole.core.errors import (
    ConstraintError,
    CurveMoleError,
    DataValidationError,
    ExpressionError,
)
from curvemole.core.expressions import SafeExpression
from curvemole.core.fitting import (
    CancellationToken,
)
from curvemole.core.functions import formula_definition
from curvemole.core.importers import ColumnMapping, import_file, inspect_file
from curvemole.core.initialization import find_peak_suggestions
from curvemole.core.parameters import Parameter
from curvemole.core.plugins import PluginManager
from curvemole.core.process_pool import bounded_results
from curvemole.core.registry import default_registry


def line():
    x = np.linspace(0, 1, 20)
    return Curve("line", x, 1 + 2*x + .01*np.sin(15*x), sigma_y=np.full(20, .1))

def project_with_curves(count=3):
    project = Project()
    for i in range(count):
        curve = Curve(f"Data {i}", np.linspace(-5., 5., 101), np.full(101, i + 1.))
        project.add_curve(curve)
        project.model_for(curve.id).add(Component.create("constant", initial={"offset": i + 1.}))
    return project

def link_to(project, target, source):
    src = project.model_for(source.id).components[0]
    dst = project.model_for(target.id).components[0]
    dst.parameters["offset"].link = f"${{{source.id}.{src.id}.offset}}"

def constant(value=0.):
    return Model(components=[Component.create("constant", initial={"offset": value})])

def plugin_candidate(root, manager):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'demo.curvemole-plugin.json').write_text(json.dumps(dict(
        identifier='second_audit', version='1', api_compatibility='1', licence='MIT',
        capabilities=[], module='demo.py')))
    (root / 'demo.py').write_text(
        'from curvemole.core.functions import formula_definition\n'
        'def register(api):\n    api.register(formula_definition("second_shadow", "Audit", "3*x"))\n')
    (root / 'helper.py').write_text('VALUE = 1\n')
    return manager.discover_local(root)[0]

def beta_script():
    path = Path('.github/scripts/beta_release.py')
    spec = importlib.util.spec_from_file_location('second_audit_beta', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_copy_value_uses_new_not_old_bounds():
    p = Project()
    a, b = line(), line()
    p.add_curve(a)
    p.add_curve(b)
    source = Component.create("constant", initial={"offset": 8})
    target = Component.create("constant", initial={"offset": .5})
    source.parameters["offset"].set_bounds(0, 10)
    target.parameters["offset"].set_bounds(0, 1)
    p.models[a.id] = Model(components=[source])
    p.models[b.id] = Model(components=[target])
    p.copy_fit(a.id, [b.id], structure=False)
    assert target.parameters["offset"].value == 8
    assert target.parameters["offset"].maximum == 10

def test_fast_mask_transfer_matches_brute_force_with_unsorted_and_duplicate_x():
    rng = np.random.default_rng(7)
    a = Curve("source", rng.integers(0, 100, 500), np.ones(500))
    b = Curve("target", rng.integers(0, 100, 600), np.ones(600))
    a.masks[a.active_mask].excluded[::3] = True
    values = a.x[a.masks[a.active_mask].excluded]
    expected = np.any(np.abs(b.x[:, None] - values) <= .5, axis=1)
    b.transfer_mask_from(a, tolerance=.5)
    np.testing.assert_array_equal(b.masks[b.active_mask].excluded, expected)
    p = Project()
    p.add_curve(a)
    p.add_curve(b)
    p.ui_state["mask_transfer_tolerance"] = .5
    extra = Curve("extra", b.x, b.y)
    p.add_curve(extra)
    p.copy_fit(a.id, [b.id, extra.id], masks=True)
    np.testing.assert_array_equal(b.effective_mask, extra.effective_mask)
    expected[:] = False
    for value in values:
        i = np.argmin(abs(b.x - value))
        if abs(b.x[i] - value) <= .5:
            expected[i] = True
    np.testing.assert_array_equal(b.masks[b.active_mask].excluded, expected)

@pytest.mark.parametrize("x", [[0., 1., 3.], [0., 0., 1.], [0., np.nan, 2.], [0., 2., 1.]])
def test_convolution_rejects_invalid_sampling_explicitly(x):
    model = Model(components=[Component.create("constant"),
                              Component.create("gaussian", operator="convolve")])
    with pytest.raises(DataValidationError, match="uniformly spaced"):
        model.evaluate(np.asarray(x))

def test_removal_blocks_external_dependencies_without_mutations():
    project = project_with_curves()
    a, b, c = project.curves
    link_to(project, b, a)
    link_to(project, c, b)
    before = [curve.id for curve in project.curves], copy.deepcopy(project.to_metadata())
    with pytest.raises(ConstraintError, match="remaining parameters"):
        project.remove_curves([a.id, b.id])
    assert [curve.id for curve in project.curves] == before[0]
    assert project.to_metadata() == before[1]
    project.resolved_parameter_values()
    # References entirely inside the removed set do not prevent group removal.
    project.remove_curves([a.id, b.id, c.id])
    assert project.curves == []

@pytest.mark.parametrize("relation", ["equal", "lower", "upper", "similar"])
def test_invalidation_follows_transitive_links_and_preserves_independent_data(relation):
    from curvemole.core.data import CurveState
    project = project_with_curves(4)
    a, b, c, d = project.curves
    link_to(project, b, a)
    link_to(project, c, b)
    parameter = project.model_for(b.id).components[0].parameters["offset"]
    parameter.link_relation = relation
    parameter.link_tolerance = .1 if relation == "similar" else 0.
    for curve in project.curves:
        curve.state = CurveState.FITTED
    affected = project.invalidate_fits({a.id})
    assert affected == {a.id, b.id, c.id}
    assert all(curve.state == CurveState.MODIFIED for curve in (a, b, c))
    assert d.state == CurveState.FITTED

def test_global_fit_invalidation_couples_records():
    from curvemole.core.data import CurveState
    project = project_with_curves()
    a, b, c = project.curves
    project.results["fit_by_curve"] = {a.id: {"global_key": "global"}, b.id: {"global_key": "global"}}
    for curve in project.curves:
        curve.state = CurveState.FITTED
    assert project.invalidate_fits({a.id}, preserve={a.id}) == {b.id}
    assert b.state == CurveState.MODIFIED
    assert a.state == c.state == CurveState.FITTED

def test_duplicate_separates_nested_metadata_and_background_provenance():
    source = Component.create("cubic_spline", metadata={"x_nodes": [0., 1., 2.]})
    source.metadata.update(_manual_points=[[0., 1.], [1., 2.], [2., 1.]],
                           nested={"list": [1, 2]}, background_subtraction_ids=["original"])
    model = Model(components=[source])
    duplicate = model.duplicate(source.id)
    duplicate.metadata["x_nodes"][0] = 99.
    duplicate.metadata["_manual_points"][0][1] = 99.
    source.metadata["nested"]["list"][0] = 42
    assert source.metadata["x_nodes"][0] == 0.
    assert source.metadata["_manual_points"][0][1] == 1.
    assert duplicate.metadata["nested"]["list"][0] == 1
    assert duplicate.metadata["background_history_detached"]
    assert "background_subtraction_ids" not in duplicate.metadata

@pytest.mark.parametrize("op,expected", [("==", [1., 10., 3.]), ("<=", [10., 10., 3.]),
                                         (">=", [1., 10., 10.]), ("!=", [10., 2., 10.])])
@pytest.mark.parametrize("assignment", ["", "Y = "])
def test_custom_formula_comparisons(op, expected, assignment):
    curve = Curve("Formula", [0., 1., 2.], [1., 2., 3.])
    apply_custom_formula(curve, "y", assignment + f"where(y {op} 2, 10, y)")
    np.testing.assert_array_equal(curve.y, expected)
    with pytest.raises(ExpressionError, match="target Y"):
        apply_custom_formula(curve, "y", "x = y")

@pytest.mark.parametrize("bounds", [(2., 0.), (2., 3.), ("invalid", 2.), (0., "invalid")])
def test_failed_bound_changes_preserve_original_parameter(bounds):
    parameter = Parameter("value", 1., minimum=0., maximum=2.)
    before = parameter.to_dict()
    with pytest.raises((ConstraintError, ValueError)):
        parameter.set_bounds(*bounds)
    assert parameter.to_dict() == before
    parameter.set_bounds(-2., 3.)
    assert (parameter.minimum, parameter.maximum) == (-2., 3.)

def test_bounded_queue_cancels_remaining_jobs_on_consumer_failure():
    submitted = []
    class Pool:
        def submit(self, value):
            future = Future()
            submitted.append(future)
            if len(submitted) == 1:
                future.set_result(value)
            return future
    stop = SimpleNamespace(set=lambda: setattr(stop, "stopped", True), stopped=False)
    iterator = bounded_results(Pool(), range(1000), lambda pool, value: pool.submit(value),
                               CancellationToken(), stop, limit=4)
    assert next(iterator) == (0, 0)
    assert len(submitted) == 4
    iterator.close()
    assert stop.stopped
    assert all(future.cancelled() for future in submitted[1:])

def test_autocorrelation_threshold_is_calibrated_across_lags_and_excludes_discontinuities():
    samples = np.random.default_rng(24).normal(size=(150, 1000))
    false_alarms = sum(any("95%" in warning for warning in residual_diagnostics(row).warnings) for row in samples)
    assert false_alarms < 16
    rows = np.array([0, 1, 2, 7, 8, 9])
    x = np.array([0., 1., 2., 7., 8., 12.])
    assert contiguous_residual_segments(rows, x) == (slice(0, 3), slice(3, 5), slice(5, 6))
    residual = np.array([1., 1., 1., -1., -1., 1.])
    diagnostic = residual_diagnostics(residual, indices=rows, x=x)
    assert diagnostic.durbin_watson == 0
    assert any("skip gaps" in warning for warning in diagnostic.warnings)

def test_convolution_rejects_nonuniform_grid_even_at_a_large_origin():
    origin = float(2**40)
    x = origin + np.spacing(origin) * np.array([0, 4, 16, 20, 32])
    model = constant(1.)
    model.components.append(Component.create("constant", initial={"offset": 1}, operator="convolve"))
    with pytest.raises(DataValidationError, match="uniformly spaced"):
        model.evaluate(x)

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

def test_parser_recursion_is_reported_as_expression_complexity(monkeypatch):
    def reject(*args, **kwargs):
        raise RecursionError("platform parser recursion limit")
    monkeypatch.setattr("curvemole.core.expressions.ast.parse", reject)
    with pytest.raises(ExpressionError, match="parser complexity"):
        SafeExpression.compile("1+2")

def test_inverse_variance_propagates_like_sigma_for_scalars_and_formulas():
    weighted = Curve("w", [1, 2, 3], [1, 2, 3], weights=[1, 4, 9])
    errors = Curve("s", [1, 2, 3], [1, 2, 3], sigma_y=1 / np.sqrt([1, 4, 9]))
    for c in (weighted, errors):
        apply_scalar(c, "y_multiply", -10)
        c.apply_transformation(Transformation("custom_formula", {"axis": "y", "formula": "y**2"}))
    assert weighted.fit_arrays()[2] == pytest.approx(errors.fit_arrays()[2], rel=1e-5)
    weighted.undo_transformation()
    assert weighted.current_weights == pytest.approx([0.01, 0.04, 0.09])

def test_copy_fit_invalidates_transitive_link_dependents():
    p = Project()
    curves = [Curve(str(i), [0, 1], [1, 2]) for i in range(3)]
    comps = [Component.create("constant", initial={"offset": i + 1}) for i in range(3)]
    for c, comp in zip(curves, comps, strict=True):
        p.add_curve(c)
        p.add_component(c.id, comp)
        c.state = CurveState.FITTED
    comps[2].parameters["offset"].link = "${" + f"{curves[1].id}.{comps[1].id}.offset" + "}"
    p.copy_fit(curves[0].id, [curves[1].id], structure=False)
    assert curves[0].state == CurveState.FITTED
    assert curves[1].state == curves[2].state == CurveState.MODIFIED

def test_import_shares_immutable_columns_and_detaches_transformations(tmp_path):
    source = tmp_path / 'many.csv'
    source.write_text('x,a,b\n0,2,3\n1,4,5\n2,6,7\n')
    a, b = import_file(source, ColumnMapping(x=0, y=[1, 2]))
    assert np.shares_memory(a.original_columns['c3'], b.original_columns['c3'])
    assert np.shares_memory(a.columns['c3'], a.original_columns['c3'])
    with pytest.raises(ValueError):
        a.original_columns['c3'].setflags(write=True)
    a.apply_transformation(Transformation('column_formula', {'formula': 'c3 * 2', 'target': 'c3'}))
    np.testing.assert_array_equal(a.columns['c3'], [6, 10, 14])
    np.testing.assert_array_equal(b.columns['c3'], [3, 5, 7])
    a.undo_transformation()
    np.testing.assert_array_equal(a.columns['c3'], b.columns['c3'])

def test_failed_validation_keeps_json_and_nonzero_status(tmp_path, capsys):
    source = tmp_path / 'invalid.yaml'
    source.write_text('schema_version: 2\nimports: []\n')
    assert main(['validate', str(source), '--json']) == EXIT_DATA
    assert '"valid": false' in capsys.readouterr().out

def test_preview_does_not_read_entire_text_file(tmp_path, monkeypatch):
    source = tmp_path / 'large.csv'
    source.write_text('x,y\n' + '0,1\n' * 5000)
    from pathlib import Path
    monkeypatch.setattr(Path, 'read_text', lambda *a, **k: pytest.fail('unbounded read_text'))
    assert len(inspect_file(source, rows=3).preview) == 3

def test_link_compilation_cached_by_expression_not_values(monkeypatch):
    SafeExpression.compile.cache_clear()
    original = ast.parse
    calls = []
    def parse(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(ast, 'parse', parse)
    for value in range(100):
        expr = SafeExpression.compile('${source} * 2')
        assert expr.evaluate(references={'source': value}) == value * 2
    assert len(calls) == 1
    SafeExpression.compile('${source} * 3')
    assert len(calls) == 2

def test_plugin_fingerprint_ignores_caches_and_rejects_symlinks(tmp_path):
    from pathlib import Path
    from runpy import run_path

    from curvemole.plugin_fingerprint import fingerprint
    validator = run_path(str(Path(__file__).parents[1] / 'scripts/validate_community_plugins.py'))['fingerprint']
    (tmp_path / 'plugin.py').write_text('value = 1\n')
    expected = fingerprint(tmp_path)
    cache = tmp_path / '__pycache__'
    cache.mkdir()
    (cache / 'plugin.pyc').write_bytes(b'cached')
    assert fingerprint(tmp_path) == validator(tmp_path) == expected
    (tmp_path / 'extra.txt').write_text('included')
    assert fingerprint(tmp_path) != expected
    link = tmp_path / 'link'
    try:
        link.symlink_to(tmp_path / 'plugin.py')
    except OSError:
        return
    with pytest.raises(ValueError, match='Symlinks'):
        fingerprint(tmp_path)

@pytest.mark.parametrize('scale', [1., 1e-18])
def test_fft_rejects_irregular_grid_at_any_units(scale):
    model = Model(components=[Component.create('constant'), Component.create('constant', operator='convolve')])
    with pytest.raises(DataValidationError, match='uniformly spaced'):
        model.evaluate(np.array([0, 1, 2, 4, 8.])*scale)

def test_background_uses_compensated_sum():
    components = [Component.create('constant', initial={'offset': value}) for value in [1e16, 1., -1e16]]
    for component in components:
        component.is_background = True
    model = Model(components=components)
    np.testing.assert_array_equal(model.background(np.arange(3.)), np.ones(3))

def test_duplicate_curve_or_series_is_rejected_without_losing_existing_model():
    p = Project()
    c = Curve('original', [0, 1], [1, 2])
    p.add_curve(c)
    p.add_component(c.id, Component.create('constant'))
    second = Series('second')
    p.add_series(second)
    revision, model = p.revision, p.models[c.id]
    with pytest.raises(DataValidationError):
        p.add_curve(Curve('collision', [0, 1], [3, 4], id=c.id), second)
    with pytest.raises(DataValidationError):
        p.add_series(Series('collision', [Curve('collision', [0, 1], [3, 4], id=c.id)]))
    with pytest.raises(DataValidationError):
        p.add_curve(Curve('foreign', [0, 1], [3, 4]), Series('outside'))
    assert p.revision == revision and p.models[c.id] is model
    assert len(p.curves) == 1 and not second.curves and len(model.components) == 1

@pytest.mark.parametrize('action', ['disable', 'remove'])
def test_disabled_plugin_does_not_return_after_project_override_is_removed(tmp_path, action):
    registry = default_registry().copy()
    manager = PluginManager(registry, storage=tmp_path / 'state')
    candidate = plugin_candidate(tmp_path / 'source', manager)
    manager.load(candidate, trust=True)
    retained = registry.get('second_shadow')
    registry.set_project_functions([dict(identifier='second_shadow', formula='5*x')])
    getattr(manager, action)('second_audit')
    with pytest.raises(CurveMoleError, match='disabled'):
        retained.evaluate(np.array([2.]), {}, {})
    assert registry.get('second_shadow').evaluate(np.array([2.]), {}, {}) == pytest.approx([10])
    registry.set_project_functions([])
    assert 'second_shadow' not in registry.identifiers()
    with pytest.raises(CurveMoleError, match='disabled'):
        retained.evaluate(np.array([2.]), {}, {})
    manager.load(candidate, trust=True)
    assert registry.get('second_shadow').evaluate(np.array([2.]), {}, {}) == pytest.approx([6])
    manager.disable('second_audit')

def test_internal_plugin_fingerprint_covers_source_and_matches_headless(tmp_path):
    manager = PluginManager(default_registry().copy(), storage=tmp_path / 'state')
    root = manager.storage / 'legacy'
    candidate = plugin_candidate(root, manager)
    first = manager._fingerprint(candidate)
    assert first != hashlib.sha256(b'').hexdigest()
    (root / 'helper.py').write_text('VALUE = 2\n')
    second = manager._fingerprint(candidate)
    assert first != second == PluginManager()._fingerprint(candidate)

def test_unregister_and_registry_copy_preserve_removal_of_hidden_definition():
    from curvemole.core.functions import formula_definition
    registry = default_registry().copy()
    registry.register(formula_definition('second_hidden', 'base', '3*x'))
    registry.set_project_functions([dict(identifier='second_hidden', formula='5*x')])
    isolated = registry.copy()
    isolated.unregister('second_hidden')
    isolated.set_project_functions([])
    assert 'second_hidden' not in isolated.identifiers()
    registry.set_project_functions([])
    assert registry.get('second_hidden').evaluate(np.array([2.]), {}, {}) == pytest.approx([6])

def test_beta_publisher_can_retry_and_still_rejects_unexpected_assets(tmp_path, monkeypatch):
    beta = beta_script()
    version = '1.2.3b999'
    for name in beta.expected_assets(version):
        (tmp_path / name).write_bytes(b'package')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'audit/placeholder')
    monkeypatch.setenv('GITHUB_SHA', 'audit-sha')
    monkeypatch.setattr(runpy, 'run_path', lambda *a, **k: {
        'beta_changes': lambda *a, **k: ('v1.2.2', 'Audit')})
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert args[1:3] == ['release', 'view']
        return SimpleNamespace(returncode=0, stdout=json.dumps(dict(
            isDraft=False, targetCommitish='audit-sha')))
    monkeypatch.setattr(beta.subprocess, 'run', run)
    for _ in range(2):
        beta.publish(version, tmp_path)
    assert len(calls) == 2
    (tmp_path / 'unexpected.exe').write_bytes(b'unknown')
    with pytest.raises(ValueError, match='Unexpected beta assets'):
        beta.publish(version, tmp_path)

def test_beta_hash_streams_without_read_bytes(tmp_path, monkeypatch):
    beta = beta_script()
    path = tmp_path / 'artifact'
    data = b'abc' * (1024 * 1024)
    path.write_bytes(data)
    def forbidden(*args, **kwargs):
        raise AssertionError('whole-file reads are forbidden')
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    assert beta.file_digest(path) == hashlib.sha256(data).hexdigest()

@pytest.mark.parametrize('ordering', ['ascending', 'descending', 'shuffled'])
def test_peak_width_uses_local_coordinates_on_irregular_grid(ordering):
    x = np.r_[np.arange(-301., -1.), np.linspace(-1, 1, 201), np.arange(2., 302.)]
    y = np.exp(-.5 * (x / .1)**2)
    order = np.arange(len(x))
    if ordering == 'descending':
        order = order[::-1]
    elif ordering == 'shuffled':
        order = np.random.default_rng(42).permutation(order)
    [peak] = find_peak_suggestions(Curve('irregular', x[order], y[order]), prominence=.1)
    assert peak.x == pytest.approx(0)
    assert peak.fwhm == pytest.approx(2 * np.sqrt(2 * np.log(2)) * .1, rel=.001)

def test_peak_search_reports_duplicate_coordinates_explicitly():
    with pytest.raises(DataValidationError, match='unique X'):
        find_peak_suggestions(Curve('duplicates', [0, 1, 1, 2], [0, 1, 2, 0]))
