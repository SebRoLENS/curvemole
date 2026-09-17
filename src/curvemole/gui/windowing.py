"""Shared ownership rules for secondary application windows."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget


def secondary_window_parent(default: QWidget) -> QWidget:
    """Return the active modal window when it must own a new child window."""
    application = QApplication.instance()
    modal = application.activeModalWidget() if application is not None else None
    return modal or default
