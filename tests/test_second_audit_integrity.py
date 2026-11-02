"""Regressions for the second November audit's data and plugin boundaries."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import runpy
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Model, Project, Series
from curvemole.core.errors import CurveMoleError, DataValidationError, ProjectFormatError
from curvemole.core.export import tidy_dataframe, wide_dataframe
from curvemole.core.fit_records import baseline_for_curve
from curvemole.core.fitting import FitPlan
from curvemole.core.plugins import PluginManager
from curvemole.core.recovery import RecoveryManager
from curvemole.core.registry import default_registry
from curvemole.core.serialization import load_project, save_project, validate_project_archive
from curvemole.core.spectrum_export import export_spectra, spectrum_export_dataframe


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


@pytest.mark.parametrize('invalid', [{'minimum': 5}, {'link': 'invalid('}])
def test_invalid_constraints_are_reported_and_do_not_hide_valid_recoveries(tmp_path, invalid):
    p = Project()
    c = Curve('curve', [0, 1, 2], [1, 2, 3])
    p.add_curve(c)
    p.add_component(c.id, Component.create('constant'))
    good = save_project(p, tmp_path / 'good.recovery-1.fitproj')
    bad = tmp_path / 'bad.recovery-2.fitproj'
    with zipfile.ZipFile(good) as z:
        payload = {name: z.read(name) for name in z.namelist()}
    manifest = json.loads(payload['manifest.json'])
    parameter = manifest['project']['models'][c.id]['components'][0]['parameters']['offset']
    parameter.update(invalid)
    payload['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(bad, 'w') as z:
        for name, value in payload.items():
            z.writestr(name, value)
    assert validate_project_archive(bad, raise_on_error=False)
    with pytest.raises(ProjectFormatError):
        load_project(bad)
    assert RecoveryManager(tmp_path).candidates() == [good]


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


@pytest.mark.parametrize('quick', [False, True])
def test_export_keeps_axis_data_and_error_columns_with_colliding_headers(quick):
    c = Curve('collision', [10, 20], [1, 2], x_label='Spectrum_y' if quick else 'sigma_y',
              y_label='y' if quick else 'sigma_y', sigma_y=[.1, .2])
    p = Project()
    p.add_curve(c)
    frame = spectrum_export_dataframe(p, c.id) if quick else wide_dataframe(c)
    roles = frame.attrs['column_roles']
    assert frame.columns.is_unique
    assert frame[roles['x']].to_numpy() == pytest.approx([10, 20])
    assert frame[roles['y']].to_numpy() == pytest.approx([1, 2])
    assert any(np.array_equal(frame[name].to_numpy(), [.1, .2]) for name in frame)
    if not quick:
        tidy = tidy_dataframe(p)
        y = tidy[tidy['quantity'] == roles['y']]
        assert y['x'].to_numpy() == pytest.approx([10, 20])
        assert y['value'].to_numpy() == pytest.approx([1, 2])


@pytest.mark.parametrize('inverse', [True, False])
def test_quick_export_writes_weights_and_their_semantics(tmp_path, inverse):
    import pandas as pd
    p = Project()
    c = Curve('weighted', [0, 1, 2], [1, 2, 3], weights=[1, 2, 3],
              weights_are_inverse_variance=inverse)
    p.add_curve(c)
    [path] = export_spectra(p, tmp_path, [c.id])
    frame = pd.read_csv(path, sep='\t')
    assert frame['weight'].to_numpy() == pytest.approx([1, 2, 3])
    assert (frame['weights_are_inverse_variance'] == int(inverse)).all()


def test_individual_baselines_retain_complete_statistics_without_batch_aggregation():
    curves = [Curve(str(i), np.arange(5.), np.array([0, 1, 1, 2, 3]) + i) for i in range(2)]
    models = {c.id: Model(components=[Component.create('constant')]) for c in curves}
    batch = Fitter().fit(FitPlan([c.id for c in curves]), curves, models)
    for c in curves:
        baseline = baseline_for_curve(batch, c.id)
        single = Fitter().fit_single(c, models[c.id])
        for key in ('N', 'k', 'degrees_of_freedom', 'chi_square', 'reduced_chi_square', 'AIC', 'AICc', 'BIC'):
            assert baseline.statistics[key] == pytest.approx(single.statistics[key])
        assert baseline_for_curve(single, c.id).statistics == single.statistics


def beta_script():
    path = Path('.github/scripts/beta_release.py')
    spec = importlib.util.spec_from_file_location('second_audit_beta', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
