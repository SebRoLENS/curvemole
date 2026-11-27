"""Regression tests for gui (formerly grouped by audit)."""
from __future__ import annotations

import copy
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication, QMessageBox

from curvemole import Component, Curve, Fitter, Project, Series
from curvemole.core.data import Dataset
from curvemole.core.errors import DataValidationError
from curvemole.core.fitting import (
    FitMode,
    FitPlan,
)
from curvemole.core.project_handoff import file_digest, reply_to_request
from curvemole.core.serialization import ProjectLock, save_project
from curvemole.core.state import copy_result_maps
from curvemole.core.uncertainty import ResamplingResult
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.edit_function_points import editable_points
from curvemole.gui.updates import ReleaseAsset, UpdateController


def project_with_curves(count=3):
    project = Project()
    for i in range(count):
        curve = Curve(f"Data {i}", np.linspace(-5., 5., 101), np.full(101, i + 1.))
        project.add_curve(curve)
        project.model_for(curve.id).add(Component.create("constant", initial={"offset": i + 1.}))
    return project

@pytest.fixture
def window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    project = project_with_curves()
    window = CurveMoleMainWindow(project)
    window.show()
    app.processEvents()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    yield window
    window.plot_workspace.cancel_placement()
    project.dirty = False
    window.close()
    app.processEvents()

def link_to(project, target, source):
    src = project.model_for(source.id).components[0]
    dst = project.model_for(target.id).components[0]
    dst.parameters["offset"].link = f"${{{source.id}.{src.id}.offset}}"

@pytest.fixture
def app():
    application = QApplication.instance() or QApplication([])
    yield application
    application.processEvents()

@pytest.fixture
def window_second_audit_gui():
    app = QApplication.instance() or QApplication([])
    instance = CurveMoleMainWindow()
    yield instance
    instance._cancel_project_transfer()
    instance.project.dirty = False
    instance.close()
    app.processEvents()

def prepare_transfer(window_second_audit_gui, tmp_path):
    path = save_project(Project('confirmed'), tmp_path / 'shared.fitproj')
    digest = file_digest(path)
    request = dict(request_id='audit', owner_session='old', requester_session='new', created_at=time.time())
    reply_to_request(path, request, accepted=True, digest=digest)
    window_second_audit_gui.project.path = path
    window_second_audit_gui.project.read_only = True
    window_second_audit_gui._transfer_request = request
    window_second_audit_gui._transfer_path = path
    window_second_audit_gui._transfer_monitor.stop()
    return path, digest

def prepare_transfer_second_audit_gui(window_second_audit_gui, tmp_path):
    path = save_project(Project('confirmed'), tmp_path / 'shared.fitproj')
    digest = file_digest(path)
    request = dict(request_id='audit', owner_session='old', requester_session='new', created_at=time.time())
    reply_to_request(path, request, accepted=True, digest=digest)
    window_second_audit_gui.project.path = path
    window_second_audit_gui.project.read_only = True
    window_second_audit_gui._transfer_request = request
    window_second_audit_gui._transfer_path = path
    window_second_audit_gui._transfer_monitor.stop()
    return path, digest


@pytest.mark.parametrize("mode", [FitMode.INDEPENDENT, FitMode.GLOBAL])
def test_curve_removal_undo_restores_all_analysis_maps_and_array_identity(window, mode):
    project = window.project
    result = Fitter().fit(FitPlan([c.id for c in project.curves], mode), project.curves, project.models)
    window._fit_finished(result)
    curve = project.curves[0]
    for key in ("uncertainty_by_curve", "uncertainty_reports_by_curve", "uncertainty_failures_by_curve"):
        project.results[key] = {curve.id: {}}
    saved = copy_result_maps(project.results)
    window.curve_tree.selected_curve_ids = lambda: {curve.id}
    for _ in range(2):
        window.remove_selected_curves()
        assert curve.id not in project.results["fit_by_curve"]
        window.undo_stack.undo()
        assert curve.id in project.results["fit_by_curve"]
        for key in ("fit_by_curve", "global_fit_baselines", "uncertainty_by_curve", "uncertainty_reports_by_curve", "uncertainty_failures_by_curve"):
            assert project.results.get(key, {}).keys() == saved.get(key, {}).keys()
            for identity, value in saved.get(key, {}).items():
                actual = project.results[key][identity]
                if key.startswith("uncertainty_"):
                    assert actual == value
                    for method, record in value.items():
                        assert actual[method] is record
                else:
                    assert actual is value
        assert project.results["last_fit"] is result
        assert project.dataset.curve(curve.id).original_x is curve.original_x

