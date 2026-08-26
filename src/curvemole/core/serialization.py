"""Portable project and model formats using ZIP, JSON, NumPy, and checksums."""

from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import tempfile
import zipfile
from collections.abc import Mapping
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from curvemole.core.data import Curve, CurveState, Dataset, Mask, Series, Transformation
from curvemole.core.errors import ProjectFormatError
from curvemole.core.models import Model
from curvemole.core.project import Project
from curvemole.version import FITMODEL_SCHEMA_VERSION, PROJECT_SCHEMA_VERSION, __version__


def save_project(
    project: Project,
    path: str | Path,
    *,
    include_uncertainty_samples: bool = True,
    portable: bool = False,
    update_project_path: bool = True,
) -> Path:
    destination = Path(path)
    if destination.suffix.lower() != ".fitproj":
        destination = destination.with_suffix(".fitproj")
    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata = project.to_metadata()
    metadata["path"] = None
    if portable:
        metadata["export_config"] = {
            key: value
            for key, value in metadata.get("export_config", {}).items()
            if key not in {"directory", "last_export_path", "local_paths"}
        }
        for curve in metadata["curves"].values():
            curve["source"] = Path(curve["source"]).name if curve.get("source") else None
    if not include_uncertainty_samples:
        metadata["results"] = _remove_raw_samples(metadata.get("results", {}))

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
            for curve in project.curves:
                prefix = f"data/{curve.id}"
                _write_array(archive, f"{prefix}/original_x.npy", curve.original_x, checksums)
                _write_array(archive, f"{prefix}/original_y.npy", curve.original_y, checksums)
                for name, array in (
                    ("sigma_x.npy", curve.sigma_x),
                    ("sigma_y.npy", curve.sigma_y),
                    ("weights.npy", curve.weights),
                ):
                    if array is not None:
                        _write_array(archive, f"{prefix}/{name}", array, checksums)
                for mask in curve.masks.values():
                    _write_array(
                        archive,
                        f"{prefix}/masks/{mask.id}.npy",
                        mask.excluded.astype(np.uint8),
                        checksums,
                    )
                for stack_name, transformations in (
                    ("transformations", curve.transformations),
                    ("redo_transformations", curve.redo_transformations),
                ):
                    for index, transformation in enumerate(transformations):
                        if transformation.operand is not None:
                            _write_array(
                                archive,
                                f"{prefix}/{stack_name}/{index}_operand.npy",
                                transformation.operand,
                                checksums,
                            )
            manifest = {
                "format": "CurveMole project",
                "schema_version": PROJECT_SCHEMA_VERSION,
                "application_version": __version__,
                "created_at": datetime.now(UTC).isoformat(),
                "portable": portable,
                "uncertainty_samples_included": include_uncertainty_samples,
                "checksums": checksums,
                "project": _json_safe(metadata),
            }
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False).encode("utf-8"),
            )
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
    failures = validate_project_archive(source, raise_on_error=not partial_recovery)
    try:
        with zipfile.ZipFile(source, "r") as archive:
            manifest = json.loads(archive.read("manifest.json"))
            schema = int(manifest.get("schema_version", -1))
            if schema < 1:
                raise ProjectFormatError(f"Unsupported project schema: {schema}")
            future = schema > PROJECT_SCHEMA_VERSION
            metadata = manifest["project"]
            curve_values: dict[str, Curve] = {}
            for curve_id, curve_meta in metadata.get("curves", {}).items():
                prefix = f"data/{curve_id}"
                try:
                    original_x = _read_array(archive, f"{prefix}/original_x.npy")
                    original_y = _read_array(archive, f"{prefix}/original_y.npy")
                except (KeyError, ValueError) as exc:
                    if partial_recovery:
                        continue
                    raise ProjectFormatError(f"Cannot recover data for curve '{curve_id}': {exc}") from exc
                optional = {
                    name: _try_array(archive, f"{prefix}/{name}.npy")
                    for name in ("sigma_x", "sigma_y", "weights")
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
                    sigma_x=optional["sigma_x"],
                    sigma_y=optional["sigma_y"],
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
                fit_history=list(metadata.get("fit_history", [])),
                custom_functions=list(metadata.get("custom_functions", [])),
                ui_state=dict(metadata.get("ui_state", {})),
                export_config=dict(metadata.get("export_config", {})),
                created_at=str(metadata.get("created_at", datetime.now(UTC).isoformat())),
                modified_at=str(metadata.get("modified_at", datetime.now(UTC).isoformat())),
                application_version=str(metadata.get("application_version", "unknown")),
                path=source,
                read_only=bool(future or failures),
                dirty=False,
            )
            project.dataset.validate_unique_ids()
            return project
    except zipfile.BadZipFile as exc:
        raise ProjectFormatError(f"'{source}' is not a valid .fitproj ZIP archive.") from exc


def validate_project_archive(
    path: str | Path, *, raise_on_error: bool = True
) -> list[str]:
    failures: list[str] = []
    try:
        with zipfile.ZipFile(path, "r") as archive:
            bad_entry = archive.testzip()
            if bad_entry:
                failures.append(f"ZIP CRC failed: {bad_entry}")
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except KeyError:
                failures.append("Missing manifest.json")
                manifest = {}
            except json.JSONDecodeError as exc:
                failures.append(f"Invalid manifest JSON: {exc}")
                manifest = {}
            for name, expected in manifest.get("checksums", {}).items():
                try:
                    actual = hashlib.sha256(archive.read(name)).hexdigest()
                except KeyError:
                    failures.append(f"Missing entry: {name}")
                    continue
                if actual != expected:
                    failures.append(f"Checksum mismatch: {name}")
    except (OSError, zipfile.BadZipFile) as exc:
        failures.append(str(exc))
    if failures and raise_on_error:
        raise ProjectFormatError("Project validation failed: " + "; ".join(failures))
    return failures


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
            self.acquired = False
            return self
        try:
            os.write(descriptor, payload)
        finally:
            os.close(descriptor)
        self.acquired = True
        return self

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
    buffer = io.BytesIO()
    np.save(buffer, np.asarray(array), allow_pickle=False)
    payload = buffer.getvalue()
    archive.writestr(name, payload)
    checksums[name] = hashlib.sha256(payload).hexdigest()


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
    from curvemole.core.fitting import FitResult

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
    from curvemole.core.fitting import FitResult

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
        return {key: _load_results(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_load_results(item) for item in value]
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
