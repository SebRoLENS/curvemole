"""Robust Undo toolbar wiring and background-preview feedback."""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu, QToolBar

from curvemole.gui.main_window import MainWindow


def _replace_action(container: Any, old: QAction, new: QAction) -> None:
    actions = container.actions()
    if old not in actions:
        return
    container.insertAction(old, new)
    container.removeAction(old)


def _install_undo_action(window: MainWindow) -> None:
    old_action = window.undo_action
    stack = window.undo_stack

    action = QAction(old_action.icon(), window.tr("Undo"), window)
    action.setObjectName(old_action.objectName() or "undo_action")
    action.setShortcut(QKeySequence.StandardKey.Undo)
    action.setShortcutContext(old_action.shortcutContext())

    background_commands = {
        window.tr("Subtract background"),
        window.tr("Subtract backgrounds from all spectra"),
    }

    def sync_action(*_args: Any) -> None:
        text = stack.undoText()
        label = window.tr("Undo") + (f" {text}" if text else "")
        action.setText(label)
        action.setToolTip(label)
        action.setEnabled(stack.canUndo())

    def perform_undo(_checked: bool = False) -> None:
        if not stack.canUndo():
            return
        text = stack.undoText()
        stack.undo()

        # A visual-only background preview can make a successful data Undo look
        # unchanged. When the Undo restores a real background subtraction, leave
        # preview mode so the original spectrum is immediately visible again.
        if text in background_commands:
            visual = getattr(window, "background_subtracted_view_action", None)
            if isinstance(visual, QAction) and visual.isChecked():
                visual.setChecked(False)

        if text:
            window.statusBar().showMessage(window.tr("Undone: ") + text, 3000)

    action.triggered.connect(perform_undo)
    stack.canUndoChanged.connect(sync_action)
    stack.undoTextChanged.connect(sync_action)

    for menu in window.menuBar().findChildren(QMenu):
        _replace_action(menu, old_action, action)
    for toolbar in window.findChildren(QToolBar):
        _replace_action(toolbar, old_action, action)

    # Prevent the old QUndoStack-created QAction from retaining Ctrl+Z after it
    # has been removed from the visible UI.
    old_action.setShortcut(QKeySequence())
    old_action.setEnabled(False)
    old_action.setVisible(False)
    window.undo_action = action
    sync_action()


def _install() -> None:
    if getattr(MainWindow, "_curvemole_explicit_undo_action", False):
        return

    original_init = MainWindow.__init__

    def init(window: MainWindow, *args: Any, **kwargs: Any) -> None:
        original_init(window, *args, **kwargs)
        _install_undo_action(window)

    MainWindow.__init__ = init
    MainWindow._curvemole_explicit_undo_action = True


_install()
