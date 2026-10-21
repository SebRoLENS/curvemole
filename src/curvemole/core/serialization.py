"""Portable project and model formats using ZIP, JSON, NumPy, and checksums."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import socket
import tempfile
import zipfile
import zlib
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from curvemole.core.data import Curve, CurveState, Dataset, Mask, Series, Transformation
from curvemole.core.errors import ProjectFormatError
from curvemole.core.fitting import FitResult
from curvemole.core.history import CompactHistory
from curvemole.core.models import Model
from curvemole.core.notebook import LaboratoryNotebook
from curvemole.core.process import process_alive
from curvemole.core.project import Project
from curvemole.core.uncertainty import ResamplingResult
from curvemole.version import FITMODEL_SCHEMA_VERSION, PROJECT_SCHEMA_VERSION, __version__


@dataclass(frozen=True, slots=True)
class ProjectSaveSnapshot:
    """Detached metadata and stable archive arrays, without rendered data copies."""

    id: str
    revision: int
    dirty: bool
    read_only: bool
    metadata: dict[str, Any]
    arrays: tuple[tuple[str, np.ndarray], ...]

    def to_metadata(self) -> dict[str, Any]:
        return self.metadata


_ARRAY_REF = "__curvemole_array__"
_LITERAL_DICT = "__curvemole_literal_dict__"
_HISTORY_PATH = "history.jsonl"


class _DigestWriter(io.RawIOBase):
    """Hash bytes as ZIP members are written, without a second full-size buffer."""

    def __init__(self, stream) -> None:
        self.stream = stream
        self.digest = hashlib.sha256()

    def writable(self) -> bool:
        return True

    def write(self, payload) -> int:
        self.digest.update(payload)
        return self.stream.write(payload)

    def flush(self) -> None:
        if not self.closed:
            self.stream.flush()


def _write_json(archive, name, value, checksums=None) -> None:
    with archive.open(name, "w", force_zip64=True) as stream:
        writer = _DigestWriter(stream)
        with io.TextIOWrapper(writer, encoding="utf-8", newline="\n") as text_stream:
            json.dump(value, text_stream, ensure_ascii=True, separators=(",", ":"),
                      allow_nan=False)
        if checksums is not None:
            checksums[name] = writer.digest.hexdigest()


class _ArchiveValues:
    """Externalise numerical results once; keep JSON limited to small metadata."""

    def __init__(self, archive, checksums, *, include_samples: bool) -> None:
        self.archive = archive
        self.checksums = checksums
        self.include_samples = include_samples
        self.arrays: dict[int, tuple[np.ndarray, str]] = {}

    def encode(self, value, *, result_data=False):
        if isinstance(value, FitResult):
            metadata = value.to_dict(arrays=False)
            for curve_id, output in value.curve_outputs.items():
                metadata["curve_outputs"][curve_id].update(
                    (name, getattr(output, name)) for name in
                    ("indices", "x", "observed", "fitted", "residual", "weighted_residual"))
            metadata.update(covariance=value.covariance, correlation=value.correlation)
            return self.encode(metadata, result_data=result_data)
        if isinstance(value, np.ndarray):
            if value.dtype.hasobject:
                return self.encode(value.tolist(), result_data=result_data)
            known = self.arrays.get(id(value))
            if known is None:
                name = f"results/arrays/{len(self.arrays):06d}.npy"
                _write_array(self.archive, name, value, self.checksums)
                self.arrays[id(value)] = (value, name)
            else:
                name = known[1]
            return {_ARRAY_REF: name}
        if hasattr(value, "to_dict") and callable(value.to_dict):
            # ResamplingResult.to_dict otherwise creates millions of Python floats.
            if isinstance(value, ResamplingResult):
                metadata = value.to_dict(include_samples=False)
                metadata["samples"] = value.samples if self.include_samples or not result_data else None
            else:
                metadata = value.to_dict()
            return self.encode(metadata, result_data=result_data)
        if isinstance(value, dict):
            encoded = {}
            for key, item in value.items():
                if result_data and key in {"samples", "raw_samples", "replicates"} and not self.include_samples:
                    item = None
                elif result_data and key == "samples" and isinstance(item, list) and "parameter_paths" in value:
                    item = _sample_array(item, value["parameter_paths"])
                encoded[str(key)] = self.encode(item, result_data=result_data)
            if set(encoded) in ({_ARRAY_REF}, {_LITERAL_DICT}):
                return {_LITERAL_DICT: encoded}
            return encoded
        if isinstance(value, (list, tuple)):
            return [self.encode(item, result_data=result_data) for item in value]
        return _json_safe(value)


def _sample_array(samples, paths):
    if not isinstance(paths, (list, tuple)):
        return samples
    try:
        array = np.asarray(samples, dtype=np.float64)
    except (TypeError, ValueError, OverflowError):
        return samples
    if array.ndim == 2 and array.shape[1] == len(paths):
        return array
    if array.size == 0 and array.ndim == 1:
        return array.reshape(0, len(paths)) if paths else array.reshape(0, 0)
    return samples


def _archive_values(value, archive, cache):
    if isinstance(value, dict):
        if set(value) == {_LITERAL_DICT}:
            if not isinstance(value[_LITERAL_DICT], dict):
                raise ProjectFormatError("Invalid literal metadata dictionary.")
            return {key: _archive_values(item, archive, cache)
                    for key, item in value[_LITERAL_DICT].items()}
        if set(value) == {_ARRAY_REF}:
            name = value[_ARRAY_REF]
            if (not isinstance(name, str) or not name.startswith("results/arrays/")
                    or not name.endswith(".npy") or ".." in name.split("/")):
                raise ProjectFormatError("Invalid numerical-result array reference.")
            if name not in cache:
                try:
                    cache[name] = _read_array(archive, name)
                except (KeyError, ValueError, EOFError, OSError, zipfile.BadZipFile, zlib.error) as exc:
                    raise ProjectFormatError(f"Cannot read result array: {name}") from exc
            return cache[name]
        return {key: _archive_values(item, archive, cache) for key, item in value.items()}
    if isinstance(value, list):
        return [_archive_values(item, archive, cache) for item in value]
    return value


def _write_history(archive, history, checksums):
    records = history.iter_records() if isinstance(history, CompactHistory) else iter(history)
    with archive.open(_HISTORY_PATH, "w", force_zip64=True) as stream:
        writer = _DigestWriter(stream)
        with io.TextIOWrapper(writer, encoding="utf-8", newline="\n") as text_stream:
            for record in records:
                json.dump(_json_safe(record), text_stream, ensure_ascii=True,
                          separators=(",", ":"), allow_nan=False)
                text_stream.write("\n")
        checksums[_HISTORY_PATH] = writer.digest.hexdigest()
    return {"storage": _HISTORY_PATH, "count": len(history)}


def _load_history(value, archive, schema, *, partial_recovery=False, failures=None):
    def problem(message):
        if not partial_recovery:
            raise ProjectFormatError(message)
        if failures is not None:
            failures.append(message)

    if schema < 3 or isinstance(value, list):
        return CompactHistory(value)
    if not isinstance(value, dict) or value.get("storage") != _HISTORY_PATH:
        problem("Invalid fit-history storage descriptor.")
        return CompactHistory()
    history = CompactHistory()
    try:
        with archive.open(_HISTORY_PATH) as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except (ValueError, UnicodeError) as exc:
                    problem(f"Invalid fit-history record: {exc}")
                    continue
                if not isinstance(record, dict):
                    problem("Invalid fit-history record.")
                    continue
                history.append_record(record)
    except (KeyError, ValueError, EOFError, OSError, zipfile.BadZipFile, zlib.error) as exc:
        problem(f"Cannot read fit history: {exc}")
    if len(history) != value.get("count"):
        problem("Fit-history record count does not match its descriptor.")
    return history


def _project_arrays(project: Project | ProjectSaveSnapshot) -> Iterator[tuple[str, np.ndarray]]:
    if isinstance(project, ProjectSaveSnapshot):
        yield from project.arrays
        return
    for curve in project.curves:
        prefix = f"data/{curve.id}"
        yield f"{prefix}/original_x.npy", curve.original_x
        yield f"{prefix}/original_y.npy", curve.original_y
        for name, array in (
            ("sigma_x.npy", curve.sigma_x), ("sigma_y.npy", curve.sigma_y),
            ("error_y_minus.npy", curve.error_y_minus), ("error_y_plus.npy", curve.error_y_plus),
            ("weights.npy", curve.weights),
        ):
            if array is not None:
                yield f"{prefix}/{name}", array
        for index, array in enumerate(curve.original_columns.values()):
            yield f"{prefix}/columns/{index}.npy", array
        for mask in curve.masks.values():
            yield f"{prefix}/masks/{mask.id}.npy", curve.original_mask(mask)
        for stack_name, transformations in (
            ("transformations", curve.transformations), ("redo_transformations", curve.redo_transformations),
        ):
            for index, transformation in enumerate(transformations):
                if transformation.operand is not None:
                    yield f"{prefix}/{stack_name}/{index}_operand.npy", transformation.operand


def capture_project_snapshot(project: Project) -> ProjectSaveSnapshot:
    """Capture on the owning thread, sharing immutable original data only.

    Mutable masks, transformation operands and result metadata are detached.
    Current/rendered curve arrays are not stored by the archive and need no copy.
    JSON conversion, compression and integrity checks belong to the save worker.
    """
    arrays = []
    memo: dict[int, Any] = {}
    for name, array in _project_arrays(project):
        stable = memo.get(id(array))
        if stable is None:
            owner = array
            immutable = not owner.flags.writeable
            while immutable and isinstance(owner.base, np.ndarray):
                owner = owner.base
                immutable = not owner.flags.writeable
            # A readonly view of a writable array/external buffer can still change.
            immutable = immutable and owner.base is None
            stable = array if immutable else array.copy()
            memo[id(array)] = stable
        arrays.append((name, stable))
    metadata = copy.deepcopy(project.to_metadata(), memo)
    source_file = project.path.name if project.path is not None else project.ui_state.get("recovery_source_file", "")
    metadata["recovery"] = {
        "display_name": Path(source_file).stem if source_file else project.name,
        "source_file": source_file,
    }
    return ProjectSaveSnapshot(
        project.id, project.revision, project.dirty, project.read_only,
        metadata, tuple(arrays),
    )


def save_project(
    project: Project | ProjectSaveSnapshot,
    path: str | Path,
    *,
    include_uncertainty_samples: bool = True,
    portable: bool = False,
    update_project_path: bool = True,
) -> Path:
    if isinstance(project, ProjectSaveSnapshot) and update_project_path:
        raise ValueError("Saving a detached snapshot cannot mark the live project as saved.")
    destination = Path(path)
    if destination.suffix.lower() != ".fitproj":
        destination = destination.with_suffix(".fitproj")
    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata = dict(project.to_metadata())
    mask_names = {
        f"data/{curve_id}/masks/{mask['id']}.npy"
        for curve_id, curve in metadata["curves"].items() for mask in curve.get("masks", [])
    }
    metadata["path"] = None
    if portable:
        metadata["export_config"] = {
            key: value
            for key, value in metadata.get("export_config", {}).items()
            if key not in {"directory", "last_export_path", "local_paths"}
        }
        metadata["curves"] = {key: dict(value) for key, value in metadata["curves"].items()}
        for curve in metadata["curves"].values():
            curve["source"] = Path(curve["source"]).name if curve.get("source") else None

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    checksums: dict[str, str] = {}
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
        ) as archive:
            for name, array in _project_arrays(project):
                if name in mask_names:
                    array = array.astype(np.uint8)
                _write_array(archive, name, array, checksums)
            history = _write_history(archive, metadata.get("fit_history", ()), checksums)
            values = _ArchiveValues(archive, checksums, include_samples=include_uncertainty_samples)
            encoded = {key: values.encode(value, result_data=key == "results")
                       for key, value in metadata.items() if key != "fit_history"}
            encoded["fit_history"] = history
            manifest = {
                "format": "CurveMole project",
                "schema_version": PROJECT_SCHEMA_VERSION,
                "application_version": __version__,
                "created_at": datetime.now(UTC).isoformat(),
                "portable": portable,
                "uncertainty_samples_included": include_uncertainty_samples,
                "checksums": checksums,
                "project": encoded,
            }
            _write_json(archive, "manifest.json", manifest)
        validate_project_archive(temporary)
        os.replace(temporary, destination)
        if update_project_path:
            project.mark_saved(destination)
        return destination
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def load_project(path: str | Path, *, partial_recovery: bool = False) -> Project:
    source = Path(path)
    if not source.is_file():
        raise ProjectFormatError(f"Project does not exist: {source}")
    try:
        with zipfile.ZipFile(source, "r") as archive:
            manifest, failures = _validate_archive(archive)
            if failures and not partial_recovery:
                raise ProjectFormatError("Project validation failed: " + "; ".join(failures))
            schema = int(manifest.get("schema_version", -1))
            if schema < 1:
                raise ProjectFormatError(f"Unsupported project schema: {schema}")
            future = schema > PROJECT_SCHEMA_VERSION
            metadata = manifest["project"]
            if schema >= 3:
                # Result arrays are loaded directly into their final NumPy storage.
                cache = {}
                decoded = dict(metadata)
                for key, value in metadata.items():
                    if key == "results" and isinstance(value, dict) and set(value) != {_LITERAL_DICT}:
                        results = {}
                        for name, record in value.items():
                            try:
                                results[name] = _archive_values(record, archive, cache)
                            except ProjectFormatError as exc:
                                if not partial_recovery:
                                    raise
                                failures.append(f"Result '{name}' could not be recovered: {exc}")
                        decoded[key] = results
                    else:
                        try:
                            decoded[key] = _archive_values(value, archive, cache)
                        except ProjectFormatError as exc:
                            if not partial_recovery:
                                raise
                            failures.append(f"Metadata '{key}' could not be fully recovered: {exc}")
                metadata = decoded
            history = _load_history(metadata.get("fit_history", []), archive, schema,
                                    partial_recovery=partial_recovery, failures=failures)
            curve_values: dict[str, Curve] = {}
            for curve_id, curve_meta in metadata.get("curves", {}).items():
                prefix = f"data/{curve_id}"
                try:
                    original_x = _read_array(archive, f"{prefix}/original_x.npy")
                    original_y = _read_array(archive, f"{prefix}/original_y.npy")
                except (KeyError, ValueError, EOFError, OSError, zipfile.BadZipFile, zlib.error) as exc:
                    if partial_recovery:
                        continue
                    raise ProjectFormatError(f"Cannot recover data for curve '{curve_id}': {exc}") from exc
                optional = {
                    name: _try_array(archive, f"{prefix}/{name}.npy")
                    for name in ("sigma_x", "sigma_y", "weights", "error_y_minus", "error_y_plus")
                }
                masks: dict[str, Mask] = {}
                for mask_meta in curve_meta.get("masks", []):
                    mask_path = f"{prefix}/masks/{mask_meta['id']}.npy"
                    excluded = _try_array(archive, mask_path)
                    if excluded is None:
                        if partial_recovery:
                            continue
                        raise ProjectFormatError(f"Missing mask data: {mask_path}")
                    mask = Mask(
                        id=str(mask_meta["id"]),
                        name=str(mask_meta["name"]),
                        excluded=excluded.astype(bool),
                        ranges=[tuple(value) for value in mask_meta.get("ranges", [])],
                    )
                    masks[mask.name] = mask
                transformations = _load_transformations(
                    archive, prefix, "transformations", curve_meta.get("transformations", [])
                )
                redo = _load_transformations(
                    archive, prefix, "redo_transformations", curve_meta.get("redo_transformations", [])
                )
                curve = Curve(
                    id=str(curve_meta.get("id", curve_id)),
                    name=str(curve_meta["name"]),
                    original_x=original_x,
                    original_y=original_y,
                    original_columns={key: _read_array(archive, f"{prefix}/columns/{index}.npy")
                                      for index, key in enumerate(curve_meta.get("column_keys", []))},
                    column_labels=dict(curve_meta.get("column_labels", {})),
                    column_axes=dict(curve_meta.get("column_axes", {})),
                    sigma_x=optional["sigma_x"],
                    sigma_y=optional["sigma_y"],
                    error_y_minus=optional["error_y_minus"],
                    error_y_plus=optional["error_y_plus"],
                    error_confidence_level=curve_meta.get("error_confidence_level", 0.95),
                    weights=optional["weights"],
                    weights_are_inverse_variance=bool(
                        curve_meta.get("weights_are_inverse_variance", True)
                    ),
                    x_label=str(curve_meta.get("x_label", "x")),
                    y_label=str(curve_meta.get("y_label", "y")),
                    x_unit=str(curve_meta.get("x_unit", "")),
                    y_unit=str(curve_meta.get("y_unit", "")),
                    source=curve_meta.get("source"),
                    visible=bool(curve_meta.get("visible", True)),
                    colour=str(curve_meta.get("colour", "#0072B2")),
                    state=CurveState(curve_meta.get("state", CurveState.NOT_FITTED.value)),
                    transformations=transformations,
                    redo_transformations=redo,
                    masks=masks,
                    active_mask=str(curve_meta.get("active_mask", "Default")),
                    fit_ranges=[tuple(value) for value in curve_meta.get("fit_ranges", [])],
                    metadata=dict(curve_meta.get("metadata", {})),
                )
                curve_values[curve_id] = curve
            series_values: list[Series] = []
            for series_meta in metadata.get("series", []):
                curves = [
                    curve_values[curve_id]
                    for curve_id in series_meta.get("curve_ids", [])
                    if curve_id in curve_values
                ]
                series_values.append(
                    Series(
                        id=str(series_meta["id"]),
                        name=str(series_meta["name"]),
                        curves=curves,
                        metadata=dict(series_meta.get("metadata", {})),
                    )
                )
            project = Project(
                id=str(metadata["id"]),
                name=str(metadata.get("name", source.stem)),
                dataset=Dataset(series_values),
                models={
                    curve_id: Model.from_dict(model)
                    for curve_id, model in metadata.get("models", {}).items()
                    if curve_id in curve_values
                },
                results=_load_results(metadata.get("results", {})),
                fit_history=history,
                custom_functions=list(metadata.get("custom_functions", [])),
                custom_formulas=list(metadata.get("custom_formulas", [])),
                ui_state=dict(metadata.get("ui_state", {})),
                export_config=dict(metadata.get("export_config", {})),
                notebook=LaboratoryNotebook.from_dict(metadata.get("notebook", {})),
                created_at=str(metadata.get("created_at", datetime.now(UTC).isoformat())),
                modified_at=str(metadata.get("modified_at", datetime.now(UTC).isoformat())),
                application_version=str(metadata.get("application_version", "unknown")),
                path=source,
                read_only=bool(future or failures),
                dirty=False,
            )
            project.dataset.validate_unique_ids()
            from curvemole.core.analysis_errors import restore_uncertainty_reports
            restore_uncertainty_reports(project)
            from curvemole.core.background_status import restore_background_history
            restore_background_history(project)
            return project
    except zipfile.BadZipFile as exc:
        raise ProjectFormatError(f"'{source}' is not a valid .fitproj ZIP archive.") from exc


def validate_project_archive(
    path: str | Path, *, raise_on_error: bool = True
) -> list[str]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            _manifest, failures = _validate_archive(archive)
    except (OSError, zipfile.BadZipFile) as exc:
        failures = [str(exc)]
    if failures and raise_on_error:
        raise ProjectFormatError("Project validation failed: " + "; ".join(failures))
    return failures


def _validate_archive(archive):
    """Parse metadata once and stream every member through CRC/checksum checks."""
    failures = []
    try:
        with archive.open("manifest.json") as stream:
            manifest = json.load(stream)
    except KeyError:
        failures.append("Missing manifest.json")
        manifest = {}
    except (ValueError, UnicodeError, EOFError, OSError, zipfile.BadZipFile, zlib.error) as exc:
        failures.append(f"Invalid manifest JSON: {exc}")
        manifest = {}
    if not isinstance(manifest, dict):
        failures.append("Manifest must be a JSON object")
        manifest = {}
    checksums = manifest.get("checksums", {})
    if not isinstance(checksums, dict):
        failures.append("Manifest checksums must be an object")
        checksums = {}
    names = set(archive.namelist())
    failures.extend(f"Missing entry: {name}" for name in checksums if name not in names)
    for member in archive.infolist():
        if member.filename == "manifest.json" or member.is_dir():
            continue
        digest = hashlib.sha256()
        try:
            with archive.open(member) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
        except (zipfile.BadZipFile, EOFError, OSError, zlib.error) as exc:
            failures.append(f"ZIP CRC/read failed: {member.filename}: {exc}")
            continue
        expected = checksums.get(member.filename)
        if expected is not None and digest.hexdigest() != expected:
            failures.append(f"Checksum mismatch: {member.filename}")
    return manifest, failures


def save_fitmodel(
    model: Model,
    path: str | Path,
    *,
    custom_functions: list[dict[str, Any]] | None = None,
) -> Path:
    destination = Path(path)
    if destination.suffix.lower() != ".fitmodel":
        destination = destination.with_suffix(".fitmodel")
    payload = {
        "format": "CurveMole fit model",
        "schema_version": FITMODEL_SCHEMA_VERSION,
        "application_version": __version__,
        "model": model.to_dict(),
        "custom_functions": custom_functions or [],
    }
    _atomic_json(destination, payload)
    return destination


def load_fitmodel(path: str | Path) -> tuple[Model, list[dict[str, Any]]]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectFormatError(f"Cannot read fit model '{source}': {exc}") from exc
    if payload.get("format") != "CurveMole fit model":
        raise ProjectFormatError("The selected file is not a CurveMole .fitmodel file.")
    schema = int(payload.get("schema_version", -1))
    if schema > FITMODEL_SCHEMA_VERSION or schema < 1:
        raise ProjectFormatError(f"Unsupported fit-model schema: {schema}")
    return Model.from_dict(payload["model"]), list(payload.get("custom_functions", []))


@dataclass(slots=True)
class ProjectLock(AbstractContextManager["ProjectLock"]):
    project_path: Path
    acquired: bool = False
    lock_path: Path | None = None

    def __enter__(self) -> ProjectLock:
        self.lock_path = self.project_path.with_suffix(self.project_path.suffix + ".lock")
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "created_at": datetime.now(UTC).isoformat(),
                "project": str(self.project_path.resolve()),
            }
        ).encode("utf-8")
        try:
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if not self._discard_stale_lock():
                self.acquired = False
                return self
            try:
                descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                self.acquired = False
                return self
        try:
            os.write(descriptor, payload)
        finally:
            os.close(descriptor)
        self.acquired = True
        return self

    def _discard_stale_lock(self) -> bool:
        """Reclaim only locks whose owner has exited on this same computer."""
        assert self.lock_path is not None
        try:
            before = self.lock_path.stat()
            owner = json.loads(self.lock_path.read_text(encoding="utf-8"))
            if owner.get("host") != socket.gethostname() or process_alive(int(owner["pid"])):
                return False
            after = self.lock_path.stat()
            if (before.st_ino, before.st_mtime_ns, before.st_size) != (
                after.st_ino, after.st_mtime_ns, after.st_size
            ):
                return False
            self.lock_path.unlink()
            return True
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return False

    def __exit__(self, *exc: object) -> None:
        if self.acquired and self.lock_path:
            self.lock_path.unlink(missing_ok=True)
        self.acquired = False


def _write_array(
    archive: zipfile.ZipFile,
    name: str,
    array: np.ndarray,
    checksums: dict[str, str],
) -> None:
    with archive.open(name, "w", force_zip64=True) as stream, _DigestWriter(stream) as writer:
        np.save(writer, np.asarray(array), allow_pickle=False)
        writer.flush()
        checksums[name] = writer.digest.hexdigest()


def _read_array(archive: zipfile.ZipFile, name: str) -> np.ndarray:
    with archive.open(name, "r") as stream:
        return np.load(stream, allow_pickle=False)


def _try_array(archive: zipfile.ZipFile, name: str) -> np.ndarray | None:
    try:
        return _read_array(archive, name)
    except KeyError:
        return None


def _load_transformations(
    archive: zipfile.ZipFile,
    prefix: str,
    stack_name: str,
    values: list[Mapping[str, Any]],
) -> list[Transformation]:
    result: list[Transformation] = []
    for index, value in enumerate(values):
        operand = None
        if value.get("has_operand"):
            operand = _read_array(archive, f"{prefix}/{stack_name}/{index}_operand.npy")
        result.append(
            Transformation(
                operation=str(value["operation"]),
                parameters=dict(value.get("parameters", {})),
                description=str(value.get("description", "")),
                created_at=str(value.get("created_at", datetime.now(UTC).isoformat())),
                operand=operand,
            )
        )
    return result


def _json_safe(value: Any) -> Any:
    if isinstance(value, CompactHistory):
        return [_json_safe(record) for record in value.iter_records()]
    if isinstance(value, FitResult):
        return _json_safe(value.to_dict(arrays=True))
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_safe(value.to_dict())
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float):
        if math_is_nan(value):
            return None
        if value == float("inf"):
            return "Infinity"
        if value == float("-inf"):
            return "-Infinity"
    return value


def _load_results(value: Any) -> Any:
    if isinstance(value, dict):
        if {
            "success",
            "mode",
            "parameters",
            "curve_outputs",
            "settings",
            "free_parameter_paths",
        }.issubset(value):
            try:
                return FitResult.from_dict(value)
            except (TypeError, ValueError, KeyError):
                return value
        # Conversion is private to the freshly decoded archive. Replace children
        # in place so their former JSON lists can be freed as soon as possible.
        for key in value:
            if key == "samples" and isinstance(value[key], list) and "parameter_paths" in value:
                value[key] = _sample_array(value[key], value["parameter_paths"])
            else:
                value[key] = _load_results(value[key])
        return value
    if isinstance(value, list):
        for index in range(len(value)):
            value[index] = _load_results(value[index])
        return value
    return value


def math_is_nan(value: float) -> bool:
    return value != value


def _remove_raw_samples(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: None if key in {"samples", "raw_samples", "replicates"} else _remove_raw_samples(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_remove_raw_samples(item) for item in value]
    return value


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(_json_safe(payload), stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except Exception:
        with suppress(OSError):
            os.close(descriptor)
        Path(temporary_name).unlink(missing_ok=True)
        raise