def test_model_edit_uses_destination_and_transitive_dependencies(window):
    from curvemole.core.data import CurveState
    project = window.project
    a, b, c = project.curves
    link_to(project, c, b)
    window.curve_tree.selected_curve_ids = lambda: {a.id}
    for curve in project.curves:
        curve.state = CurveState.FITTED
    before = copy.deepcopy(project.model_for(b.id).to_dict())
    after = copy.deepcopy(before)
    after["components"][0]["parameters"]["offset"]["value"] = 5.
    window._push_model_state(b.id, before, after, "Edit B")
    assert a.state == CurveState.FITTED
    assert b.state == c.state == CurveState.MODIFIED
    window.undo_stack.undo()
    assert project.model_for(b.id).components[0].parameters["offset"].value == 2.

def test_linked_point_editor_uses_effective_shape_and_keeps_link_on_commit(window):
    project = window.project
    a, b, _ = project.curves
    source = project.model_for(a.id).components[0]
    source.parameters["offset"].value = 3.
    peak = Component.create("gaussian", initial={"center": 0., "sigma": .5})
    peak.parameters["center"].link = f"${{{a.id}.{source.id}.offset}}"
    project.model_for(b.id).components = [peak]
    window._set_active_curve(b.id)
    points = editable_points(peak, window.registry, values=project.resolved_parameter_values(), curve_id=b.id)
    assert np.mean([x for x, y in points]) == pytest.approx(3.)
    window.edit_component_points(peak.id)
    assert np.mean([x for x, y in window.plot_workspace._spline_points]) == pytest.approx(3.)
    selected = [(x, y * 1.2) for x, y in points]
    window._function_point_editor.finish(selected)
    assert not window._function_point_editor.active
    updated = project.model_for(b.id).component(peak.id)
    assert updated.parameters["center"].link == peak.parameters["center"].link
    assert updated.parameters["center"].value == pytest.approx(3.)
    window.undo_stack.undo()
    assert project.model_for(b.id).component(peak.id).parameters["center"].value == 0.

def test_rendering_reports_invalid_link_once_and_recovers(window, monkeypatch):
    curve = window.project.curves[0]
    component = window.project.model_for(curve.id).components[0]
    component.is_background = True
    notifications = []
    monkeypatch.setattr(window, "_notify", lambda message, **kwargs: notifications.append(message))
    component.parameters["offset"].link = "${missing.component.offset}"
    workspace = window.plot_workspace
    for _ in range(3):
        workspace.refresh()
    assert curve.id in workspace.render_controller.errors
    assert len(notifications) == 1
    component.parameters["offset"].link = None
    workspace.refresh()
    assert curve.id not in workspace.render_controller.errors

def test_series_removal_undo_restores_global_fit_states(window):
    from curvemole.core.data import CurveState, Series
    project = window.project
    a, b, _ = project.curves
    separate = Series("Separate")
    project.dataset.add_series(separate)
    project.dataset.transfer_curve(b.id, separate.id)
    result = Fitter().fit(FitPlan([c.id for c in project.curves], FitMode.GLOBAL), project.curves, project.models)
    window._fit_finished(result)
    window.delete_series(separate.id)
    assert a.state == CurveState.MODIFIED
    window.undo_stack.undo()
    assert all(c.state == CurveState.FITTED for c in project.curves)
    assert b.id in project.results["fit_by_curve"]

@pytest.mark.parametrize("failure", ["exception", "nonfinite"])
def test_render_controller_handles_plugin_evaluation_errors_without_retry(window, monkeypatch, failure):
    curve = window.project.curves[0]
    window.plot_workspace.display_mode.setCurrentIndex(0)
    definition = window.registry.get("constant")
    calls = []
    def evaluate(x, p, metadata):
        calls.append(len(x))
        if failure == "exception":
            raise ValueError("Plugin evaluation failed")
        return np.full_like(x, np.nan)
    monkeypatch.setattr(definition, "evaluator", evaluate)
    window.plot_workspace.refresh()
    assert curve.id in window.plot_workspace.render_controller.errors
    assert calls == [len(curve)]

def test_automatic_colours_skip_a_colour_chosen_by_the_processor():
    from curvemole.gui.colours import SERIES_PALETTES
    from curvemole.gui.folder_import import _colour_imports

    palette = SERIES_PALETTES["Neon"]
    custom = Curve("explicit", [0, 1], [1, 2], colour=palette[1])
    automatic = Curve("automatic", [0, 1], [1, 2])
    _colour_imports([custom, automatic], palette)
    assert custom.colour == palette[1]
    assert automatic.colour == palette[0]

