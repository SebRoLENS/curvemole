"""Deterministic, non-executing workflow input discovery and naming templates."""

from __future__ import annotations

import fnmatch
import glob
import os
import re
from collections.abc import Iterator, Mapping
from functools import cache
from pathlib import Path, PurePosixPath
from string import Formatter
from typing import Any

from curvemole.core.errors import CurveMoleError

_SOURCES = ("path", "glob", "directory")
_BATCH_OPTIONS = ("pattern", "recursive", "exclude", "sort", "allow_empty")
_TEMPLATE_FIELDS = frozenset(
    {"stem", "filename", "parent", "relative_path", "relative_stem", "file_index",
     "curve_index", "curve_name"}
)


def validate_name_template(template: Any) -> list[str]:
    """Return static errors for the supported plain ``{field}`` placeholders."""
    if not isinstance(template, str) or not template.strip():
        return ["name template must be a nonempty string"]
    errors: list[str] = []
    try:
        for _literal, name, spec, conversion in Formatter().parse(template):
            if name is None:
                continue
            if name not in _TEMPLATE_FIELDS:
                errors.append(f"unknown name-template field {name!r}")
            if spec or conversion:
                errors.append("name templates do not accept format specifications or conversions")
    except ValueError as exc:
        errors.append(f"invalid name template: {exc}")
    return errors


def validate_import_source(item: Mapping[str, Any]) -> list[str]:
    """Validate source-selection options without opening files or executing plugins."""
    if not isinstance(item, Mapping):
        return ["import must be a mapping"]
    errors: list[str] = []
    sources = [key for key in _SOURCES if key in item]
    if len(sources) != 1:
        errors.append("import must specify exactly one of path, glob, directory")
    for key in sources:
        if not isinstance(item[key], str) or not item[key].strip():
            errors.append(f"{key} must be a nonempty string")
        elif "\x00" in item[key]:
            errors.append(f"{key} must not contain a null character")
    if "path" in item:
        for key in _BATCH_OPTIONS:
            if key in item:
                errors.append(f"{key} is only supported with glob or directory")
    if "pattern" in item:
        if "directory" not in item:
            errors.append("pattern is only supported with directory")
        pattern = item["pattern"]
        if not isinstance(pattern, str) or not pattern.strip():
            errors.append("pattern must be a nonempty relative glob string")
        elif "\x00" in pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            errors.append("directory pattern must stay relative to its directory")
    for key in ("recursive", "allow_empty"):
        if key in item and not isinstance(item[key], bool):
            errors.append(f"{key} must be a boolean")
    if "sort" in item and (
        not isinstance(item["sort"], str) or item["sort"] not in {"natural", "lexical", "none"}
    ):
        errors.append("sort must be natural, lexical, or none")
    if "exclude" in item:
        excluded = item["exclude"]
        if not isinstance(excluded, list) or any(
            not isinstance(value, str) or not value.strip() for value in excluded
        ):
            errors.append("exclude must be a list of nonempty glob strings")
        elif any("\x00" in value or Path(value).is_absolute() or ".." in Path(value).parts
                 for value in excluded):
            errors.append("exclude patterns must stay relative to the source directory")
    pattern = item.get("glob", item.get("pattern", "*.csv"))
    if isinstance(pattern, str) and "**" in Path(pattern).parts and not item.get("recursive", False):
        errors.append("recursive: true is required for a '**' pattern")
    for key in ("alias_template", "curve_id_template"):
        if key in item:
            errors.extend(f"{key}: {error}" for error in validate_name_template(item[key]))
    return errors


def resolve_import_paths(item: Mapping[str, Any], root: Path) -> list[Path]:
    """Expand one import source into regular files; all paths are YAML-relative.

    Explicit file paths remain literal. Batch discovery skips symlinks and hidden
    entries unless a hidden path component is explicitly named in the pattern.
    ``recursive`` enables ``**`` for glob sources and searches directory patterns
    at any depth. Excludes match filenames or relative paths below the source base.
    """
    errors = validate_import_source(item)
    if errors:
        raise CurveMoleError("Invalid workflow import source: " + "; ".join(errors))
    root = Path(root).resolve()
    try:
        if "path" in item:
            path = _resolve(root, item["path"])
            if path.is_file():
                return [path.resolve()]
            if path.is_dir():
                raise CurveMoleError(f"Import path is a directory; use directory instead: {path}")
            suggestion = "; use glob for wildcard patterns" if glob.has_magic(item["path"]) else ""
            raise CurveMoleError(f"Import file does not exist: {path}{suggestion}")

        if "directory" in item:
            base = _resolve(root, item["directory"])
            _reject_symlink_prefix(base, root)
            if not base.is_dir():
                raise CurveMoleError(f"Import directory does not exist: {base}")
            parts = Path(item.get("pattern", "*.csv")).parts
            if item.get("recursive", False):
                parts = ("**", *parts)
        else:
            base, parts = _glob_source(root, item["glob"])
            _reject_symlink_prefix(base, root)

        excluded = item.get("exclude", [])
        # Adjacent recursive segments mean the same search without rewalking
        # each subtree once for every possible division between '**' segments.
        parts = tuple(part for index, part in enumerate(parts)
                      if part != "**" or index == 0 or parts[index - 1] != "**")
        paths: list[Path] = []
        seen: set[Path] = set()
        if base.is_dir():
            for path in _expand(base, tuple(parts)):
                relative = path.relative_to(base).as_posix()
                if any(_excluded(relative, pattern) for pattern in excluded):
                    continue
                canonical = path.resolve()
                if canonical not in seen:
                    paths.append(canonical)
                    seen.add(canonical)
        mode = item.get("sort", "natural")
        if mode == "lexical":
            paths.sort(key=lambda path: path.relative_to(base.resolve()).as_posix())
        elif mode == "natural":
            paths.sort(key=lambda path: _natural_key(path.relative_to(base.resolve()).as_posix()))
        if not paths and not item.get("allow_empty", False):
            selector = item.get("glob", str(base / item.get("pattern", "*.csv")))
            raise CurveMoleError(f"Workflow import matched no files: {selector}")
        return paths
    except OSError as exc:
        raise CurveMoleError(f"Cannot enumerate workflow imports: {exc}") from exc


