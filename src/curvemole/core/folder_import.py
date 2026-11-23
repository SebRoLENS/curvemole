"""Explicit folder-import session: stable files, substring filtering, no duplicates."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from curvemole.core.data import Curve, Series
from curvemole.core.errors import DataValidationError

IMPORT_PROCESSOR_KEY = "automatic_import_processor"
IMPORT_DESTINATION_KEY = "automatic_import_destination"
DEFAULT_IMPORT_DESTINATION = "default"


@dataclass(frozen=True, slots=True)
class ImportSeriesDestination:
    """A processor-local key and the proposed name of a persistent series."""

    key: str
    name: str

    def __post_init__(self) -> None:
        for field in ("key", "name"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise DataValidationError(f"An import series destination requires a non-empty {field}.")
            object.__setattr__(self, field, value.strip())


def validate_import_destinations(
    series: Sequence[Series], requests: Mapping[str, ImportSeriesDestination],
) -> None:
    known_ids = {group.id for group in series}
    if requests.keys() - known_ids:
        raise DataValidationError("An import destination refers to a series outside the returned acquisition.")
    names: dict[str, str] = {}
    for request in requests.values():
        if names.setdefault(request.key, request.name) != request.name:
            raise DataValidationError(f"Import destination '{request.key}' has conflicting series names.")


def plan_import_series(
    existing: Sequence[Series],
    incoming: Sequence[Series],
    processor_id: str | None,
    requests: Mapping[str, ImportSeriesDestination],
) -> tuple[list[Series], list[tuple[Series, list[Curve]]]]:
    """Plan new groups and appends without changing any live series."""
    validate_import_destinations(incoming, requests)
    if requests and not processor_id:
        raise DataValidationError("Only an automatic import processor can declare series destinations.")

    # Only the host writes routing metadata. Older projects recorded a single
    # destination per processor, which is the default route for that processor.
    live: dict[str, Series] = {}
    if requests:
        for group in existing:
            if group.metadata.get(IMPORT_PROCESSOR_KEY) == processor_id:
                key = group.metadata.get(IMPORT_DESTINATION_KEY, DEFAULT_IMPORT_DESTINATION)
                if isinstance(key, str):
                    live.setdefault(key, group)
    new: list[Series] = []
    planned: dict[str, Series] = {}
    appends: dict[str, tuple[Series, list[Curve]]] = {}
    names = {group.name for group in existing}
    names.update(group.name for group in incoming if group.id not in requests)
    for group in incoming:
        group.metadata.pop(IMPORT_PROCESSOR_KEY, None)
        group.metadata.pop(IMPORT_DESTINATION_KEY, None)
        request = requests.get(group.id)
        if request is None:
            new.append(group)
        elif request.key in live:
            target = live[request.key]
            appends.setdefault(target.id, (target, []))[1].extend(group.curves)
        elif request.key in planned:
            planned[request.key].curves.extend(group.curves)
        else:
            name = request.name
            suffix = 2
            while name in names:
                name = f"{request.name} {suffix}"
                suffix += 1
            names.add(name)
            group.name = name
            group.metadata.update({
                IMPORT_PROCESSOR_KEY: processor_id,
                IMPORT_DESTINATION_KEY: request.key,
            })
            planned[request.key] = group
            new.append(group)
    return new, list(appends.values())


class FolderScan:
    def __init__(self, folder, contains="", *, include_existing=False, modified=False, settle=2.0):
        self.folder = Path(folder).resolve()
        if not self.folder.is_dir():
            raise ValueError("Choose an existing folder.")
        self.contains = contains.casefold()
        self.modified = modified
        self.settle = max(0.1, float(settle))
        self.observed = {}
        self.consumed = {}
        self.failed = {}
        if not include_existing:
            self.consumed = dict(self.files())

    def files(self):
        for path in sorted(self.folder.iterdir()):
            if path.is_symlink() or not path.is_file() or self.contains not in path.name.casefold():
                continue
            if path.name.startswith(".") or path.suffix.lower() in {
                ".tmp",
                ".part",
                ".partial",
                ".fitproj",
            }:
                continue
            try:
                stat = path.stat()
                yield path, (stat.st_size, stat.st_mtime_ns)
            except OSError:
                continue

    def ready(self, now=None):
        now = time.monotonic() if now is None else now
        ready = []
        for path, signature in self.files():
            if signature[0] == 0 or self.failed.get(path) == signature:
                continue
            if path in self.consumed and (not self.modified or self.consumed[path] == signature):
                continue
            previous = self.observed.get(path)
            if previous is None or previous[0] != signature:
                self.observed[path] = (signature, now)
            elif now - previous[1] >= self.settle:
                ready.append((path, signature))
        return ready


CURVE_RESULT_MAPS = frozenset({
    "fit_by_curve", "uncertainty_by_curve", "uncertainty_reports_by_curve",
    "uncertainty_failures_by_curve", "uncertainty_display_method_by_curve", "global_fit_baselines",
})


def merge_acquisition_results(existing, incoming, curve_ids):
    """Merge only schema-defined keyed records; never drop prior analyses."""
    import copy
    merged = dict(existing)
    history = list(existing.get("import_result_history", []))
    for key, value in incoming.items():
        if key == "import_result_history":
            if not isinstance(value, list):
                raise ValueError("Import result history must be a list.")
            history.extend(copy.deepcopy(value))
            continue
        if key in CURVE_RESULT_MAPS:
            previous = existing.get(key, {})
            if not isinstance(previous, dict) or not isinstance(value, dict):
                raise ValueError(f"Import result '{key}' must be a mapping.")
            if key != "global_fit_baselines" and not set(value) <= curve_ids:
                raise ValueError(f"Import result '{key}' refers to unrelated spectra.")
            if set(previous) & set(value):
                raise ValueError(f"Import result '{key}' collides with existing analyses.")
            merged[key] = {**previous, **copy.deepcopy(value)}
        else:
            if key in existing:
                history.append({"key": key, "value": existing[key]})
            merged[key] = copy.deepcopy(value)
    if history:
        merged["import_result_history"] = history
    return merged