def test_open_reads_after_confirmation_and_preserves_failed_open_session(
    app, tmp_path, monkeypatch
):
    path = tmp_path / "target.fitproj"
    save_project(Project("old"), path)
    window = CurveMoleMainWindow()

    def confirm():
        save_project(Project("latest"), path)
        return True

    monkeypatch.setattr(window, "_confirm_discard_or_save", confirm)
    window.open_project(path)
    assert window.project.name == "latest"
    assert window._project_disk_digest == file_digest(path)
    lock = window._project_lock
    errors = []
    monkeypatch.setattr(window, "_show_error", lambda *args: errors.append(args))
    window.open_project(tmp_path / "missing.fitproj")
    assert (
        errors and window.project.name == "latest" and window._project_lock is lock and lock.owns()
    )
    window.project.dirty = False
    window.close()

def test_new_project_clears_custom_layer(app, monkeypatch):
    p = Project(custom_functions=[{"identifier": "audit_project_only", "formula": "amplitude*x"}])
    window = CurveMoleMainWindow(p)
    assert "audit_project_only" in window.registry.identifiers()
    monkeypatch.setattr(window, "_confirm_discard_or_save", lambda: True)
    window.new_project()
    assert "audit_project_only" not in window.registry.identifiers()
    window.close()

def test_project_loading_processes_gui_events_and_cancellation(app):
    from curvemole.core.errors import FitCancelled
    from curvemole.gui.project_loading import load_project_responsive

    window = CurveMoleMainWindow()
    progressed = []

    def loader(path, cancellation):
        assert path == "test"
        import time

        for _ in range(200):
            cancellation.raise_if_cancelled()
            time.sleep(0.001)
        return Project("done")

    old_project = window.project

    def during_load():
        assert not window._can_replace_project()
        assert not window._ensure_editable()
        window.new_project()
        progressed.append(True)

    QTimer.singleShot(15, during_load)
    result = load_project_responsive(window, "test", loader)
    assert result.name == "done" and progressed
    assert window.project is old_project
    assert not window._project_loading

    def cancel_loader(path, cancellation):
        cancellation.cancel()
        cancellation.raise_if_cancelled()

    with pytest.raises(FitCancelled):
        load_project_responsive(window, "test", cancel_loader)
    window.close()

@pytest.mark.parametrize("digest", ["", "md5:1234", "sha256:short"])
def test_update_cannot_reach_installer_without_supported_digest(tmp_path, monkeypatch, digest):
    warnings = []
    monkeypatch.setattr(
        "curvemole.gui.updates.QMessageBox.warning", lambda *args: warnings.append(args)
    )
    path = tmp_path / "download"
    path.write_bytes(b"not an executable")
    installed = []
    stub = SimpleNamespace(
        _download_path=path,
        _download_asset=ReleaseAsset("x", "https://example.invalid", digest),
        _download_version="1.0.0",
        _download_handle=None,
        _drain_download=lambda: None,
        _install_download=lambda *args: installed.append(True),
        window=SimpleNamespace(
            tr=lambda s: s,
            _log=lambda s: None,
            progress=SimpleNamespace(setVisible=lambda v: None),
            fit_action=SimpleNamespace(setEnabled=lambda v: None),
        ),
    )
    reply = SimpleNamespace(
        error=lambda: QNetworkReply.NetworkError.NoError, deleteLater=lambda: None
    )
    UpdateController._download_finished(stub, reply)
    assert warnings and not installed and not path.exists()

def test_uncertainty_report_never_materializes_sample_lists(app, monkeypatch):
    class NoListArray(np.ndarray):
        def tolist(self):
            raise AssertionError("Unnecessary sample conversion")

    window = CurveMoleMainWindow()
    c = Curve("c", [0, 1, 2, 3], [1, 2, 1, 2])
    window.project.add_curve(c)
    from curvemole import Component, Fitter

    window.project.add_component(c.id, Component.create("constant"))
    baseline = Fitter().fit_single(c, window.project.model_for(c.id))
    samples = np.ones((10, 1)).view(NoListArray)
    result = ResamplingResult("residual_bootstrap", 10, 10, 0, 1, ["p"], samples, {}, 0.95, {})
    monkeypatch.setattr(window, "_sync_uncertainty_method", lambda: None)
    window._store_uncertainty_result(c.id, baseline, result)
    assert (
        "samples"
        not in window.project.results["uncertainty_reports_by_curve"][c.id]["residual_bootstrap"][
            "analysis"
        ]
    )
    window.project.dirty = False
    window.close()

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

