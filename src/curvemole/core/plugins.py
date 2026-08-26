"""Explicitly trusted plugin discovery and loading."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from curvemole.core.errors import CurveMoleError, PluginTrustError
from curvemole.core.registry import FunctionRegistry, default_registry
from curvemole.version import PLUGIN_API_VERSION


@dataclass(frozen=True, slots=True)
class PluginMetadata:
    identifier: str
    version: str
    api_compatibility: str
    licence: str
    capabilities: tuple[str, ...]
    source: str
    module: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, source: str) -> PluginMetadata:
        missing = [
            name
            for name in ("identifier", "version", "api_compatibility", "licence", "capabilities")
            if name not in value
        ]
        if missing:
            raise CurveMoleError(f"Plugin metadata is missing: {', '.join(missing)}")
        return cls(
            identifier=str(value["identifier"]),
            version=str(value["version"]),
            api_compatibility=str(value["api_compatibility"]),
            licence=str(value["licence"]),
            capabilities=tuple(str(item) for item in value["capabilities"]),
            source=source,
            module=str(value["module"]) if value.get("module") else None,
        )


@dataclass(frozen=True, slots=True)
class PluginCandidate:
    metadata: PluginMetadata
    reference: str
    kind: str


class PluginManager:
    def __init__(
        self,
        registry: FunctionRegistry | None = None,
        *,
        trusted_identifiers: set[str] | None = None,
    ) -> None:
        self.registry = registry or default_registry()
        self.trusted_identifiers = set(trusted_identifiers or ())
        self.loaded: dict[str, PluginMetadata] = {}

    def discover_local(self, directory: str | Path) -> list[PluginCandidate]:
        root = Path(directory)
        if not root.exists():
            return []
        candidates: list[PluginCandidate] = []
        for manifest in sorted(root.glob("*.curvemole-plugin.json")):
            try:
                metadata = PluginMetadata.from_mapping(
                    json.loads(manifest.read_text(encoding="utf-8")), source=str(manifest.resolve())
                )
            except (OSError, json.JSONDecodeError, CurveMoleError):
                continue
            candidates.append(PluginCandidate(metadata, str(manifest), "local"))
        return candidates

    def discover_entry_points(self) -> list[PluginCandidate]:
        result: list[PluginCandidate] = []
        for entry_point in importlib.metadata.entry_points(group="curvemole.functions"):
            metadata = PluginMetadata(
                identifier=entry_point.name,
                version=_distribution_version(entry_point),
                api_compatibility=PLUGIN_API_VERSION,
                licence="declared by package",
                capabilities=("functions",),
                source=f"Python entry point: {entry_point.value}",
                module=entry_point.value,
            )
            result.append(PluginCandidate(metadata, entry_point.name, "entry_point"))
        return result

    def load(self, candidate: PluginCandidate, *, trust: bool = False) -> PluginMetadata:
        metadata = candidate.metadata
        if metadata.api_compatibility != PLUGIN_API_VERSION:
            raise CurveMoleError(
                f"Plugin '{metadata.identifier}' targets API {metadata.api_compatibility}; "
                f"CurveMole provides API {PLUGIN_API_VERSION}."
            )
        if not trust and metadata.identifier not in self.trusted_identifiers:
            raise PluginTrustError(
                f"Plugin '{metadata.identifier}' is untrusted. Review source '{metadata.source}' "
                "and explicitly approve execution."
            )
        if candidate.kind == "local":
            module = self._load_local(candidate)
        elif candidate.kind == "entry_point":
            entry = next(
                (
                    value
                    for value in importlib.metadata.entry_points(group="curvemole.functions")
                    if value.name == candidate.reference
                ),
                None,
            )
            if entry is None:
                raise CurveMoleError(f"Plugin entry point disappeared: {candidate.reference}")
            loaded = entry.load()
            module = loaded if isinstance(loaded, ModuleType) else None
            register = getattr(loaded, "register", loaded if callable(loaded) else None)
            if register is None:
                raise CurveMoleError(f"Plugin '{metadata.identifier}' exposes no register function.")
            register(self.registry)
            self.trusted_identifiers.add(metadata.identifier)
            self.loaded[metadata.identifier] = metadata
            return metadata
        else:
            raise CurveMoleError(f"Unknown plugin candidate kind: {candidate.kind}")
        register = getattr(module, "register", None)
        if not callable(register):
            raise CurveMoleError(f"Plugin '{metadata.identifier}' must define register(registry).")
        register(self.registry)
        self.trusted_identifiers.add(metadata.identifier)
        self.loaded[metadata.identifier] = metadata
        return metadata

    def _load_local(self, candidate: PluginCandidate) -> ModuleType:
        manifest = Path(candidate.reference)
        module_name = candidate.metadata.module
        if not module_name:
            raise CurveMoleError(f"Local plugin manifest '{manifest}' has no module field.")
        source = (manifest.parent / module_name).resolve()
        if not source.is_file() or source.suffix != ".py":
            raise CurveMoleError(f"Plugin source does not exist or is not a Python file: {source}")
        spec = importlib.util.spec_from_file_location(
            f"curvemole_plugin_{candidate.metadata.identifier}", source
        )
        if spec is None or spec.loader is None:
            raise CurveMoleError(f"Cannot create loader for plugin source: {source}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def export_custom_function(definition: Any, path: str | Path) -> Path:
    metadata = getattr(definition, "custom_metadata", {})
    if not metadata.get("formula"):
        raise CurveMoleError("Only formula-based custom functions can be exported as JSON.")
    destination = Path(path)
    payload = {
        "format": "CurveMole custom function",
        "schema_version": 1,
        "identifier": definition.identifier,
        "display_name": definition.display_name,
        "kind": definition.kind,
        **metadata,
    }
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return destination


def import_custom_function(path: str | Path) -> Any:
    from curvemole.core.functions import formula_definition

    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CurveMoleError(f"Cannot read custom function '{source}': {exc}") from exc
    if payload.get("format") != "CurveMole custom function" or payload.get("schema_version") != 1:
        raise CurveMoleError("Unsupported custom-function file.")
    return formula_definition(
        str(payload["identifier"]),
        str(payload["display_name"]),
        str(payload["formula"]),
        kind=str(payload.get("kind", "generic")),
        defaults=payload.get("defaults"),
        bounds={key: tuple(value) for key, value in payload.get("bounds", {}).items()},
        derived_formulas=payload.get("derived_formulas"),
    )


def _distribution_version(entry_point: importlib.metadata.EntryPoint) -> str:
    distribution = getattr(entry_point, "dist", None)
    return str(distribution.version) if distribution is not None else "unknown"
