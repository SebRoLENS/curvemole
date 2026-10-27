"""Transaction snapshots that preserve numerical results and live edit identities."""
from __future__ import annotations

import copy
from dataclasses import fields

_RESULT_MAPS = {"fit_by_curve", "uncertainty_by_curve", "uncertainty_reports_by_curve",
                "global_fit_baselines", "uncertainty_failures_by_curve"}


def copy_result_maps(results):
    """Detach mutable map containers; completed result payloads remain shared."""
    snapshot = {}
    method_maps = {"uncertainty_by_curve", "uncertainty_reports_by_curve", "uncertainty_failures_by_curve"}
    for key, value in results.items():
        if key in method_maps and isinstance(value, dict):
            value = {identity: dict(methods) if isinstance(methods, dict) else methods
                     for identity, methods in value.items()}
        elif key in _RESULT_MAPS and isinstance(value, dict):
            value = dict(value)
        snapshot[key] = value
    return snapshot


def restore_model(target, saved, refs=None):
    """Replace model state while retaining existing component/parameter objects."""
    target.name, target.id = saved.name, saved.id
    target.display_order = list(saved.display_order)
    target.operation_order = list(saved.operation_order)
    if refs is None:
        refs = {c.id: (c, dict(c.parameters)) for c in target.components}
    components = []
    for snapshot in saved.components:
        if snapshot.id not in refs:
            components.append(copy.deepcopy(snapshot))
            continue
        component, parameters = refs[snapshot.id]
        for field in fields(snapshot):
            if field.name != "parameters":
                setattr(component, field.name, copy.deepcopy(getattr(snapshot, field.name)))
        component.parameters = {}
        for name, parameter in snapshot.parameters.items():
            current = parameters.get(name)
            if current is None:
                current = copy.deepcopy(parameter)
            else:
                for field in fields(parameter):
                    setattr(current, field.name, copy.deepcopy(getattr(parameter, field.name)))
            component.parameters[name] = current
        components.append(component)
    target.components = components
