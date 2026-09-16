"""Explicitly trusted plugin discovery and loading."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
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
    name: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, source: str) -> PluginMetadata:
        if not isinstance(value, Mapping):
            raise CurveMoleError("Plugin metadata must be a JSON object.")
        if not isinstance(value.get("capabilities"), list):
            raise CurveMoleError("Plugin capabilities must be a list.")
        if not str(value.get("identifier", "")).strip():
            raise CurveMoleError("Plugin identifier cannot be empty.")
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
            name=str(value.get("name", "")),
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
        storage: str | Path | None = None,
    ) -> None:
        self.registry = registry or default_registry()
        self.trusted_identifiers = set(trusted_identifiers or ())
        self.loaded: dict[str, PluginMetadata] = {}
        self.function_owners: dict[str, str] = {}
        self.storage = Path(storage) if storage is not None else None
        self.installed: dict[str, dict[str, Any]] = {}
        self.errors: dict[str, str] = {}
        self.symbols: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.session_path: Path | None = None
        if self.storage:
            self.storage.mkdir(parents=True, exist_ok=True)
            try:
                self.installed = json.loads((self.storage / "installed.json").read_text())
                if not isinstance(self.installed, dict):
                    self.installed = {}
                self.installed = {key: value for key, value in self.installed.items()
                                  if isinstance(key, str) and isinstance(value, dict)}
            except (OSError, ValueError):
                self.installed = {}

    def symbol(self, identifier: str) -> str:
        from curvemole.core.plugin_identity import SYMBOLS
        if identifier not in self.symbols:
            used = set(self.symbols.values()) | {
                str(record.get("symbol", "")) for record in self.installed.values()}
            saved = self.installed.get(identifier, {}).get("symbol")
            if saved and saved not in self.symbols.values():
                self.symbols[identifier] = saved
            else:
                index = 0
                while True:
                    candidate = SYMBOLS[index] if index < len(SYMBOLS) else f"◆{index + 1}"
                    if candidate not in used:
                        self.symbols[identifier] = candidate
                        break
                    index += 1
        return self.symbols[identifier]

    def plugin_name(self, identifier: str) -> str:
        return self.names.get(identifier) or self.installed.get(identifier, {}).get(
            "metadata", {}).get("name") or identifier

    def _save(self) -> None:
        if self.storage:
            destination = self.storage / "installed.json"
            temporary = destination.with_suffix(f".{uuid.uuid4().hex}.tmp")
            temporary.write_text(json.dumps(self.installed, indent=2), encoding="utf-8")
            temporary.replace(destination)

    def start_session(self) -> bool:
        """Quarantine persisted plugins after an unclean *previous process* exit."""
        if not self.storage:
            return False
        unclean = False
        for marker in self.storage.glob("session-*.json"):
            try:
                pid = int(json.loads(marker.read_text())["pid"])
                if not _process_alive(pid):
                    raise ProcessLookupError(pid)
            except PermissionError:
                continue
            except (OSError, ValueError, KeyError):
                unclean = True
                marker.unlink(missing_ok=True)
        if unclean:
            for record in self.installed.values():
                record["enabled"] = False
                record["error"] = "Disabled after an abnormal exit. Review and enable manually."
            self._save()
        self.session_path = self.storage / f"session-{uuid.uuid4().hex}.json"
        self.session_path.write_text(json.dumps({"pid": os.getpid()}))
        return unclean and bool(self.installed)

    def finish_session(self) -> None:
        if self.session_path:
            self.session_path.unlink(missing_ok=True)

    def installed_candidates(self) -> list[PluginCandidate]:
        result = []
        for record in self.installed.values():
            try:
                result.append(PluginCandidate(PluginMetadata(**record["metadata"]),
                                               record["reference"], record["kind"]))
            except (KeyError, TypeError):
                continue
        return result

    def autoload(self) -> None:
        if os.environ.get("CURVEMOLE_DISABLE_PLUGINS") == "1":
            return
        for candidate in self.installed_candidates():
            record = self.installed[candidate.metadata.identifier]
            if not record.get("enabled"):
                continue
            try:
                if record.get("fingerprint") != self._fingerprint(candidate):
                    raise CurveMoleError("Plugin source changed; review and trust it again.")
                self.load(candidate, trust=True)
            except Exception as exc:
                self.disable(candidate.metadata.identifier, str(exc))

    def _fingerprint(self, candidate: PluginCandidate) -> str:
        if candidate.kind != "local":
            return candidate.metadata.version
        manifest = Path(candidate.reference)
        source = manifest.parent / (candidate.metadata.module or "")
        return hashlib.sha256(manifest.read_bytes() + source.read_bytes()).hexdigest()

    def invoke(self, owner: str, callback: Any, *args: Any, **kwargs: Any) -> Any:
        if owner in self.errors:
            raise CurveMoleError(f"Plugin {owner} is disabled: {self.errors[owner]}")
        try:
            return callback(*args, **kwargs)
        except BaseException as exc:
            from curvemole.core.errors import FitCancelled
            if isinstance(exc, FitCancelled):
                raise
            self.errors[owner] = str(exc)
            if owner in self.installed:
                self.installed[owner].update(enabled=False, error=str(exc))
                self._save()
            raise CurveMoleError(f"Plugin {owner} failed and was disabled: {exc}") from exc

    def disable(self, identifier: str, reason: str = "Disabled by user") -> None:
        from curvemole.core.extensions import extensions
        extensions.remove_owner(identifier)
        for function, owner in list(self.function_owners.items()):
            if owner == identifier:
                if (function in self.registry.identifiers()
                        and self.registry.get(function).custom_metadata.get("plugin_owner") == identifier):
                    self.registry.unregister(function)
                del self.function_owners[function]
        self.loaded.pop(identifier, None)
        if identifier in self.installed:
            self.installed[identifier].update(enabled=False, error=reason)
            self._save()

    def remove(self, identifier: str) -> None:
        self.disable(identifier)
        self.installed.pop(identifier, None)
        self.trusted_identifiers.discard(identifier)
        self._save()


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
        if metadata.identifier in self.loaded:
            raise CurveMoleError("Plugin already loaded; disable it before reloading.")
        from curvemole.core.extensions import PluginAPI
        fingerprint = self._fingerprint(candidate)
        self.errors.pop(metadata.identifier, None)
        self.names[metadata.identifier] = metadata.name or metadata.identifier
        try:
            if candidate.kind == "local":
                loaded = self._load_local(candidate)
            elif candidate.kind == "entry_point":
                entry = next((value for value in importlib.metadata.entry_points(
                    group="curvemole.functions") if value.name == candidate.reference), None)
                if entry is None:
                    raise CurveMoleError("Plugin entry point disappeared.")
                loaded = entry.load()
            else:
                raise CurveMoleError(f"Unknown plugin kind: {candidate.kind}")
            register = getattr(loaded, "register", loaded if callable(loaded) else None)
            if not callable(register):
                raise CurveMoleError("Plugin must define register(api).")
            register(PluginAPI(self, metadata.identifier))
        except BaseException as exc:
            self.disable(metadata.identifier, "Loading failed")
            raise CurveMoleError(f"Plugin loading failed: {exc}") from exc
        self.trusted_identifiers.add(metadata.identifier)
        self.loaded[metadata.identifier] = metadata
        self.installed[metadata.identifier] = {
            "metadata": asdict(metadata), "reference": str(Path(candidate.reference).resolve())
            if candidate.kind == "local" else candidate.reference,
            "kind": candidate.kind, "fingerprint": fingerprint, "enabled": True,
            "symbol": self.symbol(metadata.identifier),
        }
        self._save()
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


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied: assume alive.
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
