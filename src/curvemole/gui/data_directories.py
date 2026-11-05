"""Shared desktop defaults for reusable user data, independent of app state."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths

DATA_FOLDER = "curvemole_data"
LIBRARY_FOLDERS = {
    "functions": "my_curvemole_functions",
    "equations": "my_curvemole_formulas",
    "plugins": "curvemole_plugins",
}
_SETTINGS = {
    "functions": ("custom_function_directory",),
    "equations": ("custom_equation_directory",),
    "plugins": ("plugin_directory", "community_plugins/folder"),
}


def data_directory(settings) -> Path:
    configured = str(settings.value("data_directory", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return (Path(documents) if documents else Path.home()) / DATA_FOLDER


def default_library_directory(settings, kind: str) -> Path:
    return data_directory(settings) / LIBRARY_FOLDERS[kind]


def library_directory(settings, kind: str, *, community: bool = False) -> Path:
    keys = _SETTINGS[kind]
    if community and kind == "plugins":
        keys = tuple(reversed(keys))
    for key in keys:
        configured = str(settings.value(key, "") or "").strip()
        if configured:
            return Path(configured).expanduser()
    return default_library_directory(settings, kind)


def prepare_library_directory(settings, kind: str, selected: Path | None = None) -> Path:
    """Create the default hierarchy on first write; honour custom destinations.

    Merely inspecting/loading a library never creates folders. Existing external
    libraries and plugin trust/session state are not moved or rewritten.
    """
    directory = selected if selected is not None else library_directory(settings, kind)
    if directory.resolve() == default_library_directory(settings, kind).resolve():
        for folder in LIBRARY_FOLDERS.values():
            (data_directory(settings) / folder).mkdir(parents=True, exist_ok=True)
    else:
        directory.mkdir(parents=True, exist_ok=True)
    return directory
