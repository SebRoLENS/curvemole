"""Compatibility alias: the Windows updater now lives in ``curvemole.gui.updates_windows``."""
from curvemole.gui.updates_windows import *  # noqa: F401,F403
from curvemole.gui.updates_windows import (  # noqa: F401
    _cleanup_stale_update_files,
    _download_windows_update,
    _install_windows_download,
    _windows_temp_download_path,
    windows_update_script,
)
