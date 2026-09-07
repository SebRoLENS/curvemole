"""Undo fit transactions without copying experimental arrays or breaking edit references."""

from __future__ import annotations

import copy
from dataclasses import fields

from PySide6.QtGui import QUndoCommand

from curvemole.gui.main_window import MainWindow


def _capture(window):
    models = {}
    for curve_id, model in window.project.models.items():
        refs = {component.id: (component, dict(component.parameters)) for component in model.components}
        models[curve_id] = (model, copy.deepcopy(model), refs)
    return {
        "models": models,
        # Completed FitResults are not mutated; share their potentially large arrays.
        "results": dict(window.project.results),
        "history": list(window.project.fit_history),
        "states": {curve.id: curve.state for curve in window.project.curves},
        "active": window.active_curve_id,
        "selected": window.selected_component_id,
        "last_fit_plan": copy.deepcopy(window.last_fit_plan),
        "resume_plan": copy.deepcopy(getattr(window, "_sequential_resume_plan", None)),
        "paused": getattr(window, "_paused_result", None),
        "sequence_pause": getattr(window, "_sequential_pause_result", None),
    }


def _restore(window, state):
    window.project.models.clear()
    for curve_id, (model, saved, refs) in state["models"].items():
        model.name, model.id = saved.name, saved.id
        components = []
        for snapshot in saved.components:
            component, parameters = refs[snapshot.id]
            for field in fields(snapshot):
                if field.name != "parameters":
                    setattr(component, field.name, copy.deepcopy(getattr(snapshot, field.name)))
            component.parameters = dict(parameters)
            for name, parameter in snapshot.parameters.items():
                for field in fields(parameter):
                    setattr(component.parameters[name], field.name, copy.deepcopy(getattr(parameter, field.name)))
            components.append(component)
        model.components = components
        window.project.models[curve_id] = model
    window.project.results = dict(state["results"])
    window.project.fit_history = list(state["history"])
    for curve in window.project.curves:
        if curve.id in state["states"]:
            curve.state = state["states"][curve.id]
    window.active_curve_id = state["active"]
    window.selected_component_id = state["selected"]
    window.last_fit_plan = copy.deepcopy(state["last_fit_plan"])
    window._sequential_resume_plan = copy.deepcopy(state["resume_plan"])
    window._paused_result = state["paused"]
    window._sequential_pause_result = state["sequence_pause"]
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


def _install():
    if getattr(MainWindow, "_fit_undo_installed", False):
        return
    original_run = MainWindow._run_fit
    original_finished = MainWindow._fit_finished
    original_failed = MainWindow._task_failed
    original_done = MainWindow._task_done

    def run(window, plan):
        if window._thread is not None:
            return original_run(window, plan)
        window._fit_undo_before = _capture(window)
        window.undo_action.setEnabled(False)
        window.redo_action.setEnabled(False)
        try:
            return original_run(window, plan)
        except Exception:
            _restore(window, window._fit_undo_before)
            window._fit_undo_before = None
            window.undo_action.setEnabled(window.undo_stack.canUndo())
            window.redo_action.setEnabled(window.undo_stack.canRedo())
            raise

    def finished(window, result):
        before = getattr(window, "_fit_undo_before", None)
        original_finished(window, result)
        window._fit_undo_before = None
        if before is not None:
            if result.success or result.curve_outputs or result.paused_curve_id:
                window.undo_stack.push(FitUndoCommand(window, before, _capture(window)))
            else:
                _restore(window, before)

    def failed(window, message, details):
        before = getattr(window, "_fit_undo_before", None)
        window._fit_undo_before = None
        if before is not None:
            _restore(window, before)
        original_failed(window, message, details)

    def done(window, *args):
        original_done(window, *args)
        window.undo_action.setEnabled(window.undo_stack.canUndo())
        window.redo_action.setEnabled(window.undo_stack.canRedo())

    MainWindow._run_fit = run
    MainWindow._fit_finished = finished
    MainWindow._task_failed = failed
    MainWindow._task_done = done
    MainWindow._fit_undo_installed = True


_install()
