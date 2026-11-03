"""Bounded structural validation for portable project archives."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np

from curvemole.core.errors import (
    ConstraintError,
    ExpressionError,
    ProjectFormatError,
    ProjectResourceLimitError,
)


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Explicit load budget; callers may opt into a larger trusted dataset."""

    members: int = 100_000
    expanded_bytes: int = 1024**3
    array_bytes: int = 1024**3
    manifest_bytes: int = 512 * 1024**2

    def __post_init__(self):
        if any(
            isinstance(v, bool) or not isinstance(v, int) or v <= 0
            for v in (self.members, self.expanded_bytes, self.array_bytes, self.manifest_bytes)
        ):
            raise ValueError("Archive limits must be positive integers.")


def preflight_archive(archive, limits: ArchiveLimits) -> None:
    members = archive.infolist()
    sizes = {"members": len(members), "expanded_bytes": sum(m.file_size for m in members)}
    try:
        manifest = archive.getinfo("manifest.json")
    except KeyError:
        pass  # structural validator reports the missing manifest
    else:
        sizes["manifest_bytes"] = manifest.file_size
    required = {name: size for name, size in sizes.items() if size > getattr(limits, name)}
    if required:
        raise ProjectResourceLimitError(required, {name: getattr(limits, name) for name in required})
    archive._curvemole_limits = limits


def read_array_header(stream, member_size: int, limits: ArchiveLimits):
    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
    elif version == (2, 0):
        shape, fortran, dtype = np.lib.format.read_array_header_2_0(stream)
    else:
        raise ProjectFormatError(f"Unsupported project NumPy array version: {version}")
    if dtype.hasobject or dtype.itemsize <= 0:
        raise ProjectFormatError("Project arrays must have a fixed-size numeric dtype.")
    count = math.prod(shape)
    payload = count * dtype.itemsize
    if (
        len(shape) > 8
        or any(d < 0 for d in shape)
        or payload > member_size - stream.tell()
    ):
        raise ProjectFormatError(
            "Project array has invalid dimensions or a truncated payload (array-size mismatch)."
        )
    if payload > limits.array_bytes:
        raise ProjectResourceLimitError(
            {"array_bytes": payload}, {"array_bytes": limits.array_bytes}
        )
    return shape, fortran, dtype


def validate_manifest(manifest, names) -> list[str]:
    errors = []
    schema = manifest.get("schema_version")
    if isinstance(schema, bool) or not isinstance(schema, int) or schema < 1:
        errors.append("Invalid or missing project schema_version")
    project = manifest.get("project")
    if not isinstance(project, dict):
        return errors + ["Manifest project must be an object"]
    if not isinstance(project.get("id"), str) or not project.get("id"):
        errors.append("Project must have a nonempty identifier")
    for field in ("curves", "models", "results", "ui_state", "export_config", "notebook"):
        if not isinstance(project.get(field, {}), dict):
            errors.append(f"Project {field} must be an object")
    for field in ("series", "custom_functions", "custom_formulas"):
        if not isinstance(project.get(field, []), list) or any(
            not isinstance(v, dict) for v in project.get(field, [])
        ):
            errors.append(f"Project {field} must be a list of objects")
    curves = project.get("curves", {})
    if not isinstance(curves, dict):
        return errors
    for identity, curve in curves.items():
        if not isinstance(curve, dict) or not isinstance(curve.get("name"), str):
            errors.append(f"Invalid curve metadata: {identity}")
            continue
        if curve.get("id", identity) != identity:
            errors.append(f"Mismatched curve identifier: {identity}")
        for axis in ("original_x", "original_y"):
            if f"data/{identity}/{axis}.npy" not in names:
                errors.append(f"Missing curve array: {identity}/{axis}")
        for field in ("masks", "transformations", "redo_transformations"):
            if not isinstance(curve.get(field, []), list) or any(
                not isinstance(v, dict) for v in curve.get(field, [])
            ):
                errors.append(f"Curve {identity} {field} must be a list of objects")
    # Construct structural value objects without resolving plugins or evaluating
    # models. A valid archive may contain an unfinished scientific model.
    from curvemole.core.models import Model

    models = project.get("models", {})
    if isinstance(models, dict):
        for identity, model in models.items():
            try:
                # Orphaned model records can be retained by notebook/undo
                # history; the loader ignores those whose curves were removed.
                if not isinstance(model, dict):
                    raise ValueError("model must be an object")
                Model.from_dict(model)
            except (KeyError, TypeError, ValueError, AttributeError, ConstraintError, ExpressionError) as exc:
                errors.append(f"Invalid model structure {identity}: {exc}")
    for identity, curve in curves.items():
        if not isinstance(curve, dict):
            continue
        masks = curve.get("masks", [])
        if isinstance(masks, list):
            for mask in masks:
                if (
                    not isinstance(mask, dict)
                    or not isinstance(mask.get("id"), str)
                    or not isinstance(mask.get("name"), str)
                ):
                    errors.append(f"Invalid mask structure: {identity}")
        for field in ("transformations", "redo_transformations"):
            values = curve.get(field, [])
            if isinstance(values, list):
                for value in values:
                    if (
                        not isinstance(value, dict)
                        or not isinstance(value.get("operation"), str)
                        or not isinstance(value.get("parameters", {}), dict)
                    ):
                        errors.append(f"Invalid transformation structure: {identity}")
    custom = project.get("custom_functions", [])
    if isinstance(custom, list):
        for value in custom:
            if (
                not isinstance(value, dict)
                or not isinstance(value.get("identifier"), str)
                or not isinstance(value.get("formula"), str)
            ):
                errors.append("Invalid custom function structure")
    series = project.get("series", [])
    if isinstance(series, list):
        used = []
        series_ids = set()
        for item in series:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not isinstance(item.get("name"), str)
                or not isinstance(item.get("curve_ids", []), list)
                or any(not isinstance(i, str) for i in item.get("curve_ids", []))
            ):
                errors.append("Invalid series metadata")
                continue
            if item["id"] in series_ids:
                errors.append("Duplicate series identifier")
            series_ids.add(item["id"])
            used.extend(item.get("curve_ids", []))
        if len(set(used)) != len(used) or set(used) != set(curves):
            errors.append("Series must reference each curve exactly once")
    checksums = manifest.get("checksums", {})
    if isinstance(checksums, dict):
        if any(
            not isinstance(v, str) or re.fullmatch(r"[0-9a-fA-F]{64}", v) is None
            for v in checksums.values()
        ):
            errors.append("Invalid SHA-256 checksum metadata")
        if isinstance(schema, int) and schema >= 3:
            errors.extend(
                f"Missing checksum: {name}"
                for name in names
                if name != "manifest.json" and not name.endswith("/") and name not in checksums
            )
    return errors
