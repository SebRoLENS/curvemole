"""Reopen saved function control points as a cancellable, undoable editing session."""
from __future__ import annotations

import copy
from dataclasses import replace

import numpy as np
from PySide6.QtCore import QObject

from curvemole.core.background_edit import updated_background_history
from curvemole.core.display import display_curve
from curvemole.core.errors import DataValidationError
from curvemole.core.models import Component, Model
from curvemole.core.parameters import Parameter, resolve_parameter_values
from curvemole.gui.manual_points import initialise_component_from_points, minimum_manual_points
from curvemole.gui.manual_points_live import (
    _generic_fit_component,
    _normalise_points,
    _set_stored_points,
    _stored_points,
    preview_component_from_points,
)


def can_edit_points(component, registry):
    try:
        definition = registry.get(component.function_id)
    except DataValidationError:
        return False
    if _stored_points(component):
        return True
    # Older graphical peaks did not retain explicit control points. Reconstruct
    # their current shape; keep their normal centre/width handles unchanged.
    return definition.kind == "peak" and "center" in component.parameters


def editable_points(component, registry):
    points = _stored_points(component)
    definition = registry.get(component.function_id)
    if points:
        if definition.kind != "peak" or "center" not in component.parameters:
            return points
        # A centre/width drag or a fit may have changed the peak since placement.
        # Reuse saved points only while they still describe its current shape.
        x, y = np.asarray(points).T
        current = definition.evaluate(x, {name: p.value for name, p in component.parameters.items()}, component.metadata)
        if np.allclose(current, y, rtol=1e-5, atol=max(float(np.max(np.abs(y))), 1.)*1e-8):
            return points
    values = {name: p.value for name, p in component.parameters.items()}
    center = values["center"]
    derived = definition.derived_values(values, component.metadata)
    width = derived.get("FWHM") or values.get("fwhm") or values.get("sigma", values.get("gamma", 1.0))*2.354820045
    width = max(abs(float(width)), abs(center)*1e-12, 1e-12)
    x = np.linspace(center-width, center+width, max(5, len(values)))
    y = definition.evaluate(x, values, component.metadata)
    if not np.all(np.isfinite(y)):
        raise ValueError("The current function cannot provide finite control points.")
    return list(zip(map(float, x), map(float, y), strict=True))


