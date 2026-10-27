"""Behavioral regressions for the eleven findings in the October beta audit."""
from __future__ import annotations

import copy
from concurrent.futures import Future
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from curvemole import Component, Curve, Project
from curvemole.core.calculator import apply_custom_formula
from curvemole.core.errors import ConstraintError, DataValidationError, ExpressionError
from curvemole.core.fit_records import baseline_for_curve
from curvemole.core.fitting import CancellationToken, FitMode, FitPlan, Fitter, _Problem
from curvemole.core.importers import ColumnMapping, import_file
from curvemole.core.matrices import BlockDiagonalMatrix
from curvemole.core.models import Model
from curvemole.core.parameters import Parameter
from curvemole.core.process_pool import bounded_results
from curvemole.core.registry import default_registry
from curvemole.core.state import copy_result_maps
from curvemole.core.workflow import dump_workflow, run_workflow
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.edit_function_points import editable_points


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


@pytest.mark.parametrize("count", [100, 101])
@pytest.mark.parametrize("selection", ["mask", "ranges"])
@pytest.mark.parametrize("descending", [False, True])
def test_convolution_selects_residuals_without_changing_model(count, selection, descending):
    x = np.linspace(-5., 5., count)
    if descending:
        x = x[::-1]
    model = Model(components=[Component.create("gaussian", initial={"center": .5, "sigma": .5}),
                              Component.create("gaussian", operator="convolve", initial={"sigma": .4})])
    curve = Curve("Convolution", x, model.evaluate(x))
    if selection == "mask":
        curve.masks[curve.active_mask].excluded[(x > -.3) & (x < .3)] = True
    else:
        curve.fit_ranges = [(-4., -1.), (1., 4.)]
    problem = _Problem([curve], {curve.id: model}, FitPlan([curve.id]),
                       default_registry(), CancellationToken(), None)
    np.testing.assert_allclose(problem.residual(problem.initial), 0., atol=1e-14)
    values = problem.values(problem.initial)
    output = problem.outputs(values)[curve.id]
    np.testing.assert_allclose(output.fitted, model.evaluate(curve.x)[output.indices])


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


def test_baseline_extracts_blocks_without_dense_conversion():
    project = project_with_curves()
    result = Fitter().fit(FitPlan([c.id for c in project.curves]), project.curves, project.models)
    reference = np.asarray(result.covariance)
    class BlocksOnly(BlockDiagonalMatrix):
        def __array__(self, *args, **kwargs):
            raise AssertionError("An independent baseline must never allocate the full matrix")
    result.covariance = BlocksOnly(result.covariance.blocks)
    result.correlation = BlocksOnly(result.correlation.blocks)
    for i, curve in enumerate(project.curves):
        baseline = baseline_for_curve(result, curve.id)
        np.testing.assert_array_equal(baseline.covariance, reference[np.ix_([i], [i])])


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


@pytest.mark.parametrize("names", [("first", "second"), ("same", "same")])
def test_workflow_round_trip_remaps_repeated_local_and_external_references(tmp_path, names):
    path = tmp_path / "data.csv"
    path.write_text("x,y\n0,1\n1,2\n2,3\n")
    project = Project()
    for name in names:
        curve = import_file(path, ColumnMapping(x=0, y=[1]))[0]
        curve.name = name
        project.add_curve(curve)
        project.model_for(curve.id).add(Component.create("constant", initial={"offset": 2.}))
    a, b = project.curves
    first = project.model_for(a.id).components[0]
    local = Component.create("constant")
    local.parameters["offset"].link = f"${{{a.id}.{first.id}.offset}} + ${{{a.id}.{first.id}.offset}}"
    local.parameters["offset"].link_reference_scopes = ["relative", "absolute"]
    project.model_for(a.id).add(local)
    link_to(project, b, a)
    project.model_for(b.id).components[0].parameters["offset"].link_scope = "absolute"
    workflow = dump_workflow(project, tmp_path / "workflow.yml")
    restored = run_workflow(workflow).project
    assert set(project.resolved_parameter_values().values()) == set(restored.resolved_parameter_values().values())
    for original, loaded in zip(project.curves, restored.curves, strict=True):
        assert original.id != loaded.id
        np.testing.assert_allclose(
            project.model_for(original.id).evaluate(original.x, curve_id=original.id, values=project.resolved_parameter_values()),
            restored.model_for(loaded.id).evaluate(loaded.x, curve_id=loaded.id, values=restored.resolved_parameter_values()))
    assert restored.model_for(restored.curves[0].id).component(local.id).parameters["offset"].link_reference_scopes == ["relative", "absolute"]
    # The exported identities also resolve the explicit global fit selection.
    import yaml
    payload = yaml.safe_load(workflow.read_text())
    payload["fit"] = {"mode": "global", "curves": [curve.id for curve in project.curves]}
    workflow.write_text(yaml.safe_dump(payload))
    fitted = run_workflow(workflow)
    assert fitted.result.success
    assert set(fitted.result.curve_outputs) == {curve.id for curve in fitted.project.curves}


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


def test_result_snapshot_detaches_method_maps_but_shares_finished_arrays():
    array = np.arange(100.)
    record = {"analysis": array}
    original = {"uncertainty_reports_by_curve": {"curve": {"covariance": record}}}
    saved = copy_result_maps(original)
    original["uncertainty_reports_by_curve"]["curve"]["new_method"] = {"analysis": np.ones(100)}
    assert set(saved["uncertainty_reports_by_curve"]["curve"]) == {"covariance"}
    assert saved["uncertainty_reports_by_curve"]["curve"]["covariance"]["analysis"] is array


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
