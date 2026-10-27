"""Shared final-version target for beta builds and explicit stable promotion."""
from __future__ import annotations

import json
import re
from pathlib import Path

TARGET_FILE = Path(".github/release-target.json")


def version_tuple(version: str) -> tuple[int, int, int]:
    if not isinstance(version, str) or not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        raise ValueError("The release target must be a final MAJOR.MINOR.PATCH version")
    return tuple(map(int, version.split(".")))


def read_target(root: Path = Path(".")) -> str:
    path = root / TARGET_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read release target from {path}") from exc
    if not isinstance(data, dict) or set(data) != {"version"}:
        raise ValueError(f"{path} must contain only a version field")
    version = data["version"]
    version_tuple(version)
    return version


def beta_target(stable: str, root: Path = Path(".")) -> str:
    target = read_target(root)
    if version_tuple(target) <= version_tuple(stable):
        raise ValueError("Set .github/release-target.json to a version newer than the stable baseline")
    return target


def promotion_target(requested: str = "", root: Path = Path(".")) -> str:
    target = read_target(root)
    if requested and requested != target:
        raise ValueError(f"Promotion must match the tested target {target}; change release-target.json first")
    return target


def advance_target(released: str, root: Path = Path(".")) -> bool:
    """Start the next patch cycle after stable sync; preserve any newer explicit target."""
    target = read_target(root)
    if version_tuple(target) > version_tuple(released):
        return False
    major, minor, patch = version_tuple(released)
    (root / TARGET_FILE).write_text(json.dumps({"version": f"{major}.{minor}.{patch + 1}"}, indent=2) + "\n", encoding="utf-8")
    return True
