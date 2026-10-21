import copy
import gc
import weakref
from types import SimpleNamespace

import numpy as np

from curvemole import Curve, Project
from curvemole.core.extensions import Contribution, extensions
from curvemole.gui.plugin_host import PluginContext, PluginHost
from curvemole.gui.plugin_services import PluginServices
from curvemole.gui.plugin_snapshots import ProjectSnapshot, ProjectSnapshotStore


def test_compact_snapshots_share_unchanged_fields_and_release_them():
    project = Project()
    project.add_curve(Curve("source", np.arange(1000.), np.arange(1000.)))
    project.results["samples"] = np.random.default_rng(1).normal(size=(1000, 20))
    store = ProjectSnapshotStore()
    before = store.capture(project)
    project.curves[0].name = "renamed"
    after = store.capture(project)

    assert before._fields["results"] is after._fields["results"]
    assert before._fields["dataset"] is not after._fields["dataset"]
    assert before.restore().curves[0].name == "source"
    assert after.restore().curves[0].name == "renamed"
    buffers = [weakref.ref(value) for value in before._fields.values()]
    del before, after
    gc.collect()
    assert not store._fields
    assert not store._arrays
    assert not any(ref() is not None for ref in buffers)


def test_snapshot_is_frozen_at_capture_and_arrays_never_share_live_storage():
    project = Project()
    curve = Curve("source", np.arange(5.), np.arange(5.))
    project.add_curve(curve)
    project.results["samples"] = np.arange(10.).reshape(2, 5)
    project.results["last_fit"] = project.results["samples"]
    snapshot = ProjectSnapshotStore().capture(project)
    project.results["samples"][0, 0] = 456
    restored = snapshot.restore()
    assert restored.results["samples"][0, 0] == 0
    assert restored.results["samples"] is restored.results["last_fit"]
    assert not restored.curves[0].original_x.flags.writeable
    assert not curve.original_x.flags.writeable
    assert not np.shares_memory(restored.curves[0].original_x, curve.original_x)
    restored.results["samples"][0, 0] = 123
    restored.curves[0]._y[0] = 789
    assert project.results["samples"][0, 0] == 456
    assert curve.y[0] == 0
    assert snapshot.restore().results["samples"][0, 0] == 0


def test_context_settings_do_not_expand_project_and_sync_before_materializing(monkeypatch):
    project = Project()
    project.ui_state["plugin_data"] = {"example": {"values": [1]}, "other": {"large": [2]}}
    context = PluginContext(ProjectSnapshotStore().capture(project), None, (), "example")
    original = ProjectSnapshot.restore
    calls = []

    def restore(snapshot):
        calls.append(True)
        return original(snapshot)

    monkeypatch.setattr(ProjectSnapshot, "restore", restore)
    settings = context.data
    settings["values"].append(3)
    assert calls == []
    assert project.ui_state["plugin_data"]["example"]["values"] == [1]
    assert context.project.ui_state["plugin_data"]["example"] is settings
    assert calls == [True]
    assert context.data is settings


def test_settings_service_and_undo_copy_only_owner_and_selected_metadata(monkeypatch):
    class DoNotCopy:
        def __deepcopy__(self, memo):
            raise AssertionError("Unrelated settings and metadata must not be copied")

    project = Project()
    curve = Curve("source", np.arange(5.), np.arange(5.))
    project.add_curve(curve)
    owner = "example"
    project.ui_state["plugin_data"] = {owner: {"values": [1]}, "other": DoNotCopy()}
    curve.metadata = {"own": {"value": 1}, "unrelated": DoNotCopy()}
    commands = []

    def push_change(text, redo, undo, **kwargs):
        commands.append((redo, undo))
        redo()

    window = SimpleNamespace(project=project, _thread=None,
                             plugin_manager=SimpleNamespace(errors={}), _push_change=push_change)
    monkeypatch.setattr(extensions, "entries", {
        owner + ":panel": Contribution(owner, owner + ":panel", "Example", "panels", lambda ctx: None)
    })
    service = PluginServices(SimpleNamespace(window=window), owner)
    settings = service.settings()
    settings["values"].append(2)
    assert project.ui_state["plugin_data"][owner]["values"] == [1]
    service.save_settings(settings, metadata_key="own", curve_metadata={curve.id: {"value": 2}})
    curve.metadata["another"] = "keep"
    commands[-1][1]()
    assert project.ui_state["plugin_data"][owner]["values"] == [1]
    assert curve.metadata["own"] == {"value": 1}
    assert curve.metadata["another"] == "keep"
    commands[-1][0]()
    assert curve.metadata["own"] == {"value": 2}


def test_replacement_undo_survives_project_recreation_and_detaches_metadata(monkeypatch):
    project = Project()
    curve = Curve("source", np.arange(5.), np.arange(5.))
    project.add_curve(curve)
    owner = "example"
    commands = []

    def push_change(text, redo, undo, **kwargs):
        commands.append((redo, undo))
        redo()

    window = SimpleNamespace(project=project, _thread=None,
                             plugin_manager=SimpleNamespace(errors={}), _push_change=push_change)
    monkeypatch.setattr(extensions, "entries", {
        owner + ":panel": Contribution(owner, owner + ":panel", "Example", "panels", lambda ctx: None)
    })
    service = PluginServices(SimpleNamespace(window=window), owner)
    metadata = {"intervals": [[1, 2]]}
    service.apply_y_replacement(curve.id, np.arange(5.)[::-1], metadata_key="own", metadata=metadata)
    metadata["intervals"].append([3, 4])
    window.project = copy.deepcopy(window.project)
    commands[-1][1]()
    assert window.project.curves[0].y.tolist() == [0, 1, 2, 3, 4]
    commands[-1][0]()
    assert window.project.curves[0].y.tolist() == [4, 3, 2, 1, 0]
    assert window.project.curves[0].metadata["own"]["intervals"] == [[1, 2]]


def test_plugin_commit_undo_and_redo_are_isolated_from_retained_callback_context():
    project = Project()
    curve = Curve("source", np.arange(5.), np.arange(5.))
    project.add_curve(curve)
    project.results["samples"] = np.arange(10.).reshape(2, 5)
    commands = []

    def push_change(text, redo, undo, **kwargs):
        commands.append((redo, undo))
        redo()

    window = SimpleNamespace(
        project=project, active_curve_id=curve.id, _thread=None,
        curve_tree=SimpleNamespace(selected_curve_ids=lambda: [curve.id]),
        _ensure_editable=lambda: True, _push_change=push_change, _notify=lambda *args: None,
        plugin_manager=SimpleNamespace(errors={}, installed={}),
    )
    host = object.__new__(PluginHost)
    host.window = window
    host._snapshots = ProjectSnapshotStore()
    captured = []

    def action(context):
        captured.append(context)
        context.project.curves[0].name = "renamed"

    entry = Contribution("example", "example:rename", "Rename", "actions", action)
    host.run(entry)
    captured[0].project.curves[0].name = "late edit"
    captured[0].project.results["samples"][0, 0] = 123
    assert window.project.curves[0].name == "renamed"
    assert window.project.results["samples"][0, 0] == 0
    window.project.results["samples"][0, 0] = 456
    commands[-1][1]()
    assert window.project.curves[0].name == "source"
    assert window.project.results["samples"][0, 0] == 0
    commands[-1][0]()
    assert window.project.curves[0].name == "renamed"
    assert window.project.results["samples"][0, 0] == 0
