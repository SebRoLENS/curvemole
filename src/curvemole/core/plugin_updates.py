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
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any

from curvemole.core.errors import CurveMoleError
from curvemole.core.plugins import PluginCandidate, PluginManager, PluginMetadata
from curvemole.version import PLUGIN_API_VERSION

DOWNLOAD_ROOT = "https://github.com/SebRoLENS/curvemole/releases/download/community-plugins-latest"
CATALOG_URL = DOWNLOAD_ROOT + "/catalog.json"
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_EXTRACTED_BYTES = 80 * 1024 * 1024


class PluginUpdateLocationError(CurveMoleError):
    """The user must choose another permanent plugin directory."""


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
    category: str = "by_community"

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
                or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
                or not isinstance(item.get("category", "by_community"), str)
                or item.get("category", "by_community") not in
                {"by_main_developer", "by_community"}):
            raise CurveMoleError("Invalid community plugin catalog entry.")
        if item["identifier"] in identifiers:
            raise CurveMoleError("Duplicate plugin identifier in catalog.")
        identifiers.add(item["identifier"])
        result.append(CommunityPlugin(
            item["identifier"], item["name"], item["description"], item["author"],
            item["version"], item["folder"], item["sha256"], item["api_compatibility"],
            item["licence"], tuple(item["capabilities"]),
            item.get("category", "by_community"),
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


@dataclass
class _SourceReplacement:
    target: Path
    temporary: Path

    def rollback(self):
        self.target.rename(self.temporary / "rejected")
        previous = self.temporary / "previous"
        if previous.exists():
            previous.rename(self.target)
        self.finish()

    def finish(self):
        shutil.rmtree(self.temporary, ignore_errors=True)


def _replace_source(record: dict, folder: Path, metadata: PluginMetadata):
    """Prepare a complete replacement beside the source, retaining unrelated files."""
    original = Path(record["reference"])
    target = original.parent
    temporary = None
    try:
        if target.is_symlink() or original.is_symlink():
            return None
        manifests = list(target.rglob("*.curvemole-plugin.json"))
        if len(manifests) != 1 or manifests[0].resolve() != original.resolve():
            # A flat/shared plugin directory must not be replaced as a whole.
            return None
        previous = PluginMetadata.from_mapping(
            json.loads(original.read_text(encoding="utf-8")), source=str(original))
        if (previous.identifier != metadata.identifier
                or (version(previous.version) or ()) > (version(metadata.version) or ())):
            return None
        temporary = Path(tempfile.mkdtemp(prefix=".curvemole-plugin-update-", dir=target.parent))
        replacement = temporary / "replacement"
        shutil.copytree(target, replacement, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        new_files = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
        old_files = set(record.get("files", [])) | {original.name, previous.module or ""}
        for name in old_files - new_files:
            path = PurePosixPath(name)
            if (not name or path.is_absolute() or "\\" in name
                    or any(part in (".", "..") or ":" in part for part in path.parts)):
                continue
            old = replacement.joinpath(*path.parts)
            if any(parent.is_symlink() for parent in old.parents if parent != replacement
                   and replacement in parent.parents):
                continue
            if old.is_file() or old.is_symlink():
                old.unlink()
        for source in folder.rglob("*"):
            destination = replacement / source.relative_to(folder)
            if any(parent.is_symlink() for parent in destination.parents
                   if parent != replacement and replacement in parent.parents):
                raise OSError("Plugin payload overlaps a symbolic-link directory.")
            if source.is_dir():
                if destination.is_symlink():
                    raise OSError("Plugin payload overlaps a symbolic-link directory.")
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.is_file() or destination.is_symlink():
                    destination.unlink()
                shutil.copy2(source, destination)
        target.rename(temporary / "previous")
    except (OSError, ValueError, CurveMoleError):
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        return None
    try:
        replacement.rename(target)
    except OSError:
        # Restore the untouched directory before choosing persistent fallback storage.
        (temporary / "previous").rename(target)
        shutil.rmtree(temporary, ignore_errors=True)
        return None
    return _SourceReplacement(target, temporary)


def _relocate_source(record: dict, folder: Path, metadata: PluginMetadata, destination: str | Path):
    """Retain the update only in a directory explicitly chosen by the user."""
    root = Path(destination).expanduser().resolve()
    if not root.is_dir():
        raise PluginUpdateLocationError("Choose an existing writable folder for plugin updates.")
    target = root / folder.name
    if target.exists():
        manifests = list(target.glob("*.curvemole-plugin.json"))
        if len(manifests) == 1:
            replacement = _replace_source({**record, "reference": str(manifests[0])}, folder, metadata)
            if replacement:
                return replacement
        raise PluginUpdateLocationError(f"The chosen plugin destination cannot be replaced: {target}")
    temporary = Path(tempfile.mkdtemp(prefix=".curvemole-plugin-update-", dir=root))
    try:
        shutil.copytree(folder, temporary / "replacement")
        (temporary / "replacement").rename(target)
    except OSError:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return _SourceReplacement(target, temporary)


def stage_update(manager: PluginManager, update: PluginUpdate, archive: bytes,
                 *, destination: str | Path | None = None) -> None:
    """Replace plugin files in their directory or a user-selected alternative."""
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
    internal = manager.storage.resolve()
    if destination is not None and Path(destination).expanduser().resolve().is_relative_to(internal):
        raise PluginUpdateLocationError("Choose a plugin folder outside CurveMole's internal storage.")
    temporary = Path(tempfile.mkdtemp(prefix="curvemole-plugin-download-"))
    original = copy.deepcopy(record)
    committed = False
    replacement = None
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
        if destination is not None:
            replacement = _relocate_source(record, folder, metadata, destination)
        elif not Path(record["reference"]).resolve().is_relative_to(internal):
            replacement = _replace_source(record, folder, metadata)
        if replacement is None:
            raise PluginUpdateLocationError(
                "The installed plugin folder cannot be replaced. Choose another writable folder "
                "to retain this update.")
        retained_manifest = replacement.target / manifest.name
        metadata = replace(metadata, source=str(retained_manifest))
        candidate = PluginCandidate(metadata, str(retained_manifest), "local")
        manager.installed[update.identifier] = {
            "metadata": asdict(metadata), "reference": str(retained_manifest), "kind": "local",
            "fingerprint": manager._fingerprint(candidate), "enabled": True,
            "symbol": manager.symbol(update.identifier),
            "files": [p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()],
        }
        manager._save()
        committed = True
        replacement.finish()
    finally:
        if not committed:
            manager.installed[update.identifier] = original
            if replacement:
                replacement.rollback()
        shutil.rmtree(temporary, ignore_errors=True)


def plugin_installation_root(manager: PluginManager, destination: str | Path) -> Path:
    """Require an explicit permanent folder outside the host's internal storage."""
    if not str(destination).strip():
        raise CurveMoleError("Choose an existing storage folder for downloaded plugins first.")
    root = Path(destination).expanduser().resolve()
    if not root.is_dir():
        raise CurveMoleError("Choose an existing storage folder for downloaded plugins first.")
    if manager.storage is not None and root.is_relative_to(manager.storage.resolve()):
        raise CurveMoleError("Choose a plugin folder outside CurveMole's internal storage.")
    return root


def install_community_plugin(
    manager: PluginManager, plugin: CommunityPlugin, archive: bytes, destination: str | Path
) -> PluginMetadata:
    """Verify, retain and load one previously uninstalled validated plugin."""
    if plugin.identifier in manager.installed or plugin.identifier in manager.loaded:
        raise CurveMoleError("This plugin is already installed; use Plugin updates instead.")
    if not plugin.compatible:
        raise CurveMoleError("Update CurveMole first: this plugin requires a different plugin API.")
    root = plugin_installation_root(manager, destination)
    category_root = root / plugin.category
    final = category_root / plugin.folder
    resolved = final.resolve()
    if (not resolved.is_relative_to(root) or manager.storage is not None
            and resolved.is_relative_to(manager.storage.resolve())):
        raise CurveMoleError("Plugin destination must stay inside the selected folder "
                             "and outside CurveMole's internal storage.")
    if final.exists():
        raise CurveMoleError(f"Destination already exists: {final}")
    category_root.mkdir(exist_ok=True)
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
