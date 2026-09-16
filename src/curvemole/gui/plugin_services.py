"""GUI-thread services for nonmodal plugin panels, without exposing the window."""
from __future__ import annotations

import copy
import json

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
        previous = copy.deepcopy(window.project.ui_state.get("plugin_data", {}))
        if not updates and previous.get(self.owner, {}) == data:
            return
        before = {key: copy.deepcopy(curves[key].metadata) for key in updates}

        def redo():
            window.project.ui_state.setdefault("plugin_data", {})[self.owner] = copy.deepcopy(data)
            for key, value in updates.items():
                window.project.dataset.curve(key).metadata[metadata_key] = copy.deepcopy(value)

        def undo():
            window.project.ui_state["plugin_data"] = copy.deepcopy(previous)
            for key, value in before.items():
                window.project.dataset.curve(key).metadata = copy.deepcopy(value)

        window._push_change("Plugin settings", redo, undo, modified_curve_ids=set())

    def select_masks(self, masks):
        """Select existing editable masks without changing fit data or fit state."""
        window = self._window()
        if window._thread is not None or window.project.read_only:
            raise ValueError("Wait for the fit to finish, or use an editable project.")
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
