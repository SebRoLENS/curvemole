"""Rename automatically named model functions by a chosen parameter."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Mapping

from curvemole.core.models import Model
from curvemole.core.registry import FunctionRegistry


def reorder_component_names(
    model: Model, registry: FunctionRegistry, rules: Mapping[str, str]
) -> int:
    """Number each function type by its parameter value, leaving custom names alone.

    Components keep their IDs and positions. A custom name also reserves its
    spelling, so an automatic name will never overwrite it.
    """
    groups = defaultdict(list)
    reserved = {component.name for component in model.components
                if component.metadata.get("custom_name")}
    for component in model.components:
        if not component.metadata.get("custom_name"):
            groups[component.function_id].append(component)

    changed = 0
    for function_id, components in groups.items():
        parameter_name = rules.get(function_id, "center")
        if not all(parameter_name in component.parameters and
                   math.isfinite(component.parameters[parameter_name].value)
                   for component in components):
            continue
        base = re.sub(r"[\W_]+", "", registry.get(function_id).display_name, flags=re.UNICODE)
        base = base or "Function"
        number = 1
        for component in sorted(components, key=lambda item: item.parameters[parameter_name].value):
            while f"{base}{number}" in reserved:
                number += 1
            name = f"{base}{number}"
            changed += component.name != name
            component.name = name
            number += 1
    return changed
