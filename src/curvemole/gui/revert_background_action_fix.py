"""Ensure the Revert background toolbar/menu action ignores QAction's checked flag."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from PySide6.QtGui import QAction

from curvemole.gui.main_window import MainWindow


def _install_revert_background_action_fix(window: MainWindow) -> None:
    action = getattr(window, "revert_background_action", None)
    if not isinstance(action, QAction):
        return

    # QAction.triggered emits a boolean `checked` argument. The existing
    # revert_backgrounds method has an optional `curve_ids` argument, so a direct
    # signal connection accidentally passes False as curve_ids. That skips the
    # chooser and returns immediately. Replace the connection with one that
    # explicitly discards the QAction payload.
    with suppress(RuntimeError, TypeError):
        action.triggered.disconnect()
    action.triggered.connect(lambda _checked=False: window.revert_backgrounds())


def _install() -> None:
    if getattr(MainWindow, "_curvemole_revert_background_action_fix", False):
        return

    original_init = MainWindow.__init__

    def init(window: MainWindow, *args: Any, **kwargs: Any) -> None:
        original_init(window, *args, **kwargs)
        _install_revert_background_action_fix(window)

    MainWindow.__init__ = init
    MainWindow._curvemole_revert_background_action_fix = True


_install()
