"""Behavior and allocation contracts identified by the October 2026 audit."""
from __future__ import annotations

import ast

import numpy as np
import pytest

from curvemole import Component, Curve, Project, Transformation
from curvemole.cli import EXIT_DATA, main
from curvemole.core.expressions import SafeExpression
from curvemole.core.fitting import FitPlan, Fitter
from curvemole.core.importers import ColumnMapping, import_file, inspect_file
from curvemole.core.matrices import BlockDiagonalMatrix
from curvemole.core.serialization import load_project, save_project
from curvemole.core.workflow import dump_workflow, run_workflow


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


@pytest.mark.parametrize('delimiter', [',', ';', '\t'])
def test_workflow_roundtrip_retains_import_mapping(tmp_path, delimiter):
    source = tmp_path / 'input data.txt'
    source.write_text('\n'.join(delimiter.join(row) for row in [('x','a','b'), ('0','2','3'), ('1','4','5'), ('2','6','7')]))
    project = Project('import roundtrip')
    for index, curve in enumerate(import_file(source, ColumnMapping(x=0, y=[1, 2]))):
        curve.name = f'curve {index}'
        project.add_curve(curve)
    restored = run_workflow(dump_workflow(project, tmp_path / 'workflow.yaml')).project
    for original, replay in zip(project.curves, restored.curves, strict=True):
        np.testing.assert_array_equal(original.x, replay.x)
        np.testing.assert_array_equal(original.y, replay.y)


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


def test_independent_covariance_stays_blocked_in_archive(tmp_path):
    project = Project('independent')
    for i in range(5):
        curve = Curve(str(i), np.arange(12.), np.arange(12.) * (i + 1) + .01)
        project.add_curve(curve)
        project.model_for(curve.id).add(Component.create('linear'))
    result = Fitter().fit(FitPlan([c.id for c in project.curves]), project.curves, project.models)
    assert isinstance(result.covariance, BlockDiagonalMatrix)
    assert sum(b.size for b in result.covariance.blocks) == 5 * 4
    np.testing.assert_array_equal(result.covariance.submatrix([0, 3])[0, 1], 0)
    project.results['last_fit'] = result
    restored = load_project(save_project(project, tmp_path / 'blocks.fitproj')).results['last_fit']
    assert isinstance(restored.covariance, BlockDiagonalMatrix)
    np.testing.assert_allclose(np.asarray(restored.covariance), np.asarray(result.covariance))


def test_desktop_points_size_five_and_live_snapshot():
    from PySide6.QtWidgets import QApplication

    from curvemole.gui.app import create_main_window
    from curvemole.gui.live_fit_refresh import refresh_snapshot
    app = QApplication.instance() or QApplication([])
    project = Project('display')
    curve = Curve('points', np.arange(10.), np.ones(10))
    project.add_curve(curve)
    component = Component.create('constant', initial={'offset': 2.})
    model = project.model_for(curve.id)
    model.add(component)
    window = create_main_window(project)
    workspace = window.plot_workspace
    workspace.set_plot_appearance({'data_style': 'points', 'function_style': 'points',
                                   'data_point_size': 5, 'function_point_size': 5})
    assert workspace._data_items[curve.id].scene() is not None
    assert workspace._sum_items[curve.id].scene() is not None
    values = project.resolved_parameter_values()
    values[model.parameter_path(curve.id, component.id, 'offset')] = 7.
    refresh_snapshot(window, values)
    np.testing.assert_allclose(workspace._sum_items[curve.id].getOriginalDataset()[1], 7.)
    assert component.parameters['offset'].value == 2.
    window.project.dirty = False
    window.close()
    app.processEvents()


def test_dense_error_geometry_is_bounded_and_keeps_extrema():
    from PySide6.QtWidgets import QApplication

    from curvemole.gui.data_errors import DenseErrorBars, error_bar_item
    app = QApplication.instance() or QApplication([])
    x = np.linspace(0, 1, 100_000)
    error = np.ones(len(x))
    error[123] = 100.
    curve = Curve('dense', x, np.zeros(len(x)), sigma_y=error)
    item = error_bar_item(curve, curve.x, curve.y, np.ones(len(x), dtype=bool), '#000000')
    assert isinstance(item, DenseErrorBars)
    xx, yy = item.getOriginalDataset()
    assert len(xx) <= 3000
    assert np.nanmin(yy) == -100.
    assert np.nanmax(yy) == 100.
    app.processEvents()


