import copy
import hashlib
import json
import struct
import zipfile

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Project
from curvemole.core.errors import ProjectFormatError
from curvemole.core.history import CompactHistory
from curvemole.core.serialization import (
    _json_safe,
    capture_project_snapshot,
    load_project,
    save_project,
    validate_project_archive,
)
from curvemole.core.uncertainty import ResamplingResult


def sample_project():
    project = Project("Compact storage")
    curve = Curve("data", np.arange(10.), np.ones(10))
    project.add_curve(curve)
    model = project.model_for(curve.id)
    model.add(Component.create("constant", initial={"offset": 1.}))
    fit = Fitter().fit_single(curve, model)
    project.results.update(last_fit=fit, last_attempt=fit)
    samples = np.random.default_rng(7).normal(size=(2000, 1))
    result = ResamplingResult("residual_bootstrap", 2000, 2000, 0, 7,
                              fit.free_parameter_paths, samples, {}, .95, {})
    project.results["uncertainty_by_curve"] = {curve.id: {"residual_bootstrap": result}}
    for index in range(100):
        project.snapshot("Fit", {"result": fit.to_dict(arrays=False), "index": index})
    return project, curve, samples


def test_results_are_binary_and_history_is_streamed_without_expanding_records(tmp_path):
    project, curve, samples = sample_project()
    destination = save_project(project, tmp_path / "compact.fitproj")
    assert validate_project_archive(destination) == []
    assert all(isinstance(record, bytes) for record in project.fit_history._entries)
    with zipfile.ZipFile(destination) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema_version"] == 3
        assert archive.getinfo("manifest.json").file_size < 15_000
        assert manifest["project"]["fit_history"] == {"storage": "history.jsonl", "count": 100}
        assert any(name.startswith("results/arrays/") for name in archive.namelist())
        assert not any(name.endswith((".pkl", ".pickle")) for name in archive.namelist())
    restored = load_project(destination)
    np.testing.assert_array_equal(restored.results["uncertainty_by_curve"][curve.id]
                                  ["residual_bootstrap"]["samples"], samples)
    first = restored.results["last_fit"].curve_outputs[curve.id].fitted
    assert first is restored.results["last_attempt"].curve_outputs[curve.id].fitted
    assert _json_safe(restored.fit_history) == _json_safe(project.fit_history)
    assert all(isinstance(record, bytes) for record in restored.fit_history._entries)


def test_legacy_numeric_samples_restore_as_arrays_and_keep_every_history_record(tmp_path):
    project = Project("legacy")
    samples = np.random.default_rng(11).normal(size=(1000, 2))
    project.results["uncertainty_by_curve"] = {"curve_old": {
        "residual_bootstrap": {"parameter_paths": ["a", "b"], "samples": samples.tolist()}}}
    project.fit_history = CompactHistory([{"reason": "Fit", "index": i} for i in range(200)])
    manifest = {"schema_version": 2, "checksums": {}, "project": _json_safe(project.to_metadata())}
    path = tmp_path / "old.fitproj"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
    restored = load_project(path)
    actual = restored.results["uncertainty_by_curve"]["curve_old"]["residual_bootstrap"]["samples"]
    assert isinstance(actual, np.ndarray) and actual.dtype == np.float64
    np.testing.assert_array_equal(actual, samples)
    assert restored.fit_history == project.fit_history