def format_import_name(
    template: str,
    path: Path,
    root: Path,
    *,
    file_index: int,
    curve_index: int,
    curve_name: str,
) -> str:
    """Format a curve alias/identity; indices are one-based within one import item."""
    errors = validate_name_template(template)
    if errors:
        raise CurveMoleError("Invalid workflow name template: " + "; ".join(errors))
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 1
           for value in (file_index, curve_index)):
        raise CurveMoleError("Workflow file and curve template indices must be positive integers")
    path = Path(path).resolve()
    try:
        relative = Path(os.path.relpath(path, Path(root).resolve()))
    except ValueError:  # Absolute paths on a different Windows drive.
        relative = path
    values = {
        "stem": path.stem,
        "filename": path.name,
        "parent": path.parent.name,
        "relative_path": relative.as_posix(),
        "relative_stem": relative.with_suffix("").as_posix(),
        "file_index": file_index,
        "curve_index": curve_index,
        "curve_name": curve_name,
    }
    result = template.format_map(values)
    if not result.strip():
        raise CurveMoleError("Workflow name template produced an empty name")
    return result


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    # Keep declared directory symlinks visible to the caller's policy checks.
    return path if path.is_absolute() else root / path


def _reject_symlink_prefix(base: Path, root: Path) -> None:
    """Do not bypass discovery's symlink policy through a static glob prefix."""
    candidate = Path(os.path.abspath(base))
    while candidate != root:
        if candidate.is_symlink():
            raise CurveMoleError(f"Import directory must not traverse a symbolic link: {candidate}")
        if candidate == candidate.parent:
            break
        candidate = candidate.parent


def _glob_source(root: Path, pattern: str) -> tuple[Path, tuple[str, ...]]:
    path = Path(pattern)
    parts = path.parts
    first = next((index for index, part in enumerate(parts) if glob.has_magic(part)), None)
    if first is None:
        resolved = _resolve(root, pattern)
        return resolved.parent, (resolved.name,)
    prefix = Path(*parts[:first])
    base = prefix if path.is_absolute() else root / prefix
    return base, tuple(parts[first:])


def _expand(base: Path, parts: tuple[str, ...]) -> Iterator[Path]:
    if not parts:
        if base.is_file() and not base.is_symlink():
            yield base
        return
    component, remaining = parts[0], parts[1:]
    if component == "**":
        yield from _expand(base, remaining)
        for child in base.iterdir():
            if child.is_symlink() or child.name.startswith("."):
                continue
            if child.is_dir():
                yield from _expand(child, parts)
            elif not remaining and child.is_file():
                yield child
        return
    for child in base.iterdir():
        if child.is_symlink() or (child.name.startswith(".") and not component.startswith(".")):
            continue
        if not fnmatch.fnmatchcase(child.name, component):
            continue
        if remaining:
            if child.is_dir():
                yield from _expand(child, remaining)
        elif child.is_file():
            yield child


def _excluded(relative: str, pattern: str) -> bool:
    parts = PurePosixPath(pattern.replace(os.sep, "/")).parts
    path_parts = PurePosixPath(relative).parts
    if len(parts) == 1:
        return fnmatch.fnmatchcase(path_parts[-1], parts[0])

    @cache
    def matches(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(parts):
            return path_index == len(path_parts)
        if parts[pattern_index] == "**":
            return matches(path_index, pattern_index + 1) or (
                path_index < len(path_parts) and matches(path_index + 1, pattern_index)
            )
        return (path_index < len(path_parts)
                and fnmatch.fnmatchcase(path_parts[path_index], parts[pattern_index])
                and matches(path_index + 1, pattern_index + 1))

    return matches(0, 0)


def _natural_key(value: str) -> tuple[tuple[tuple[int, Any], ...], str]:
    tokens = tuple((0, int(part)) if part.isdecimal() else (1, part.casefold())
                   for part in re.split(r"(\d+)", value))
    return tokens, value