def test_export_evaluates_only_requested_model_quantities(monkeypatch, tmp_path):
    from curvemole.core.export import ExportSelection, wide_dataframe
    from curvemole.core.functions import FunctionDefinition
    from curvemole.core.spectrum_export import SpectrumExportOptions, export_spectra
    project = Project('export calls')
    for i in range(3):
        curve = Curve(str(i), np.arange(5.), np.ones(5))
        project.add_curve(curve)
        background = Component.create('constant')
        background.is_background = True
        factor = Component.create('constant', operator='multiply')
        project.model_for(curve.id).components = [background, factor]
    calls = []
    original = FunctionDefinition.evaluate
    def evaluate(self, *args, **kwargs):
        calls.append(self.identifier)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(FunctionDefinition, 'evaluate', evaluate)
    curve = project.curves[0]
    model = project.models[curve.id]
    wide_dataframe(curve, model, selection=ExportSelection(total_fit=False, residual=False, background=False, components=False))
    assert calls == []
    wide_dataframe(curve, model)
    assert len(calls) == 2
    resolutions = []
    original_resolve = Project.resolved_parameter_values
    def resolve(self):
        resolutions.append(1)
        return original_resolve(self)
    monkeypatch.setattr(Project, 'resolved_parameter_values', resolve)
    export_spectra(project, tmp_path, [c.id for c in project.curves], options=SpectrumExportOptions())
    assert len(resolutions) == 1


def test_automatic_update_opt_out_does_not_block_manual_action(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from curvemole.gui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    controller = window._release_update_controller
    calls = []
    class Finished:
        def connect(self, callback):
            pass
    class Reply:
        finished = Finished()
    class Manager:
        def get(self, request):
            calls.append(request.url().toString())
            return Reply()
    controller.manager = Manager()
    monkeypatch.setenv('CURVEMOLE_DISABLE_UPDATE_CHECK', 'true')
    controller.check()
    assert not calls
    controller.check(force=True)
    assert len(calls) == 1
    controller._release_reply = None
    window.close()
    app.processEvents()


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


def test_worker_progress_publishes_changing_values_without_mutating_project(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from curvemole.core import live_fit_progress
    from curvemole.gui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(live_fit_progress, 'LIVE_REFRESH_EVERY', 1)
    project = Project('worker snapshot')
    curve = Curve('constant', np.arange(20.), np.full(20, 3.))
    project.add_curve(curve)
    component = Component.create('constant', initial={'offset': 0.})
    model = project.model_for(curve.id)
    model.add(component)
    path = model.parameter_path(curve.id, component.id, 'offset')
    window = MainWindow(project)
    seen = []
    def synchronous(operation, finished, status, partial=None):
        def publish(item):
            partial(item)
            if isinstance(item, dict):
                seen.append(float(window.plot_workspace._sum_items[curve.id].getOriginalDataset()[1][0]))
                assert component.parameters['offset'].value == 0.
        result = operation(lambda *_: None, publish)
        assert result.success
        # Inspect state before delivering the final result to the GUI.
    monkeypatch.setattr(window, '_run_background', synchronous)
    window._run_fit(FitPlan([curve.id]))
    assert any(value > 1. for value in seen)
    assert project.resolved_parameter_values()[path] == 0.
    window._reset_task_state()
    project.dirty = False
    window.close()
    app.processEvents()


def test_prepared_link_order_invalidates_on_expression_changes():
    from curvemole.core.parameters import EqualityParameterResolver, Parameter
    source = Parameter('source', 2.)
    linked = Parameter('linked', 0., link='${source} * 2')
    resolver = EqualityParameterResolver({'linked': linked, 'source': source})
    assert resolver.resolve()['linked'] == 4.
    source.value = 3.
    assert resolver.resolve()['linked'] == 6.
    linked.link = '${source} * 3'
    assert resolver.resolve()['linked'] == 9.
