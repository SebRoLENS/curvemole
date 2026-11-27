"""Which spectrum and function a Model-panel list item refers to.

Kept free of main-window and panel imports so that the panel, the point editor
and the model-editing extensions can share it without an import cycle.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt

# Item data role carrying the curve id of a function row in the Model panel.
COMPONENT_CURVE_ROLE = int(Qt.ItemDataRole.UserRole) + 1

# Component id the Model panel sends to mean "the whole current multi-selection".
_BATCH = "__curvemole_batch_components__"


def _item_ref(item: Any) -> tuple[str, str] | None:
    if item is None:
        return None
    component_id = item.data(Qt.ItemDataRole.UserRole)
    curve_id = item.data(COMPONENT_CURVE_ROLE)
    if component_id is None or curve_id is None:
        return None
    return str(curve_id), str(component_id)


def _selected_refs(panel: Any) -> list[tuple[str, str]]:
    refs = {
        ref
        for item in panel.components.selectedItems()
        if (ref := _item_ref(item)) is not None
    }
    ordered: list[tuple[str, str]] = []
    for row in range(panel.components.count()):
        ref = _item_ref(panel.components.item(row))
        if ref in refs:
            ordered.append(ref)
    return ordered


def _current_ref(panel: Any) -> tuple[str, str] | None:
    return _item_ref(panel.components.currentItem())


def _find_component_curve(window: Any, component_id: str) -> str | None:
    # Sequential propagation deliberately preserves component IDs. Resolve the
    # visible/selected curve first instead of editing the first original source
    # that happens to carry the same ID.
    candidates = [
        curve_id for curve_id, model in window.project.models.items()
        if any(component.id == component_id for component in model.components)
    ]
    panel = window.model_panel
    current = _current_ref(panel)
    if current and current[1] == component_id and current[0] in candidates:
        return current[0]
    selected = {curve_id for curve_id, selected_id in _selected_refs(panel) if selected_id == component_id}
    if len(selected) == 1:
        curve_id = next(iter(selected))
        if curve_id in candidates:
            return curve_id
    if window.active_curve_id in candidates:
        return window.active_curve_id
    return candidates[0] if len(candidates) == 1 else None


def _restore_models(window: Any, states: dict[str, dict[str, Any]]) -> None:
    """Restore whole model snapshots (curve id -> Model.to_dict()) into the project."""
    from curvemole.core.transactions import restore_model_state

    for curve_id, state in states.items():
        restore_model_state(window.project, curve_id, state)
