import copy

from curvemole import Project
from curvemole.core.history import CompactHistory


def test_completed_records_stay_compact_through_snapshots_and_streaming():
    project = Project()
    expected = [{"reason": "Fit", "result": {"values": list(range(100))}, "index": i}
                for i in range(100)]
    project.fit_history = CompactHistory(expected)
    original_buffers = list(project.fit_history._entries)
    assert all(isinstance(item, bytes) for item in original_buffers)
    assert list(project.fit_history.iter_records()) == expected
    snapshot = copy.deepcopy(project.fit_history)
    assert snapshot == expected
    assert all(a is b for a, b in zip(original_buffers, snapshot._entries, strict=True))
    assert all(isinstance(item, bytes) for item in project.fit_history._entries)
    assert sum(len(item) for item in original_buffers) < 32_000


def test_explicit_entry_edits_and_sequence_operations_keep_list_semantics():
    history = CompactHistory([{"value": 1}, {"value": 2}])
    history[0]["value"] = 3
    assert list(history.iter_records()) == [{"value": 3}, {"value": 2}]
    snapshot = history.copy()
    history[0]["value"] = 4
    assert snapshot[0]["value"] == 3
    mutable = {"value": 5}
    history.append(mutable)
    mutable["value"] = 6
    assert history[-1]["value"] == 6
    history[1:2] = [{"value": 7}, {"value": 8}]
    del history[0]
    assert history[:] == [{"value": 7}, {"value": 8}, {"value": 6}]
    history.clear()
    assert history == []


def test_non_json_python_extensions_are_preserved():
    record = {"tuple": (1, 2), "mapping": {1: "integer key"}}
    history = CompactHistory([record])
    assert history[0] is record
    cyclic = {}
    cyclic["self"] = cyclic
    history.append_record(cyclic)
    assert history[-1] is cyclic


def test_project_snapshot_compresses_history_without_dropping_records():
    project = Project()
    for i in range(20):
        project.snapshot("Fit", {"value": i})
    assert len(project.fit_history) == 20
    assert all(isinstance(item, bytes) for item in project.fit_history._entries)
    assert [record["value"] for record in project.fit_history.iter_records()] == list(range(20))


def test_shallow_copy_has_independent_sequence_and_shares_explicit_mutable_records():
    history = CompactHistory([{"value": 1}])
    shallow = copy.copy(history)
    shallow.append({"value": 2})
    assert len(history) == 1
    history[0]["value"] = 3
    other = copy.copy(history)
    other[0]["value"] = 4
    assert history[0]["value"] == 4
