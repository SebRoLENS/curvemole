"""Single entry point for undoable changes and the project's saved/modified state.

Every undoable change is pushed through :class:`UndoService`:

* :meth:`push` - a change given by redo/undo callables, applied immediately;
* :meth:`push_model_edit` - model snapshots (``core.transactions.ModelEdit``),
  restored in place so live components keep their identity;
* :meth:`push_applied` - a ready-made command whose change is already applied
  (for example a completed fit).

The service also ties the project's *modified* flag to the undo stack: after
saving, the stack is marked clean, and undoing back to that point makes the
project unmodified again - unless something changed outside Undo in between
(``project.touch()`` calls that are not part of an undoable command), in which
case the project conservatively stays modified.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import contextmanager
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtGui import QUndoCommand

from curvemole.core.transactions import ModelEdit
from curvemole.gui.undo_commands import CallbackCommand


class UndoService(QObject):
    def __init__(self, window: Any, stack: Any) -> None:
        super().__init__(window)
        self.window = window
        self.stack = stack
        self._accounted_revision = window.project.revision
        self._outside_changes = False
        stack.cleanChanged.connect(self._clean_changed)

    # -- recording -------------------------------------------------------
    def _account_outside(self) -> None:
        if self.window.project.revision != self._accounted_revision:
            self._outside_changes = True
            self._accounted_revision = self.window.project.revision

    @contextmanager
    def executing(self):
        """Attribute project revisions made inside the block to the undo stack."""
        self._account_outside()
        try:
            yield
        finally:
            self._accounted_revision = self.window.project.revision

    def guarded(self, operation: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            with self.executing():
                operation()
        return run

    # -- pushing ---------------------------------------------------------
    def push(
        self,
        text: str,
        redo: Callable[[], None],
        undo: Callable[[], None],
        *,
        modified_curve_ids: Iterable[str] | None = None,
        preserve_curve_ids: Iterable[str] | None = None,
        refresh: bool = True,
        check_editable: bool = True,
    ) -> bool:
        """Apply ``redo`` now and record it; return False if editing is not allowed.

        ``refresh=False`` is for callables that refresh the window themselves;
        ``check_editable=False`` for display-only changes (colours, ordering) that
        stay available while a task runs.
        """
        window = self.window
        if check_editable and not window._ensure_editable():
            return False
        modified = None if modified_curve_ids is None else set(modified_curve_ids)
        preserved = None if preserve_curve_ids is None else set(preserve_curve_ids)

        def wrapped(operation: Callable[[], None]) -> None:
            operation()
            if refresh:
                window._after_edit(modified, preserved)

        self.stack.push(CallbackCommand(text, self.guarded(lambda: wrapped(redo)),
                                        self.guarded(lambda: wrapped(undo))))
        return True

    def push_model_edit(self, edit: ModelEdit, text: str) -> bool:
        project_of = lambda: self.window.project  # noqa: E731 - the project may be replaced later
        return self.push(text, lambda: edit.apply(project_of()), lambda: edit.revert(project_of()),
                         modified_curve_ids=edit.curve_ids)

    def push_applied(self, command: QUndoCommand) -> None:
        """Record a command whose change was already applied (its first redo is a no-op)."""
        self._account_outside()
        self.stack.push(command)
        self._accounted_revision = self.window.project.revision

    # -- saved state -----------------------------------------------------
    def mark_saved(self) -> None:
        """The project on disk now equals the current state."""
        self._outside_changes = False
        self._accounted_revision = self.window.project.revision
        self.stack.setClean()

    def reset(self) -> None:
        """Forget the history, e.g. for a new or newly opened project."""
        self.stack.clear()
        self.mark_saved()

    def project_replaced(self, _project: Any = None) -> None:
        # Plugin snapshots and fit Undo may swap the Project object; their
        # revisions are unrelated, so start accounting afresh.
        self._accounted_revision = self.window.project.revision

    def _clean_changed(self, clean: bool) -> None:
        self._account_outside()
        project = self.window.project
        if clean and not self._outside_changes and project.dirty:
            project.dirty = False
            self.window.setWindowTitle(self.window._title())
