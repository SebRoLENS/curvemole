"""Where CurveMole keeps its per-user files (no Qt dependency).

All per-user directories are resolved here, at call time, through
platformdirs, so tests and portable setups can redirect them in one place.
"""

from __future__ import annotations

from pathlib import Path

import platformdirs

APPLICATION = "CurveMole"


def config_dir() -> Path:
    """Per-user configuration (plugins and their settings)."""
    return Path(platformdirs.user_config_path(APPLICATION))


def cache_dir() -> Path:
    """Per-user cache (crash-recovery sessions, single-instance sockets)."""
    return Path(platformdirs.user_cache_path(APPLICATION))


def data_dir() -> Path:
    """Base per-user data directory (desktop integration files)."""
    return Path(platformdirs.user_data_path("", appauthor=False))


def plugin_storage() -> Path:
    return config_dir() / "plugins"


def recovery_dir() -> Path:
    return cache_dir() / "recovery"
