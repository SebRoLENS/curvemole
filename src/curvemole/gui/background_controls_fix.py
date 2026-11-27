"""Compatibility alias: background subtraction lives in ``gui.background_controller``.

This module used to replace MainWindow methods at import time; it no longer
patches anything.
"""
from curvemole.gui.background_controller import (  # noqa: F401
    RevertBackgroundDialog,
    _eligible_revert_curves,
    _revert_backgrounds,
    _subtract_all_backgrounds,
    _subtract_current_background,
)
from curvemole.gui.dialogs import BackgroundComponentsDialog  # noqa: F401
