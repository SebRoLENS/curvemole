"""GUI-thread services for nonmodal plugin panels, without exposing the window."""
from __future__ import annotations

import copy
import json

import numpy as np

from curvemole.core.extensions import extensions


class PluginServices:
    def __init__(self, host, owner):
        self._host = host
        self.owner = owner

    def _window(self):
        window = self._host.window
        if self.owner in window.plugin_manager.errors or not any(
            e.owner == self.owner for e in extensions.entries.values()
        ):
            raise ValueError("Plugin is disabled or unloaded.")
        return window

    def snapshot(self):
        self._window()
        return self._host.context(self.owner, with_services=True)

    def settings(self):
        """Copy only this plugin's settings, without capturing project data."""
        window = self._window()
        return copy.deepcopy(window.project.ui_state.get("plugin_data", {}).get(self.owner, {}))

    def active_spectrum_state(self):
        """Detached identifiers/hash for polling; never copy the full project."""
        window = self._window()
        curve = next(
            (curve for series in window.project.dataset.series for curve in series.curves
             if curve.id == window.active_curve_id), None
        )
        return (window.project.id, curve.id if curve else None,
                curve.content_hash if curve else None, curve.name if curve else None)

    def spectrum_snapshot(self, *, include_selected=False, include_models=False, include_settings=False):
        """Detached requested spectra, optionally models/settings; no fit history.

        All models are included together when requested, so links to parameters
        in other spectra still resolve. Fit results and resampling stay omitted.
        """
        from curvemole.core.data import Dataset, Series
        from curvemole.core.project import Project
        from curvemole.gui.plugin_host import PluginContext

        window = self._window()
        selected = tuple(window.curve_tree.selected_curve_ids()) if include_selected else ()
        ids = set(selected)
        ids.add(window.active_curve_id)
        groups = []
        for series in window.project.dataset.series:
            curves = [curve for curve in series.curves if curve.id in ids]
            if curves:
                groups.append(Series(series.name, copy.deepcopy(curves), id=series.id))
        project = Project(
            name=window.project.name, id=window.project.id, dataset=Dataset(groups),
            path=window.project.path, read_only=window.project.read_only,
        )
        if include_models:
            project.models = copy.deepcopy(window.project.models)
        if include_settings:
            project.ui_state["plugin_data"] = {self.owner: self.settings()}
        return PluginContext(project, window.active_curve_id, selected, self.owner, services=self)

    def active_model_snapshot(self):
        """Active spectrum, linked models and owner settings; omit fit outputs."""
        return self.spectrum_snapshot(include_models=True, include_settings=True)

    def save_settings(self, data, *, metadata_key=None, curve_metadata=None):
        """Undoable settings/metadata only; preserve fit state and selection."""
        window = self._window()
        if window._thread is not None or window.project.read_only:
            raise ValueError("Wait for the fit to finish, or use an editable project.")
        data, updates = copy.deepcopy(data), copy.deepcopy(curve_metadata or {})
        json.dumps([data, updates], allow_nan=False)
        if updates and not metadata_key:
            raise ValueError("A metadata key is required.")
        curves = {curve.id: curve for curve in window.project.curves}
        if not set(updates) <= curves.keys():
            raise ValueError("The selected spectra are no longer available.")
        missing = object()
        current = window.project.ui_state.get("plugin_data", {})
        previous = copy.deepcopy(current[self.owner]) if self.owner in current else missing
        if not updates and current.get(self.owner, {}) == data:
            return
        before = {
            key: copy.deepcopy(curves[key].metadata[metadata_key])
            if metadata_key in curves[key].metadata else missing
            for key in updates
        }

        def redo():
            window.project.ui_state.setdefault("plugin_data", {})[self.owner] = copy.deepcopy(data)
            for key, value in updates.items():
                window.project.dataset.curve(key).metadata[metadata_key] = copy.deepcopy(value)

        def undo():
            plugin_data = window.project.ui_state.setdefault("plugin_data", {})
            if previous is missing:
                plugin_data.pop(self.owner, None)
            else:
                plugin_data[self.owner] = copy.deepcopy(previous)
            for key, value in before.items():
                metadata = window.project.dataset.curve(key).metadata
                if value is missing:
                    metadata.pop(metadata_key, None)
                else:
                    metadata[metadata_key] = copy.deepcopy(value)

        window._push_change("Plugin settings", redo, undo, modified_curve_ids=set())

    def apply_y_replacement(
        self,
        curve_id,
        values,
        *,
        description="Replace spectrum values",
        metadata_key=None,
        metadata=None,
    ):
        """Apply an undoable full-length Y replacement to one spectrum."""
        window = self._window()
        if window._thread is not None or window.project.read_only:
            raise ValueError("Wait for the fit to finish, or use an editable project.")
        curve = window.project.dataset.curve(curve_id)
        replacement = np.asarray(values, dtype=float).reshape(-1).copy()
        if replacement.shape != curve.y.shape or not np.all(np.isfinite(replacement)):
            raise ValueError("Replacement Y values must be finite and match the spectrum length.")
        if metadata is not None and not metadata_key:
            raise ValueError("A metadata key is required when metadata is supplied.")
        metadata = copy.deepcopy(metadata)
        json.dumps(metadata, allow_nan=False)
        from curvemole.core.data import Transformation

        transformation = Transformation(
            "replace_y",
            parameters={"plugin_owner": self.owner},
            description=str(description),
            operand=replacement,
        )
        missing = object()
        previous_metadata = (
            copy.deepcopy(curve.metadata[metadata_key])
            if metadata_key and metadata_key in curve.metadata
            else missing
        )

        def is_replacement(item):
            # General plugin Undo can restore a detached Project, recreating
            # Transformation instances. Object identity then no longer matches.
            return (item.created_at == transformation.created_at
                    and item.operation == transformation.operation
                    and item.parameters == transformation.parameters)

        def redo():
            current = window.project.dataset.curve(curve_id)
            if current.redo_transformations and is_replacement(current.redo_transformations[-1]):
                current.redo_transformation()
            elif not any(is_replacement(item) for item in current.transformations):
                current.apply_transformation(copy.deepcopy(transformation))
            if metadata_key:
                current.metadata[metadata_key] = copy.deepcopy(metadata)

        def undo():
            current = window.project.dataset.curve(curve_id)
            if current.transformations and is_replacement(current.transformations[-1]):
                current.undo_transformation()
            if metadata_key:
                if previous_metadata is missing:
                    current.metadata.pop(metadata_key, None)
                else:
                    current.metadata[metadata_key] = copy.deepcopy(previous_metadata)

        window._push_change(str(description), redo, undo, modified_curve_ids={curve_id})

    def edit_data_points(self, curve_id, *, axes="xy"):
        """Open the native point editor for the active spectrum without changing data."""
        window = self._window()
        if axes not in {"x", "y", "xy"}:
            raise ValueError("Choose x, y or xy for point editing.")
        if window._thread is not None or window.project.read_only:
            raise ValueError("Wait for the calculation to finish, or use an editable project.")
        if curve_id is None or curve_id != window.active_curve_id:
            raise ValueError("The selected spectrum changed; select it again before editing.")
        curve = window.project.dataset.curve(curve_id)
        workspace = window.plot_workspace
        if not any(item.id == curve.id for item in workspace.displayed_curves()):
            raise ValueError("Show the active spectrum in the main graph before editing its points.")
        window.edit_data_points_action.setChecked(True)
        editor = workspace.point_editor
        if not editor.active:
            raise ValueError("The data-point editor could not be opened.")
        editor.axes.setCurrentIndex(editor.axes.findData(axes))
        workspace.graphics.setFocus()

    def plot_session(self, curve_id):
        """Create/reuse an owner-scoped main-plot preview and sample-selection session."""
        from curvemole.gui.plugin_plot import PluginPlotSession

        window = self._window()
        if curve_id is None or curve_id != window.active_curve_id:
            raise ValueError("Select the active spectrum before opening a plot session.")
        workspace = window.plot_workspace
        if not any(c.id == curve_id for c in workspace.displayed_curves()):
            raise ValueError("Show the active spectrum in the main graph first.")
        session = workspace._plugin_plot_sessions.get(self.owner)
        if session is not None and session._curve() is None:
            session._invalidate()
            session = None
        if session is None:
            session = PluginPlotSession(window, self.owner, curve_id)
            workspace._plugin_plot_sessions[self.owner] = session
        return session

    def select_masks(self, masks):
        """Select existing editable masks without changing fit data or fit state."""
        window = self._window()
        if window._thread is not None or window.project.read_only:
            raise ValueError("Wait for the fit to finish, or use an editable project.")
        masks = dict(masks)
        previous = {}
        for curve_id, name in masks.items():
            curve = window.project.dataset.curve(curve_id)
            if name not in curve.masks:
                raise ValueError("The requested mask no longer exists.")
            previous[curve_id] = curve.active_mask
        def restore(values):
            for curve_id, name in values.items():
                window.project.dataset.curve(curve_id).active_mask = name
        if previous != masks:
            window._push_change("Select editable masks", lambda: restore(masks),
                                lambda: restore(previous), modified_curve_ids=set())
        window.plot_workspace.mask_action.setChecked(True)

    def monitor_status(self):
        controller = self._window().folder_import
        own = controller.scan is not None and any(
            e.identifier == controller.processor_id and e.owner == self.owner
            for e in extensions.values("import_processors")
        )
        return {"running": own, "busy": controller.future is not None,
                "other_running": controller.scan is not None and not own,
                "follow": getattr(controller, "follow", True),
                "folder": str(controller.scan.folder) if own else "",
                "contains": controller.scan.contains if own else ""}

    def start_monitor(self, folder, contains, *, include_existing=False, follow=True):
        window = self._window()
        entries = [e for e in extensions.values("import_processors") if e.owner == self.owner]
        if len(entries) != 1:
            raise ValueError("The panel requires exactly one automatic import processor.")
        window.folder_import.start(
            folder, contains, processor=entries[0].identifier,
            include_existing=include_existing, follow=follow,
        )

    def stop_monitor(self):
        if self.monitor_status()["running"]:
            self._window().folder_import.stop()

    def set_follow(self, follow):
        if self.monitor_status()["running"]:
            controller = self._window().folder_import
            controller.follow = bool(follow)
            if controller.dialog is not None:
                controller.dialog.follow.setChecked(bool(follow))
