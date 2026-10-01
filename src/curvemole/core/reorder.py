"""Order model functions and their automatic names by a chosen parameter."""

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
    """Sort display order and number each type, without altering model composition.

    Components keep their IDs, mathematical order and custom names. Functions without a finite sort
    parameter keep their list slots. Equal values retain their relative order.
    A custom name reserves its spelling against automatic numbering.
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
    sortable = []
    displayed = model.display_components
    for index, component in enumerate(displayed):
        parameter = component.parameters.get(rules.get(component.function_id, "center"))
        if parameter is not None and math.isfinite(parameter.value):
            sortable.append((index, component, parameter.value))
    ordered = sorted(sortable, key=lambda item: item[2])
    for (index, _, _), (_, component, _) in zip(sortable, ordered, strict=True):
        displayed[index] = component
    order = [component.id for component in displayed]
    if order != [component.id for component in model.display_components]:
        model.display_order = order
    return changed
