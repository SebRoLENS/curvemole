"""Public plugin API version and compatibility rule.

Plugins declare the API version they were written for in their manifest
(``api_compatibility``), as ``"MAJOR"`` or ``"MAJOR.MINOR"``. CurveMole loads a
plugin when the major versions match and the plugin does not require a newer
minor version than CurveMole provides. A new major version marks a breaking
change; a new minor version only adds capabilities.

The registration objects plugins receive (``PluginAPI``, extension kinds) are
re-exported here so that plugins can import them from one stable place.
"""

from __future__ import annotations

from curvemole.core.extensions import KINDS, Contribution, ExtensionRegistry, PluginAPI
from curvemole.version import PLUGIN_API_VERSION

__all__ = [
    "KINDS",
    "PLUGIN_API_VERSION",
    "Contribution",
    "ExtensionRegistry",
    "PluginAPI",
    "is_compatible",
    "parse_api_version",
]


def parse_api_version(value: object) -> tuple[int, int]:
    """``"1"`` → (1, 0); ``"1.2"`` → (1, 2). Raises ValueError for anything else."""
    text = str(value).strip()
    parts = text.split(".")
    if not 1 <= len(parts) <= 2 or not all(part.isdigit() for part in parts):
        raise ValueError(f"Invalid plugin API version {value!r}; expected MAJOR or MAJOR.MINOR.")
    major, minor = int(parts[0]), int(parts[1]) if len(parts) == 2 else 0
    return major, minor


def is_compatible(required: object, provided: object = PLUGIN_API_VERSION) -> bool:
    """Same major version and a required minor version not newer than the provided one."""
    try:
        need_major, need_minor = parse_api_version(required)
        have_major, have_minor = parse_api_version(provided)
    except ValueError:
        return False
    return need_major == have_major and need_minor <= have_minor
