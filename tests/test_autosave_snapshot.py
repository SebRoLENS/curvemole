from concurrent.futures import ThreadPoolExecutor
from threading import Event

import numpy as np
import pytest

from curvemole import Component, Curve, Project
from curvemole.core.data import Transformation
from curvemole.core.recovery import RecoveryManager
from curvemole.core.serialization import capture_project_snapshot, load_project, save_project


def test_snapshot_shares_original_data_but_detaches_all_mutable_archive_state(tmp_path):
    project = Project("Snapshot")
    curve = Curve("Spectrum", np.arange(30.), np.arange(30.),
                  sigma_y=np.ones(30), original_columns={"aux": np.arange(30.) + 1})
    project.add_curve(curve)
    operand = np.full(30, 2.)
    curve.apply_transformation(Transformation("replace_y", operand=operand))
    curve.mask_interval(3, 5)
    component = Component.create("constant", initial={"offset": 7.})
    project.model_for(curve.id).add(component)
    project.results["values"] = np.array([1., 2.])
    project.ui_state["nested"] = {"value": [1]}
    project.notebook.notes = "Before"
    snapshot = capture_project_snapshot(project)
    arrays = dict(snapshot.arrays)
    assert arrays[f"data/{curve.id}/original_x.npy"] is curve.original_x
    assert arrays[f"data/{curve.id}/original_y.npy"] is curve.original_y
    assert arrays[f"data/{curve.id}/sigma_y.npy"] is curve.sigma_y
    assert arrays[f"data/{curve.id}/columns/0.npy"] is curve.original_columns["aux"]

    curve.masks[curve.active_mask].excluded[:] = False
    operand[:] = 100
    curve.apply_transformation(Transformation("y_add", parameters={"value": 10}))
    component.parameters["offset"].value = 99
    project.results["values"][:] = 99
    project.ui_state["nested"]["value"].append(2)
    project.notebook.notes = "After"
    project.touch()
    project.add_curve(Curve("Later", [0, 1], [2, 3]))
    save_project(snapshot, tmp_path / "snapshot.fitproj", update_project_path=False)
    recovered = load_project(tmp_path / "snapshot.fitproj")
    assert len(recovered.curves) == 1
    np.testing.assert_array_equal(recovered.curves[0].y, np.full(30, 2.))
    assert recovered.curves[0].effective_mask[3:6].all()
    assert recovered.models[curve.id].components[0].parameters["offset"].value == 7
    assert recovered.results["values"] == [1., 2.]
    assert recovered.ui_state["nested"]["value"] == [1]
    assert recovered.notebook.notes == "Before"
    assert project.dirty and project.path is None
    assert snapshot.revision < project.revision


def test_snapshot_keeps_redo_operands_and_asymmetric_errors(tmp_path):
    project = Project()
    curve = Curve("Errors", np.arange(20.), np.arange(20.),
                  error_y_minus=np.ones(20), error_y_plus=np.full(20, 2.))
    project.add_curve(curve)
    curve.apply_transformation(Transformation("replace_y", operand=np.full(20, 5.)))
    curve.undo_transformation()
    snapshot = capture_project_snapshot(project)
    curve.redo_transformations[0].operand[:] = 100
    save_project(snapshot, tmp_path / "redo.fitproj", update_project_path=False)
    recovered = load_project(tmp_path / "redo.fitproj").curves[0]
    recovered.redo_transformation()
    np.testing.assert_array_equal(recovered.y, np.full(20, 5.))
    np.testing.assert_array_equal(recovered.error_y_minus, np.ones(20))
    np.testing.assert_array_equal(recovered.error_y_plus, np.full(20, 2.))


def test_readonly_operand_view_with_mutable_backing_is_copied(tmp_path):
    project = Project()
    curve = Curve("Spectrum", np.arange(20.), np.arange(20.))
    project.add_curve(curve)
    backing = np.full(20, 5.)
    view = backing.view()
    view.setflags(write=False)
    curve.apply_transformation(Transformation("replace_y", operand=view))
    snapshot = capture_project_snapshot(project)
    backing[:] = 100
    save_project(snapshot, tmp_path / "view.fitproj", update_project_path=False)
    np.testing.assert_array_equal(load_project(tmp_path / "view.fitproj").curves[0].y, np.full(20, 5.))


def test_clear_invalidates_an_in_flight_save_without_publishing_a_backup(tmp_path, monkeypatch):
    from curvemole.core import recovery

    manager = RecoveryManager(tmp_path)
    project = Project()
    project.touch()
    snapshot = capture_project_snapshot(project)
    entered, release = Event(), Event()
    original = recovery.save_project

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(recovery, "save_project", paused)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(manager.autosave, snapshot, generation=manager.generation(project.id))
        try:
            assert entered.wait(10)
            assert manager.candidates() == []
            manager.clear(project.id)
        finally:
            release.set()
        assert future.result(timeout=10) is None
    assert list(tmp_path.iterdir()) == []
    assert manager.needs_autosave(project)


def test_request_invalidated_before_worker_starts_never_writes(tmp_path, monkeypatch):
    manager = RecoveryManager(tmp_path)
    project = Project()
    project.touch()
    snapshot = capture_project_snapshot(project)
    generation = manager.generation(project.id)
    manager.clear(project.id)
    monkeypatch.setattr("curvemole.core.recovery.save_project",
                        lambda *args, **kwargs: pytest.fail("Stale queued request wrote a file"))
    assert manager.autosave(snapshot, generation=generation) is None


def test_failed_save_keeps_previous_backups_and_allows_retry(tmp_path, monkeypatch):
    from curvemole.core import recovery

    project = Project()
    project.touch()
    manager = RecoveryManager(tmp_path)
    previous = manager.autosave(project)
    project.notebook.notes = "New edits"
    project.touch()
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise OSError("Disk full")
        patch.setattr(recovery, "save_project", fail)
        with pytest.raises(OSError, match="Disk full"):
            manager.autosave(capture_project_snapshot(project))
    assert list(tmp_path.iterdir()) == [previous]
    assert manager.needs_autosave(project)
    newest = manager.autosave(capture_project_snapshot(project))
    assert manager.candidates() == [newest, previous]