def test_snapshot_detaches_samples_and_materialised_history_and_portable_save_does_not_mutate_it(tmp_path):
    project, curve, samples = sample_project()
    curve.source = "/private/experiment/spectrum.csv"
    project.fit_history[0]["nested"] = {"value": 2}
    snapshot = capture_project_snapshot(project)
    samples[:] = 999
    project.fit_history[0]["nested"]["value"] = 3
    project.results["last_fit"].curve_outputs[curve.id].fitted[:] = 999
    before = copy.deepcopy(snapshot.metadata)
    path = save_project(snapshot, tmp_path / "snapshot.fitproj", portable=True, update_project_path=False)
    assert snapshot.metadata["fit_history"] == before["fit_history"]
    assert "path" not in snapshot.metadata
    assert snapshot.metadata["curves"][curve.id]["source"] == "/private/experiment/spectrum.csv"
    restored = load_project(path)
    assert restored.curves[0].source == "spectrum.csv"
    assert restored.fit_history[0]["nested"]["value"] == 2
    assert not np.any(restored.results["uncertainty_by_curve"][curve.id]
                      ["residual_bootstrap"]["samples"] == 999)
    assert not np.any(restored.results["last_fit"].curve_outputs[curve.id].fitted == 999)


def test_excluding_raw_samples_handles_live_resampling_results(tmp_path):
    project, curve, _samples = sample_project()
    path = save_project(project, tmp_path / "without.fitproj", include_uncertainty_samples=False)
    record = load_project(path).results["uncertainty_by_curve"][curve.id]["residual_bootstrap"]
    assert record["samples"] is None
    assert record["completed"] == 2000
    assert project.results["uncertainty_by_curve"][curve.id]["residual_bootstrap"].samples is not None


def test_reserved_metadata_keys_are_escaped_without_interpreting_user_values(tmp_path):
    project = Project()
    project.ui_state = {"__curvemole_array__": "not an archive array"}
    project.results = {"nested": {"__curvemole_literal_dict__": {"custom": True}}}
    restored = load_project(save_project(project, tmp_path / "reserved.fitproj"))
    assert restored.ui_state == project.ui_state
    assert restored.results == project.results


def test_corrupt_binary_result_is_reported_and_cannot_load(tmp_path):
    project, _curve, _samples = sample_project()
    path = save_project(project, tmp_path / "corrupt.fitproj")
    with zipfile.ZipFile(path) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist()}
    member = next(name for name in payloads if name.startswith("results/arrays/"))
    payloads[member] = b"corrupted numerical result"
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in payloads.items():
            archive.writestr(name, payload)
    assert any(member in failure for failure in validate_project_archive(path, raise_on_error=False))
    with pytest.raises(ProjectFormatError, match="Checksum mismatch"):
        load_project(path)


def test_history_descriptor_count_is_checked_even_when_checksum_matches(tmp_path):
    path = save_project(Project(), tmp_path / "count.fitproj")
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    payload = b'{"reason":"Fit"}\n'
    manifest["checksums"]["history.jsonl"] = hashlib.sha256(payload).hexdigest()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("history.jsonl", payload)
    with pytest.raises(ProjectFormatError, match="count"):
        load_project(path)


@pytest.mark.parametrize("missing", ["result", "empty_result", "history"])
def test_partial_recovery_keeps_intact_experimental_data_when_results_or_history_are_missing(tmp_path, missing):
    project, curve, _samples = sample_project()
    path = save_project(project, tmp_path / "partial.fitproj")
    with zipfile.ZipFile(path) as archive:
        omitted = ("history.jsonl" if missing == "history" else
                   next(name for name in archive.namelist() if name.startswith("results/arrays/")))
        payloads = {name: archive.read(name) for name in archive.namelist() if name != omitted}
    if missing == "empty_result":
        payloads[omitted] = b""
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in payloads.items():
            archive.writestr(name, payload)
    restored = load_project(path, partial_recovery=True)
    assert restored.read_only
    assert len(restored.curves) == 1
    np.testing.assert_array_equal(restored.curves[0].original_x, curve.original_x)
    np.testing.assert_array_equal(restored.curves[0].original_y, curve.original_y)
    if missing == "history":
        assert not restored.fit_history
    else:
        assert len(restored.fit_history) == len(project.fit_history)