class FunctionPointEditor(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.active = False
        self.committing = False
        window.plot_workspace.placementCancelled.connect(self.cancel)

    def start(self, component_id):
        window, workspace = self.window, self.window.plot_workspace
        if window.project.read_only or window._thread is not None:
            window._notify(self.tr("Point editing requires an editable project and no running fit."), warning=True)
            return
        if not window.active_curve_id or not component_id:
            return
        workspace.cancel_placement()
        # No fit is running: a retained worker preview must not override edits.
        workspace._live_parameter_values = None
        from curvemole.gui.model_multiselect import _find_component_curve
        curve_id = _find_component_curve(window, component_id)
        if curve_id is None:
            return
        if curve_id != window.active_curve_id:
            window._set_active_curve(curve_id)
        project = window.project
        component = project.model_for(curve_id).component(component_id)
        if not can_edit_points(component, window.registry):
            return
        points = editable_points(component, window.registry)
        window.model_panel.select_component_ref(curve_id, component.id)
        window._set_component(component.id)
        self.project, self.curve_id = project, curve_id
        controller = window.view_options_controller
        self.view_options = dict(controller.options)
        self.legacy_view = bool(getattr(workspace, "_background_subtracted_view", False))
        self.viewport = (copy.deepcopy(workspace.view_box.viewRange()),
                         copy.deepcopy(workspace.residual_plot.getViewBox().viewRange()))
        self.initial_points = _normalise_points(points)
        self.original = copy.deepcopy(component.to_dict())
        self.draft = Component.from_dict(copy.deepcopy(self.original))
        self.active = True
        try:
            if component.is_background:
                current = controller.for_curve(self.curve_id)
                restored = replace(current, background="restore")
                display_curve(self.project.dataset.curve(self.curve_id), restored)
                controller.options[self.curve_id] = restored
                workspace.refresh()
            self._begin(points)
            if component.is_background:
                workspace.view_active()
        except Exception:
            self.cancel()
            raise

    def _begin(self, points):
        window, workspace = self.window, self.window.plot_workspace
        window._pending_component = self.draft
        window._pending_component_curve_id = self.curve_id
        window._pending_manual_points = True
        workspace.begin_manual_point_placement(
            self.tr("Edit points") + " — " + self.draft.name, self.draft.function_id,
            minimum_manual_points(self.draft, registry=window.registry),
        )
        workspace._spline_points = list(points)
        workspace.placement_editor.mode.setCurrentIndex(workspace.placement_editor.mode.findData("move"))
        workspace._render_placement_preview()
        workspace._update_spline_instruction()
        item = workspace._component_items.get((self.curve_id, self.draft.id))
        if item is not None:
            item.hide()
        label = workspace._component_labels_by_key.get((self.curve_id, self.draft.id))
        if label is not None:
            label.hide()
        for handle in workspace._handles:
            handle.hide()

    def preview(self, points):
        selected = _normalise_points(points)
        original = Component.from_dict(copy.deepcopy(self.original))
        if selected == self.initial_points:
            return original
        definition = self.window.registry.get(original.function_id)
        if definition.kind == "peak" and not definition.has_point_configuration and definition.point_initializer is None:
            # Fit from the current peak, avoiding a second centre/width guess.
            return _generic_fit_component(original, selected, registry=self.window.registry,
                                          free_only=False, reseed=False, strict=True)
        return preview_component_from_points(original, selected, registry=self.window.registry)

    def finish(self, points):
        window = self.window
        selected = _normalise_points(points)
        try:
            if window.project is not self.project or window.active_curve_id != self.curve_id:
                raise ValueError("The spectrum changed while editing points.")
            model = self.project.model_for(self.curve_id)
            if model.component(self.draft.id).to_dict() != self.original:
                raise ValueError("The function changed while editing points. Cancel and reopen Edit points.")
            if selected == self.initial_points:
                self._close()
                return
            required = minimum_manual_points(self.draft, registry=window.registry)
            if len(selected) < required:
                raise ValueError(f"This function needs at least {required} manual points.")
            definition = window.registry.get(self.draft.function_id)
            if definition.kind == "peak" and not definition.has_point_configuration and definition.point_initializer is None:
                candidate = self.preview(selected)
            else:
                candidate = Component.from_dict(copy.deepcopy(self.original))
                initialise_component_from_points(candidate, selected, registry=window.registry)
            _set_stored_points(candidate, selected)
            # Preserve existing parameter constraints for names that still exist.
            for name, parameter in list(candidate.parameters.items()):
                if name in self.original["parameters"]:
                    original = Parameter.from_dict(copy.deepcopy(self.original["parameters"][name]))
                    original.value = parameter.value
                    original.standard_error = original.ci_low = original.ci_high = None
                    original.validate()
                    candidate.parameters[name] = original
            context = self.project.parameter_map()
            prefix = f"{self.curve_id}.{candidate.id}."
            context = {key: p for key, p in context.items() if not key.startswith(prefix)}
            context.update({prefix+name: p for name, p in candidate.parameters.items()})
            values = resolve_parameter_values(context)
            before = model.to_dict()
            after = Model.from_dict(copy.deepcopy(before))
            index = next(i for i, c in enumerate(after.components) if c.id == candidate.id)
            after.components[index] = candidate
            curve = self.project.dataset.curve(self.curve_id)
            history = updated_background_history(curve, after, candidate,
                values=values, registry=window.registry)
            before_history = copy.deepcopy(curve.transformations)
            before_redo = copy.deepcopy(curve.redo_transformations)
            before_state = curve.state
            after_dict = after.to_dict()

            # Undo callbacks must outlive this editor session, whose fields are
            # cleared on close. Capture the project and curve identity by value.
            project, curve_id = self.project, self.curve_id
            def restore(model_state, transformations, redo, state):
                project.models[curve_id] = Model.from_dict(copy.deepcopy(model_state))
                target = project.dataset.curve(curve_id)
                target.transformations = copy.deepcopy(transformations)
                target.redo_transformations = copy.deepcopy(redo)
                target._recompute()
                target.state = state

            self.committing = True
            try:
                if history is None:
                    window._push_model_state(self.curve_id, before, after_dict, self.tr("Edit function points"))
                else:
                    window._push_change(self.tr("Edit function points and update background"),
                        lambda: restore(after_dict, history, [], before_state),
                        lambda: restore(before, before_history, before_redo, before_state),
                        modified_curve_ids={curve_id})
            finally:
                self.committing = False
        except Exception as exc:
            window._notify(str(exc), warning=True)
            self._begin(selected)
            return
        self._close()

    def cancel(self):
        if self.active:
            self._close()

    def _close(self):
        self.active = False
        window, workspace = self.window, self.window.plot_workspace
        workspace._live_parameter_values = None
        window._pending_component = None
        window._pending_component_curve_id = None
        window._pending_manual_points = False
        if window.project is self.project:
            controller = window.view_options_controller
            controller.options = dict(self.view_options)
            workspace._background_subtracted_view = self.legacy_view
            window.background_subtracted_view_action.blockSignals(True)
            window.background_subtracted_view_action.setChecked(
                self.legacy_view or any(o.background == "subtract" and not o.original for o in self.view_options.values()))
            window.background_subtracted_view_action.blockSignals(False)
            workspace.refresh()
            main, residual = self.viewport
            workspace.view_box.setRange(xRange=main[0], yRange=main[1], padding=0)
            workspace.residual_plot.getViewBox().setRange(yRange=residual[1], padding=0)
        # Do not retain a replaced project's arrays in this reusable controller.
        self.project = self.draft = self.original = None
        self.view_options = {}
