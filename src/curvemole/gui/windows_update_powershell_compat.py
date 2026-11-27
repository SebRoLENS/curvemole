"""Compatibility import: native SHA-256 generation lives in the Windows controller."""
from curvemole.gui.updates_windows import windows_update_script

__all__ = ["windows_update_script"]