def test_worker_progress_publishes_changing_values_without_mutating_project(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from curvemole.core import live_fit_progress
    from curvemole.gui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(live_fit_progress, 'LIVE_REFRESH_EVERY', 1)
    monkeypatch.setattr(live_fit_progress, 'LIVE_PREVIEW_SECONDS', 0.)
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

def test_import_conflict_is_rejected_before_push_and_preserves_original(window_second_audit_gui):
    original = Series('original', [Curve('old', [0, 1], [1, 2])])
    window_second_audit_gui.project.add_series(original)
    revision = window_second_audit_gui.project.revision
    new = Series('partial', [Curve('new', [0, 1], [3, 4])])
    collision = Series('collision', [Curve('new2', [0, 1], [5, 6])], id=original.id)
    acquisition = SimpleNamespace(dataset=Dataset([new, collision]), models={}, results={})
    with pytest.raises(DataValidationError):
        window_second_audit_gui.folder_import.commit(acquisition)
    assert window_second_audit_gui.project.dataset.series == [original]
    assert window_second_audit_gui.project.revision == revision
    assert window_second_audit_gui.undo_stack.count() == 0
    window_second_audit_gui.undo_stack.undo()
    assert window_second_audit_gui.project.curves == original.curves

def test_import_undo_redo_restores_only_the_imported_lot_and_handles_empty_tail(window_second_audit_gui):
    original = Series('original', [Curve('old', [0, 1], [1, 2])])
    window_second_audit_gui.project.add_series(original)
    curve = Curve('new', [0, 1], [3, 4])
    imported = Series('imported', [curve])
    acquisition = SimpleNamespace(dataset=Dataset([imported, Series('empty tail')]), models={}, results={})
    window_second_audit_gui.folder_import.follow = True
    window_second_audit_gui.folder_import.commit(acquisition)
    assert len(window_second_audit_gui.project.curves) == 2 and window_second_audit_gui.active_curve_id == curve.id
    window_second_audit_gui.undo_stack.undo()
    assert window_second_audit_gui.project.dataset.series == [original]
    assert curve.id not in window_second_audit_gui.project.models
    window_second_audit_gui.undo_stack.redo()
    assert len(window_second_audit_gui.project.curves) == 2 and window_second_audit_gui.active_curve_id == curve.id
    assert original.curves[0].id in window_second_audit_gui.project.models and curve.id in window_second_audit_gui.project.models

def test_handoff_rejects_replacement_after_lock_without_replacing_session(window_second_audit_gui, tmp_path, monkeypatch):
    path, digest = prepare_transfer(window_second_audit_gui, tmp_path)
    original = window_second_audit_gui.project
    replacement = save_project(Project('unconfirmed'), tmp_path / 'replacement.fitproj')
    class InterleavedLock(ProjectLock):
        def __enter__(self):
            result = super().__enter__()
            replacement.replace(path)
            return result
    monkeypatch.setattr('curvemole.gui.project_session.ProjectLock', InterleavedLock)
    window_second_audit_gui._poll_project_transfer()
    assert window_second_audit_gui.project is original and window_second_audit_gui.project.read_only
    assert window_second_audit_gui._project_lock is None and ProjectLock.owner(path) is None
    assert file_digest(path) != digest
    assert window_second_audit_gui._transfer_request is not None

def test_handoff_rejects_replacement_during_read_and_keeps_ui_responsive(window_second_audit_gui, tmp_path, monkeypatch):
    import curvemole.gui.project_session as main
    path, _ = prepare_transfer_second_audit_gui(window_second_audit_gui, tmp_path)
    original = window_second_audit_gui.project
    real_loader = main.load_project
    progressed = []
    def interleaved_loader(source, **kwargs):
        time.sleep(.04)
        project = real_loader(source, **kwargs)
        save_project(Project('unconfirmed'), source)
        return project
    monkeypatch.setattr(main, 'load_project', interleaved_loader)
    QTimer.singleShot(10, lambda: progressed.append(True))
    window_second_audit_gui._poll_project_transfer()
    assert progressed and window_second_audit_gui.project is original
    assert window_second_audit_gui.project.read_only and window_second_audit_gui._project_lock is None
    assert not window_second_audit_gui._project_loading
