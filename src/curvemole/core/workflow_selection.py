"""Resolve explicit and batch curve selectors used by declarative workflows."""

from __future__ import annotations

from collections.abc import Mapping
from fnmatch import fnmatchcase
from typing import Any

from curvemole.core.errors import CurveMoleError
from curvemole.core.project import Project

SELECTOR_KEYS = frozenset({"curve", "curves", "match"})


def validate_curve_selector(
    specification: Mapping[str, Any], *, default_all: bool = False,
) -> list[str]:
    """Check selector shape without loading data or evaluating a project."""
    present = [name for name in SELECTOR_KEYS if name in specification]
    if len(present) > 1:
        return ["choose only one of curve, curves, or match"]
    if not present:
        return [] if default_all else ["one of curve, curves, or match is required"]
    name = present[0]
    value = specification[name]
    if name == "curves":
        if isinstance(value, str):
            return [] if value in {"all", "first", "last"} else [
                "curves must be 'all', 'first', 'last', or a non-empty list"
            ]
        if not isinstance(value, list) or not value:
            return ["curves must be 'all', 'first', 'last', or a non-empty list"]
        if any(not isinstance(item, str) or not item.strip() for item in value):
            return ["curves must contain non-empty curve names or identities"]
        if len(value) != len(set(value)):
            return ["curves must not contain duplicate selectors"]
    elif not isinstance(value, str) or not value.strip():
        return [f"{name} must be a non-empty string"]
    return []


def select_curve_ids(
    project: Project,
    aliases: Mapping[str, str],
    *,
    curve: str | None = None,
    curves: str | list[str] | None = None,
    match: str | None = None,
    default_all: bool = False,
) -> list[str]:
    """Resolve selectors, preserving explicit order or project order for batches.

    ``curves='all'`` selects every curve; ``first``/``last`` select one by order.
    ``match`` uses case-sensitive shell
    patterns against display names and supplied alias/identity keys. Alias keys
    take precedence over runtime IDs and unique display names for exact lookup.
    """
    specification = {
        name: value for name, value in (("curve", curve), ("curves", curves), ("match", match))
        if value is not None
    }
    errors = validate_curve_selector(specification, default_all=default_all)
    if errors:
        raise CurveMoleError("Invalid curve selector: " + "; ".join(errors))
    available = project.curves
    identities = {item.id for item in available}

    def resolve(value: str) -> str:
        if value in aliases:
            identity = aliases[value]
            if identity in identities:
                return identity
            raise CurveMoleError(f"Curve selector '{value}' refers to an unavailable curve.")
        if value in identities:
            return value
        named = [item.id for item in available if item.name == value]
        if len(named) == 1:
            return named[0]
        if named:
            raise CurveMoleError(
                f"Ambiguous curve selector '{value}'; use a unique alias or workflow identity."
            )
        raise CurveMoleError(f"Unknown curve selector: {value}")

    if match is not None:
        matching = {identity for name, identity in aliases.items() if fnmatchcase(name, match)}
        selected = [
            item.id for item in available
            if fnmatchcase(item.name, match) or item.id in matching
        ]
    elif not specification or curves == "all":
        selected = [item.id for item in available]
    elif curves == "first":
        selected = [available[0].id] if available else []
    elif curves == "last":
        selected = [available[-1].id] if available else []
    else:
        requested = [curve] if curve is not None else curves
        selected = [resolve(value) for value in requested]
    if not selected:
        suffix = f" pattern '{match}'" if match is not None else ""
        raise CurveMoleError(f"No curves selected by{suffix or ' the workflow selector'}.")
    if len(selected) != len(set(selected)):
        raise CurveMoleError("Curve selectors resolve to the same curve more than once.")
    return selected
