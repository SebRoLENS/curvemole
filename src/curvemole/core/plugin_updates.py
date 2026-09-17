"""Validated community plugin updates, staged without executing downloaded code."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from curvemole.core.errors import CurveMoleError
from curvemole.core.plugins import PluginCandidate, PluginManager, PluginMetadata
from curvemole.version import PLUGIN_API_VERSION

DOWNLOAD_ROOT = "https://github.com/SebRoLENS/curvemole/releases/download/community-plugins-latest"
CATALOG_URL = DOWNLOAD_ROOT + "/catalog.json"
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_EXTRACTED_BYTES = 80 * 1024 * 1024


def version(value: str) -> tuple[int, ...] | None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        return None
    return tuple(map(int, value.split(".")))


@dataclass(frozen=True)
class PluginUpdate:
    identifier: str
    name: str
    current: str
    latest: str
    folder: str
    sha256: str
    api: str
    capabilities: tuple[str, ...]

    @property
    def url(self) -> str:
        return f"{DOWNLOAD_ROOT}/{self.folder}.zip"

    @property
    def compatible(self) -> bool:
        return self.api == PLUGIN_API_VERSION


@dataclass(frozen=True)
class CommunityPlugin:
    identifier: str
    name: str
    description: str
    author: str
    latest: str
    folder: str
    sha256: str
    api: str
    licence: str
    capabilities: tuple[str, ...]

    @property
    def url(self) -> str:
        return f"{DOWNLOAD_ROOT}/{self.folder}.zip"

    @property
    def compatible(self) -> bool:
        return self.api == PLUGIN_API_VERSION


def community_plugins(payload: Any) -> list[CommunityPlugin]:
    """Validate and return every entry in the signed-off community catalog."""
    if not isinstance(payload, dict) or not isinstance(payload.get("plugins"), list):
        raise CurveMoleError("Invalid community plugin catalog.")
    result, identifiers = [], set()
    for item in payload["plugins"]:
        required = ("identifier", "name", "description", "author", "version", "folder",
                    "sha256", "api_compatibility", "licence", "capabilities")
        if (not isinstance(item, dict) or any(key not in item for key in required)
                or any(not isinstance(item[key], str) or not item[key].strip()
                       for key in required if key != "capabilities")
                or not isinstance(item["capabilities"], list)
                or not all(isinstance(value, str) for value in item["capabilities"])
                or version(item["version"]) is None
                or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", item["folder"])
                or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])):
            raise CurveMoleError("Invalid community plugin catalog entry.")
        if item["identifier"] in identifiers:
            raise CurveMoleError("Duplicate plugin identifier in catalog.")
        identifiers.add(item["identifier"])
        result.append(CommunityPlugin(
            item["identifier"], item["name"], item["description"], item["author"],
            item["version"], item["folder"], item["sha256"], item["api_compatibility"],
            item["licence"], tuple(item["capabilities"]),
        ))
    return result


def available_updates(manager: PluginManager, payload: Any) -> tuple[list[PluginUpdate], list[str]]:
    """Only running local plugins are eligible; never install catalog additions."""
    catalog = {item.identifier: item for item in community_plugins(payload)}
    updates, unsupported = [], []
    for identifier, metadata in manager.loaded.items():
        if identifier in manager.errors:
            continue
        installed = manager.installed.get(identifier, {})
        if not installed.get("enabled"):
            continue
        item = catalog.get(identifier)
        current = version(metadata.version)
        if item is None or installed.get("kind") != "local" or current is None:
            unsupported.append(identifier)
            continue
        latest = version(item.latest)
        pending = version(str(installed.get("metadata", {}).get("version", "")))
        if latest <= max(current, pending or current):
            continue
        updates.append(PluginUpdate(identifier, item.name, metadata.version, item.latest,
                                    item.folder, item.sha256, item.api, item.capabilities))
    return updates, unsupported


def _unpack(archive: bytes, root: Path, update: PluginUpdate) -> Path:
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise CurveMoleError("Plugin download exceeds the size limit.")
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        members = bundle.infolist()
        if len(members) > 2000 or sum(item.file_size for item in members) > MAX_EXTRACTED_BYTES:
            raise CurveMoleError("Plugin archive exceeds the extraction limit.")
        seen = set()
        for member in members:
            path = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if (not path.parts or path.is_absolute() or path.parts[0] != update.folder
                    or any(part in (".", "..") or ":" in part for part in path.parts)
                    or "\\" in member.filename or stat.S_ISLNK(mode)
                    or path.as_posix().casefold() in seen):
                raise CurveMoleError("Unsafe or duplicate path in plugin archive.")
            seen.add(path.as_posix().casefold())
            destination = root.joinpath(*path.parts)
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
    folder = root / update.folder
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*"), key=lambda item: item.relative_to(folder).as_posix()):
        if path.is_file():
            digest.update(path.relative_to(folder).as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
    if digest.hexdigest() != update.sha256:
        raise CurveMoleError("Plugin checksum mismatch. Check for updates again and retry.")
    return folder


def stage_update(manager: PluginManager, update: PluginUpdate, archive: bytes) -> None:
    """Atomically switch the next-startup record; running code and source stay intact."""
    current = manager.loaded.get(update.identifier)
    record = manager.installed.get(update.identifier)
    if (current is None or current.version != update.current or not record
            or not record.get("enabled") or update.identifier in manager.errors
            or record.get("kind") != "local"):
        raise CurveMoleError("Plugin is no longer loaded; check for updates again.")
    if not update.compatible:
        raise CurveMoleError("Update CurveMole first: this plugin requires a different plugin API.")
    installed_version = version(str(record["metadata"]["version"]))
    if version(update.latest) is None or version(update.latest) <= (installed_version or ()):
        raise CurveMoleError("This plugin version is already installed or newer.")
    if manager.storage is None:
        raise CurveMoleError("Persistent plugin storage is unavailable.")
    staging = manager.storage / "updates"
    staging.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="plugin-", dir=staging))
    original = copy.deepcopy(record)
    committed = False
    try:
        folder = _unpack(archive, temporary, update)
        manifests = list(folder.glob("*.curvemole-plugin.json"))
        if len(manifests) != 1:
            raise CurveMoleError("Update must contain exactly one plugin manifest.")
        manifest = manifests[0]
        metadata = PluginMetadata.from_mapping(json.loads(manifest.read_text(encoding="utf-8")),
                                               source=str(manifest))
        if (metadata.identifier != update.identifier or metadata.version != update.latest
                or metadata.api_compatibility != update.api
                or metadata.capabilities != update.capabilities
                or not re.fullmatch(r"[a-zA-Z0-9_]+\.py", metadata.module or "")
                or not (folder / metadata.module).is_file()):
            raise CurveMoleError("Plugin manifest does not match the validated catalog.")
        candidate = PluginCandidate(metadata, str(manifest), "local")
        manager.installed[update.identifier] = {
            "metadata": asdict(metadata), "reference": str(manifest), "kind": "local",
            "fingerprint": manager._fingerprint(candidate), "enabled": True,
            "symbol": manager.symbol(update.identifier),
        }
        try:
            manager._save()
        except Exception:
            manager.installed[update.identifier] = original
            raise
        committed = True
    finally:
        if not committed:
            shutil.rmtree(temporary, ignore_errors=True)


def install_community_plugin(
    manager: PluginManager, plugin: CommunityPlugin, archive: bytes, destination: str | Path
) -> PluginMetadata:
    """Verify, retain and load one previously uninstalled validated plugin."""
    if plugin.identifier in manager.installed or plugin.identifier in manager.loaded:
        raise CurveMoleError("This plugin is already installed; use Plugin updates instead.")
    if not plugin.compatible:
        raise CurveMoleError("Update CurveMole first: this plugin requires a different plugin API.")
    root = Path(destination).expanduser().resolve()
    if not root.is_dir():
        raise CurveMoleError("Choose an existing folder for downloaded plugins.")
    final = root / plugin.folder
    if final.exists():
        raise CurveMoleError(f"Destination already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=".curvemole-plugin-", dir=root))
    moved = False
    try:
        folder = _unpack(archive, temporary, plugin)
        manifests = list(folder.glob("*.curvemole-plugin.json"))
        if len(manifests) != 1:
            raise CurveMoleError("Plugin must contain exactly one manifest.")
        manifest = manifests[0]
        metadata = PluginMetadata.from_mapping(
            json.loads(manifest.read_text(encoding="utf-8")), source=str(final / manifest.name)
        )
        if (metadata.identifier != plugin.identifier or metadata.version != plugin.latest
                or metadata.api_compatibility != plugin.api
                or metadata.capabilities != plugin.capabilities
                or not re.fullmatch(r"[a-zA-Z0-9_]+\.py", metadata.module or "")
                or not (folder / metadata.module).is_file()):
            raise CurveMoleError("Plugin manifest does not match the validated catalog.")
        folder.rename(final)
        moved = True
        candidate = PluginCandidate(metadata, str(final / manifest.name), "local")
        return manager.load(candidate, trust=True)
    except Exception:
        if moved:
            shutil.rmtree(final, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
