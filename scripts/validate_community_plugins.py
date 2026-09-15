"""Validate community submissions; produce a catalog only after every check passes.

Plugin code runs only in child processes, with timeouts. This is NOT a sandbox:
run on disposable, unprivileged CI workers without secrets.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = {"functions", "importers", "exporters", "transformations", "analysis", "actions",
         "workflows", "panels", "plot_layers", "hooks", "fit_solvers"}


def inspect_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"identifier", "name", "description", "author", "version", "api_compatibility",
                "licence", "capabilities", "module", "test_file"}
    if not isinstance(data, dict) or not required <= data.keys():
        raise ValueError(f"{path}: missing manifest fields")
    for key in required - {"capabilities"}:
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"{path}: {key} must be a nonempty string")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]+", data["identifier"]):
        raise ValueError("Invalid plugin identifier")
    if not re.fullmatch(r"\d+\.\d+\.\d+", data["version"]) or data["api_compatibility"] != "1":
        raise ValueError("Use a major.minor.patch version and plugin API 1")
    capabilities = data["capabilities"]
    if (not isinstance(capabilities, list) or not capabilities
            or any(not isinstance(value, str) or value not in KINDS for value in capabilities)
            or len(set(capabilities)) != len(capabilities)):
        raise ValueError("Invalid or duplicate capabilities")
    for key in ("module", "test_file"):
        name = data[key]
        if not re.fullmatch(r"[a-zA-Z0-9_]+\.py", name) or not (path.parent / name).is_file():
            raise ValueError(f"{key} must name a local Python file")
    for name in ("README.md", "LICENSE"):
        if not (path.parent / name).is_file() or not (path.parent / name).read_text().strip():
            raise ValueError(f"Missing {name}")
    for source in path.parent.rglob("*.py"):
        ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    return data


def fingerprint(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*"), key=lambda item: item.relative_to(folder).as_posix()):
        if "__pycache__" in path.parts or ".pytest_cache" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise ValueError("Symlinks are not allowed in community plugins")
        if path.is_file():
            digest.update(path.relative_to(folder).as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def smoke(path: Path):
    from curvemole.core.extensions import extensions
    from curvemole.core.plugins import PluginManager

    manager = PluginManager()
    candidate = next(item for item in manager.discover_local(path.parent)
                     if Path(item.reference).resolve() == path.resolve())
    manager.load(candidate, trust=True)
    identifier = candidate.metadata.identifier
    actual = {entry.kind for entry in extensions.entries.values() if entry.owner == identifier}
    if identifier in manager.function_owners.values():
        actual.add("functions")
    if actual != set(candidate.metadata.capabilities):
        raise ValueError(f"Declared capabilities differ from registered contributions: {actual}")
    manager.disable(identifier)
    if any(entry.owner == identifier for entry in extensions.entries.values()):
        raise ValueError("Plugin contributions could not be removed")


def validate(root: Path, output: Path):
    output.unlink(missing_ok=True)
    records = []
    identifiers = set()
    folders = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    for folder in folders:
        if folder.is_symlink():
            raise ValueError("Plugin folders cannot be symlinks")
        manifests = list(folder.glob("*.curvemole-plugin.json"))
        if len(manifests) != 1:
            raise ValueError(f"{folder}: exactly one manifest is required")
        manifest = manifests[0]
        data = inspect_manifest(manifest)
        if data["identifier"] in identifiers:
            raise ValueError("Duplicate plugin identifier")
        identifiers.add(data["identifier"])
        before = fingerprint(folder)
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--smoke", str(manifest.resolve())],
                       check=True, timeout=60, env=environment)
        subprocess.run([sys.executable, "-m", "pytest", "-q", "--confcutdir", str(folder.resolve()),
                        str((folder / data["test_file"]).resolve())],
                       check=True, timeout=120, env=environment)
        if fingerprint(folder) != before:
            raise ValueError("Plugin files changed during validation")
        records.append({**data, "folder": folder.name, "sha256": before})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"plugins": records}, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "custom_plugins")
    parser.add_argument("--output", type=Path, default=ROOT / "build/community-catalog.json")
    parser.add_argument("--smoke", type=Path)
    args = parser.parse_args()
    if args.smoke:
        smoke(args.smoke)
    else:
        validate(args.root, args.output)
