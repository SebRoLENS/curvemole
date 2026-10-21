"""Shared ownership rules for secondary application windows."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid


@contextmanager
def transient_widget[Widget](widget: Widget) -> Iterator[Widget]:
    """Release a one-shot dialog/menu after its caller has read its values.

    Qt parents retain closed widgets, including Python references to projects
    and preview data. Defer destruction until the complete handler has finished:
    deleting on close would invalidate accepted dialog fields before extraction.
    Persistent modeless tools and embedded panels must keep their usual owner.
    """
    try:
        yield widget
    finally:
        # Some callers use light Python stand-ins for dialogs in tests/plugins.
        # Already deleted dialogs (WA_DeleteOnClose) need no second disposal.
        if isinstance(widget, QObject) and isValid(widget):
            widget.deleteLater()


def secondary_window_parent(default: QWidget) -> QWidget:
    """Return the active modal window when it must own a new child window."""
    application = QApplication.instance()
    modal = application.activeModalWidget() if application is not None else None
    return modal or default
