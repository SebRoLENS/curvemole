"""Undo fit transactions without copying experimental arrays or breaking edit references."""

from __future__ import annotations

import copy

from PySide6.QtGui import QUndoCommand

from curvemole.core.history import CompactHistory
from curvemole.core.state import copy_result_maps, restore_model


def _capture(window, curve_ids=None):
    models = {}
    for curve_id, model in window.project.models.items():
        if curve_ids is not None and curve_id not in curve_ids:
            continue
        refs = {component.id: (component, dict(component.parameters)) for component in model.components}
        models[curve_id] = (model, copy.deepcopy(model), refs)
    return {
        "models": models,
        "scope": set(window.project.models) if curve_ids is None else set(curve_ids),
        # Completed FitResults are not mutated; share their potentially large arrays.
        "results": copy_result_maps(window.project.results),
        "history": CompactHistory(window.project.fit_history),
        "states": {curve.id: curve.state for curve in window.project.curves},
        "active": window.active_curve_id,
        "selected": window.selected_component_id,
        "last_fit_plan": copy.deepcopy(window.last_fit_plan),
        "resume_plan": copy.deepcopy(getattr(window, "_sequential_resume_plan", None)),
        "paused": getattr(window, "_paused_result", None),
        "sequence_pause": getattr(window, "_sequential_pause_result", None),
        "pause_source_ids": getattr(window, "_sequential_pause_source_ids", ()),
    }


def _restore(window, state):
    for curve_id in state["scope"] - state["models"].keys():
        window.project.models.pop(curve_id, None)
    for curve_id, (model, saved, refs) in state["models"].items():
        restore_model(model, saved, refs)
        window.project.models[curve_id] = model
    window.project.results = copy_result_maps(state["results"])
    window.project.fit_history = state["history"].copy()
    for curve in window.project.curves:
        if curve.id in state["states"]:
            curve.state = state["states"][curve.id]
    window.active_curve_id = state["active"]
    window.selected_component_id = state["selected"]
    window.last_fit_plan = copy.deepcopy(state["last_fit_plan"])
    window._sequential_resume_plan = copy.deepcopy(state["resume_plan"])
    window._paused_result = state["paused"]
    window._sequential_pause_result = state["sequence_pause"]
    window._sequential_pause_source_ids = state["pause_source_ids"]
    window.resume_action.setEnabled(bool(state["paused"] or state["sequence_pause"]))
    window.project.touch()
    window.refresh_all()


class FitUndoCommand(QUndoCommand):
    def __init__(self, window, before, after):
        super().__init__(window.tr("Fit"))
        self.window, self.before, self.after = window, before, after
        self.initial = True

    def redo(self):
        if self.initial:
            self.initial = False
        else:
            _restore(self.window, self.after)

    def undo(self):
        _restore(self.window, self.before)


class FitLifecycleController:
    """Explicit transaction hooks called around the complete GUI fit lifecycle.

    Completion runs after sequential/resume handlers, so Undo includes their
    final state without relying on importing this module after those wrappers.
    """
    def __init__(self, window):
        self.window = window

    def begin(self, plan):
        window = self.window
        window._fit_undo_before = _capture(window, set(plan.curve_ids))
        window.undo_action.setEnabled(False)
        window.redo_action.setEnabled(False)

    def complete(self, result):
        window = self.window
        before = getattr(window, "_fit_undo_before", None)
        window._fit_undo_before = None
        if before is not None:
            if result.success or result.curve_outputs or result.paused_curve_id:
                window.undo_stack.push(FitUndoCommand(window, before, _capture(window, before["scope"])))
            else:
                _restore(window, before)

    def abort(self):
        window = self.window
        before = getattr(window, "_fit_undo_before", None)
        window._fit_undo_before = None
        if before is not None:
            _restore(window, before)

    def done(self):
        window = self.window
        window.undo_action.setEnabled(window.undo_stack.canUndo())
        window.redo_action.setEnabled(window.undo_stack.canRedo())
