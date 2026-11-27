"""Undo commands shared by the main window and its controllers."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QUndoCommand


class CallbackCommand(QUndoCommand):
    def __init__(
        self,
        text: str,
        redo: Callable[[], None],
        undo: Callable[[], None],
    ) -> None:
        super().__init__(text)
        self._redo = redo
        self._undo = undo

    def redo(self) -> None:
        self._redo()

    def undo(self) -> None:
        self._undo()