@pytest.mark.parametrize("values", [
    np.array([0., -0., np.nextafter(0., 1.), np.nan, np.inf, -np.inf]),
    np.array([0, np.iinfo(np.uint64).max], dtype=np.uint64),
    np.array([1 + 2j, 3 - 4j], dtype=np.complex128),
])
def test_binary_storage_preserves_dtypes_and_exact_bits(tmp_path, values):
    project = Project()
    project.results["numeric_extension"] = values
    restored = load_project(save_project(project, tmp_path / "bits.fitproj"))
    actual = restored.results["numeric_extension"]
    assert actual.dtype == values.dtype
    assert actual.tobytes() == values.tobytes()


def test_unrecognised_sample_metadata_is_left_untouched(tmp_path):
    project = Project()
    project.results["custom"] = {"parameter_paths": None, "samples": [[1, 2]]}
    restored = load_project(save_project(project, tmp_path / "custom.fitproj"))
    assert restored.results["custom"] == project.results["custom"]


@pytest.mark.parametrize("marker", ["__curvemole_array__", "__curvemole_literal_dict__"])
def test_whole_result_mapping_can_be_reserved_user_metadata(tmp_path, marker):
    project = Project()
    project.results = {marker: "ordinary user metadata"}
    restored = load_project(save_project(project, tmp_path / "literal-results.fitproj"))
    assert restored.results == project.results


def test_excluding_uncertainty_samples_preserves_other_metadata_with_similar_names(tmp_path):
    project, curve, _samples = sample_project()
    curve.metadata = {"samples": ["sample-A"], "raw_samples": ["raw"], "replicates": 3}
    project.dataset.series[0].metadata = {"replicates": 4}
    project.ui_state = {"plugin_data": {"custom": {"replicates": 200, "samples": [1, 2]}}}
    path = save_project(project, tmp_path / "without-private-samples.fitproj",
                        include_uncertainty_samples=False)
    restored = load_project(path)
    assert restored.curves[0].metadata == curve.metadata
    assert restored.dataset.series[0].metadata == project.dataset.series[0].metadata
    assert restored.ui_state == project.ui_state
    assert restored.results["uncertainty_by_curve"][curve.id]["residual_bootstrap"]["samples"] is None


@pytest.mark.parametrize("kind", ["results", "history", "manifest"])
def test_real_zip_stream_corruption_is_reported_and_intact_spectra_can_be_recovered(tmp_path, kind):
    project, curve, _samples = sample_project()
    path = save_project(project, tmp_path / "deflate.fitproj")
    with zipfile.ZipFile(path) as archive:
        name = ("manifest.json" if kind == "manifest" else "history.jsonl" if kind == "history" else
                next(name for name in archive.namelist() if name.startswith("results/arrays/")))
        member = archive.getinfo(name)
    with path.open("r+b") as stream:
        stream.seek(member.header_offset)
        header = struct.unpack("<IHHHHHIIIHH", stream.read(30))
        stream.seek(member.header_offset + 30 + header[-2] + header[-1])
        stream.write(b"\xff" * min(8, member.compress_size))
    assert validate_project_archive(path, raise_on_error=False)
    with pytest.raises(ProjectFormatError):
        load_project(path)
    if kind != "manifest":
        recovered = load_project(path, partial_recovery=True)
        assert recovered.read_only
        assert len(recovered.curves) == 1
        np.testing.assert_array_equal(recovered.curves[0].y, curve.y)


def test_unicode_and_surrogate_escaped_filenames_survive_streamed_metadata_and_history(tmp_path):
    project = Project("Misura à λ")
    name = "spectrum-\udc80.dat"  # POSIX surrogateescape for a non-UTF-8 filename byte.
    curve = Curve(name, [0., 1.], [1., 2.], source=name)
    project.add_curve(curve)
    project.ui_state["filename"] = name
    project.snapshot("Fit", {"source": name, "label": "λ"})
    restored = load_project(save_project(project, tmp_path / "unicode.fitproj"))
    assert restored.name == project.name
    assert restored.curves[0].source == name
    assert restored.curves[0].name == name
    assert restored.ui_state["filename"] == name
    assert restored.fit_history[0]["source"] == name
    assert restored.fit_history[0]["label"] == "λ"
