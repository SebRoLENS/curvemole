"""Compatibility shim for legacy BackgroundComponentsDialog injection points."""

from __future__ import annotations

from typing import Any

from curvemole.gui import background_controls_fix as _fix
from curvemole.gui import main_window as _main_window
from curvemole.gui.main_window import MainWindow


class _UncheckedApplyAll:
    def isChecked(self) -> bool:
        return False


def _subtract_background_compat(window: MainWindow) -> None:
    """Resolve the dialog through main_window so existing tests/plugins keep working."""
    dialog_type = _main_window.BackgroundComponentsDialog
    original_dialog_type = _fix.BackgroundComponentsDialog

    class CompatibleDialog(dialog_type):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            if not hasattr(self, "apply_to_all_spectra"):
                self.apply_to_all_spectra = _UncheckedApplyAll()

    _fix.BackgroundComponentsDialog = CompatibleDialog
    try:
        _fix._subtract_current_background(window)
    finally:
        _fix.BackgroundComponentsDialog = original_dialog_type


MainWindow.subtract_background = _subtract_background_compat
