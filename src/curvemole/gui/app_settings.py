"""The application's persistent settings: one name, one set of keys.

All Qt settings live under ORGANIZATION/APPLICATION. Use :func:`settings_for`
from widgets: it returns the owning main window's ``settings`` when there is
one (so a window-specific or test-injected QSettings applies everywhere) and a
fresh QSettings otherwise. Keys are listed in :class:`SettingKey`.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSettings

ORGANIZATION = "CurveMole"
APPLICATION = "CurveMole"


class SettingKey:
    THEME = "theme"
    GEOMETRY = "geometry"
    WINDOW_STATE = "window_state"
    LAYOUT_SCHEMA_VERSION = "layout/schema_version"
    LAYOUT_COLLAPSED_DOCKS = "layout/collapsed_docks"
    RECENT_PROJECTS = "recent_projects"
    DATA_DIRECTORY = "data_directory"
    PLUGIN_DIRECTORY = "plugin_directory"
    COMMUNITY_PLUGINS_FOLDER = "community_plugins/folder"
    LAST_PEAK_FUNCTION = "last_peak_function"
    LAST_QUICK_FUNCTION = "last_quick_function"
    MODEL_REORDER_RULES = "model/reorder_rules"
    SPECTRUM_EXPORT_DIRECTORY = "spectrum_export_directory"
    FOLDER_IMPORT_PATH = "folder_import/path"
    AUTOMATION_FILE = "automation/file"
    RECOVERY_WARNING_BAND = "recovery/warning_band"
    SHORTCUTS_COMMANDS = "shortcuts/commands"
    SHORTCUTS_SCHEMA = "shortcuts/schema"
    UPDATES_CHANNEL = "updates/channel"
    UPDATES_LAST_CHECK = "updates/last_check"
    WINDOWS_INSTALLER_DECLINED = "desktop/windows_installer_declined"
    SEQUENTIAL_MONITOR_RESIDUALS = "sequential/monitor_residuals"
    SEQUENTIAL_RESIDUAL_RATIO = "sequential/residual_ratio"
    SEQUENTIAL_RESIDUAL_DELTA_PERCENT = "sequential/residual_delta_percent"
    SEQUENTIAL_MONITOR_PARAMETERS = "sequential/monitor_parameters"
    SEQUENTIAL_PARAMETER_CHANGE_PERCENT = "sequential/parameter_change_percent"
    SEQUENTIAL_PROPAGATE_PREFIX = "sequential/propagate_"


def open_settings() -> QSettings:
    return QSettings(ORGANIZATION, APPLICATION)


def settings_for(widget: Any = None, *, factory: Any = None) -> QSettings:
    """The settings of ``widget``'s main window, or the application settings.

    ``factory`` builds the fallback (a module's own ``QSettings`` name, kept as
    an injection point for tests).
    """
    current = widget
    while current is not None:
        settings = getattr(current, "settings", None)
        if isinstance(settings, QSettings):
            return settings
        parent = getattr(current, "parentWidget", None)
        current = parent() if callable(parent) else None
    if factory is not None:
        return factory(ORGANIZATION, APPLICATION)
    return open_settings()
