"""Reconstruct builtin and declarative formula functions in spawned workers."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from curvemole.core.functions import builtin_definitions, formula_definition
from curvemole.core.models import Model
from curvemole.core.registry import FunctionRegistry


def worker_formula_specs(
    registry: FunctionRegistry, models: Mapping[str, Model], curve_ids: Sequence[str],
) -> dict[str, Any] | None:
    """Transfer declarative formulas, never executable plugin callbacks."""
    builtins = {definition.identifier: definition.evaluator for definition in builtin_definitions()}
    formulas = {}
    for curve_id in curve_ids:
        for component in models[curve_id].components:
            if not component.enabled:
                continue
            definition = registry.get(component.function_id)
            if definition.evaluator is builtins.get(component.function_id):
                continue
            # Metadata alone is insufficient: only evaluators created by our
            # safe formula builder may be reconstructed this way.
            if (getattr(definition.evaluator, "__module__", "") != "curvemole.core.functions"
                    or getattr(definition.evaluator, "__qualname__", "") != "formula_definition.<locals>.evaluator"
                    or "formula" not in definition.custom_metadata):
                return None
            formulas[component.function_id] = {
                "display_name": definition.display_name, "kind": definition.kind,
                **{key: copy.deepcopy(definition.custom_metadata[key])
                   for key in ("formula", "defaults", "bounds", "derived_formulas")
                   if key in definition.custom_metadata},
            }
    return formulas


def registry_from_worker_formulas(formulas: Mapping[str, Any]) -> FunctionRegistry:
    registry = FunctionRegistry()
    registry.extend(builtin_definitions())
    for identifier, spec in formulas.items():
        registry.register(formula_definition(identifier, **spec), replace=True)
    return registry
