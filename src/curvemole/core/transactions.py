"""Reversible project changes used by Undo/Redo.

All model restores go through :func:`restore_model_state`, which updates the
project's live Model in place (``core.state.restore_model``) instead of
replacing it with a fresh object. Components and parameters that survive the
change keep their identity, so panels, plot handles and pending edits that hold
references stay valid after Undo or Redo, exactly as for fit Undo.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from curvemole.core.models import Model
from curvemole.core.state import restore_model


def model_state(model: Model) -> dict[str, Any]:
    """A detached snapshot of ``model``."""
    return copy.deepcopy(model.to_dict())


def restore_model_state(project: Any, curve_id: str, state: Mapping[str, Any]) -> Model:
    """Make ``project.models[curve_id]`` equal ``state``, reusing live objects."""
    saved = Model.from_dict(copy.deepcopy(dict(state)))
    current = project.models.get(curve_id)
    if current is None:
        project.models[curve_id] = saved
        return saved
    restore_model(current, saved)
    return current


@dataclass(slots=True)
class ModelEdit:
    """Before/after snapshots of one or more spectra's models."""

    before: dict[str, dict[str, Any]] = field(default_factory=dict)
    after: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def single(cls, curve_id: str, before: Mapping[str, Any], after: Mapping[str, Any]) -> ModelEdit:
        return cls({curve_id: copy.deepcopy(dict(before))}, {curve_id: copy.deepcopy(dict(after))})

    @property
    def curve_ids(self) -> set[str]:
        return set(self.before) | set(self.after)

    def apply(self, project: Any) -> None:
        for curve_id, state in self.after.items():
            restore_model_state(project, curve_id, state)

    def revert(self, project: Any) -> None:
        for curve_id, state in self.before.items():
            restore_model_state(project, curve_id, state)


@dataclass(slots=True)
class ProjectChange:
    """A change described by its own apply/revert callables."""

    apply_change: Callable[[], None]
    revert_change: Callable[[], None]

    def apply(self, project: Any = None) -> None:
        self.apply_change()

    def revert(self, project: Any = None) -> None:
        self.revert_change()
