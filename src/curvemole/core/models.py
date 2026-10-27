"""Composable function models independent of fitting and presentation."""

from __future__ import annotations

import copy
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from curvemole.core.errors import DataValidationError
from curvemole.core.parameters import Parameter, resolve_parameter_values
from curvemole.core.registry import FunctionRegistry, default_registry


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass(slots=True)
class Component:
    function_id: str
    name: str
    parameters: dict[str, Parameter]
    operator: str = "add"
    enabled: bool = True
    is_background: bool = False
    group: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: _identifier("component"))

    @classmethod
    def create(
        cls,
        function_id: str,
        *,
        registry: FunctionRegistry | None = None,
        name: str | None = None,
        initial: Mapping[str, float] | None = None,
        metadata: Mapping[str, Any] | None = None,
        operator: str = "add",
    ) -> Component:
        registry = registry or default_registry()
        definition = registry.get(function_id)
        meta = definition.configuration(metadata)
        return cls(
            function_id=function_id,
            name=name or definition.display_name,
            parameters=definition.make_parameters(initial, meta),
            operator=operator,
            metadata=meta,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "function_id": self.function_id,
            "name": self.name,
            "operator": self.operator,
            "enabled": self.enabled,
            "is_background": self.is_background,
            "group": self.group,
            "metadata": self.metadata,
            "parameters": {name: parameter.to_dict() for name, parameter in self.parameters.items()},
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Component:
        return cls(
            id=str(value["id"]),
            function_id=str(value["function_id"]),
            name=str(value["name"]),
            operator=str(value.get("operator", "add")),
            enabled=bool(value.get("enabled", True)),
            is_background=bool(value.get("is_background", False)),
            group=str(value["group"]) if value.get("group") else None,
            metadata=dict(value.get("metadata", {})),
            parameters={
                str(name): Parameter.from_dict(parameter)
                for name, parameter in dict(value["parameters"]).items()
            },
        )


@dataclass(slots=True)
class Model:
    name: str = "Model"
    components: list[Component] = field(default_factory=list)
    id: str = field(default_factory=lambda: _identifier("model"))
    display_order: list[str] = field(default_factory=list)
    operation_order: list[str] = field(default_factory=list)

    @property
    def composition_mode(self) -> str:
        """Every model uses global roles, regardless of its saved format."""
        return "global"

    @property
    def display_components(self) -> list[Component]:
        """Functions in presentation order, independent of mathematical composition."""
        positions = {component_id: index for index, component_id in enumerate(self.display_order)}
        return sorted(self.components, key=lambda item: positions.get(item.id, len(positions)))

    def add(self, component: Component, index: int | None = None) -> None:
        if any(item.id == component.id for item in self.components):
            raise DataValidationError(f"Component id '{component.id}' is already in model '{self.name}'.")
        if index is None:
            self.components.append(component)
        else:
            self.components.insert(index, component)

    def remove(self, component_id: str) -> Component:
        for index, component in enumerate(self.components):
            if component.id == component_id:
                self.display_order = [item for item in self.display_order if item != component_id]
                self.operation_order = [item for item in self.operation_order if item != component_id]
                return self.components.pop(index)
        raise KeyError(component_id)

    def delete_components(self, component_ids: set[str]) -> None:
        """Delete functions without changing the surviving functions' roles."""
        existing = {component.id for component in self.components}
        missing = component_ids - existing
        if missing:
            raise KeyError(next(iter(missing)))
        self.components = [component for component in self.components if component.id not in component_ids]
        self.display_order = [component_id for component_id in self.display_order if component_id not in component_ids]
        self.operation_order = [component_id for component_id in self.operation_order if component_id not in component_ids]

    def duplicate(self, component_id: str) -> Component:
        source = self.component(component_id)
        duplicate = Component.from_dict(source.to_dict())
        duplicate.metadata.pop("background_subtraction_ids", None)
        duplicate.metadata.pop("background_unresolved_ids", None)
        duplicate.metadata["background_history_detached"] = True
        duplicate.id = _identifier("component")
        duplicate.name = f"{source.name} copy"
        self.components.insert(self.components.index(source) + 1, duplicate)
        if self.display_order:
            order = [item.id for item in self.display_components if item.id != duplicate.id]
            order.insert(order.index(component_id) + 1, duplicate.id)
            self.display_order = order
        return duplicate

    def move(self, component_id: str, index: int) -> None:
        calculation_order = list(self.operation_order)
        component = self.remove(component_id)
        self.components.insert(max(0, min(index, len(self.components))), component)
        self.operation_order = calculation_order
        self.display_order = []

    def component(self, component_id: str) -> Component:
        for component in self.components:
            if component.id == component_id:
                return component
        raise KeyError(component_id)

    def validate_composition(self) -> None:
        if len(self.operation_order) != len(set(self.operation_order)):
            raise DataValidationError("Calculation order contains duplicate functions.")
        for component in self.components:
            if component.operator not in {"add", "subtract", "multiply", "divide", "convolve"}:
                raise DataValidationError(f"Unknown component operator: {component.operator}")

    def set_component_operator(self, component_id: str, operator: str) -> None:
        component = self.component(component_id)
        if component.is_background and operator in {"multiply", "divide", "convolve"}:
            raise DataValidationError("Unmark this function as background before choosing Multiply, Divide or Convolve.")
        old = component.operator
        component.operator = operator
        try:
            self.validate_composition()
        except Exception:
            component.operator = old
            raise

    def parameter_map(self, curve_id: str) -> dict[str, Parameter]:
        return {
            self.parameter_path(curve_id, component.id, name): parameter
            for component in self.components
            for name, parameter in component.parameters.items()
        }

    @staticmethod
    def parameter_path(curve_id: str, component_id: str, name: str) -> str:
        return f"{curve_id}.{component_id}.{name}"

    def evaluate(
        self,
        x: np.ndarray,
        *,
        curve_id: str | None = None,
        values: Mapping[str, float] | None = None,
        registry: FunctionRegistry | None = None,
        components: bool = False,
    ) -> np.ndarray | tuple[np.ndarray, dict[str, np.ndarray]]:
        registry = registry or default_registry()
        prefix = curve_id or self.id
        if values is None:
            values = resolve_parameter_values(self.parameter_map(prefix))
        component_values: dict[str, np.ndarray] = {}
        for component in self.components:
            if not component.enabled:
                continue
            if component.operator not in {"add", "subtract", "multiply", "divide", "convolve"}:
                raise DataValidationError(f"Unknown component operator: {component.operator}")
            definition = registry.get(component.function_id)
            parameters = {
                name: float(values.get(self.parameter_path(prefix, component.id, name), parameter.value))
                for name, parameter in component.parameters.items()
            }
            evaluated = definition.evaluate(np.asarray(x, dtype=float), parameters, component.metadata)
            component_values[component.id] = evaluated
        total = self._evaluate_global(np.asarray(x, dtype=float), component_values)
        return (total, component_values) if components else total

    @property
    def ordered_operations(self) -> list[Component]:
        """User-selected calculation order, separate from insertion/display order."""
        rank = {"multiply": 0, "divide": 1, "convolve": 2}
        positions = {identity: index for index, identity in enumerate(self.operation_order)}
        operations = [c for c in self.components if c.operator in rank]
        return sorted(operations, key=lambda c: (
            positions.get(c.id, len(positions)), rank[c.operator] if c.id not in positions else 0, c.id,
        ))

    def _evaluate_global(self, x: np.ndarray, evaluated: dict[str, np.ndarray]) -> np.ndarray:
        terms = sorted((c for c in self.components if c.enabled and c.id in evaluated
                        and c.operator in {"add", "subtract"}), key=lambda c: c.id)
        total = None
        if terms:
            total = np.zeros_like(x, dtype=float)
            for component in terms:
                total += evaluated[component.id] * (1 if component.operator == "add" else -1)
        operations = [c for c in self.ordered_operations if c.enabled and c.id in evaluated]
        index = 0
        while index < len(operations):
            component = operations[index]
            if component.operator == "convolve":
                from scipy.signal import fftconvolve
                # Crop once per consecutive convolution block. Repeated 'same'
                # cropping would make three kernels depend on their insertion order.
                arrays = [] if total is None else [total]
                while index < len(operations) and operations[index].operator == "convolve":
                    arrays.append(evaluated[operations[index].id])
                    index += 1
                spacing = np.nanmedian(np.abs(np.diff(x))) if len(x) > 1 else 1.0
                full = arrays[0].copy()
                for array in arrays[1:]:
                    full = fftconvolve(full, array, mode="full") * spacing
                offset = (len(full) - len(x)) // 2
                total = full[offset:offset + len(x)]
                continue
            if total is None:
                total = np.ones_like(x, dtype=float)
            if component.operator == "multiply":
                total = total * evaluated[component.id]
            elif component.operator == "divide":
                with np.errstate(divide="ignore", invalid="ignore"):
                    total = total / evaluated[component.id]
            index += 1
        return np.zeros_like(x, dtype=float) if total is None else total

    def calculation_expression(self) -> str:
        enabled = [c for c in self.components if c.enabled]
        terms = sorted((c for c in enabled if c.operator in {"add", "subtract"}), key=lambda c: c.id)
        expression = ""
        for component in terms:
            sign = "+" if component.operator == "add" else "−"
            expression += (f" {sign} " if expression else "−" if sign == "−" else "") + component.name
        operations = [c for c in self.ordered_operations if c.enabled]
        for component in operations:
            name = component.name
            if component.operator == "convolve":
                expression = f"convolve({expression}, {name})" if expression else name
            elif component.operator == "multiply":
                expression = f"({expression}) × {name}" if expression else name
            elif component.operator == "divide":
                expression = f"({expression or '1'}) / {name}"
        return expression or "0"

    def background(
        self,
        x: np.ndarray,
        *,
        curve_id: str | None = None,
        values: Mapping[str, float] | None = None,
        registry: FunctionRegistry | None = None,
        component_ids: set[str] | None = None,
        evaluated_components: Mapping[str, np.ndarray] | None = None,
    ) -> np.ndarray:
        """Evaluate marked background components, or an explicit selected subset."""
        registry = registry or default_registry()
        prefix = curve_id or self.id
        if values is None:
            values = resolve_parameter_values(self.parameter_map(prefix))
        selected = set(component_ids) if component_ids is not None else None
        result = np.zeros_like(x, dtype=float)
        global_operations = any(c.enabled and c.operator not in {"add", "subtract"} for c in self.components)
        if evaluated_components is None and global_operations:
            _, evaluated_components = self.evaluate(x, curve_id=curve_id, values=values, registry=registry, components=True)
        included = set()
        for component in self.components:
            if not component.enabled:
                continue
            if selected is None:
                if not component.is_background:
                    continue
            elif component.id not in selected:
                continue
            if component.operator not in {"add", "subtract"}:
                raise DataValidationError(
                    f"Background component '{component.name}' must use add or subtract composition."
                )
            definition = registry.get(component.function_id)
            parameters = {
                name: values.get(self.parameter_path(prefix, component.id, name), parameter.value)
                for name, parameter in component.parameters.items()
            }
            evaluated = (evaluated_components[component.id] if evaluated_components is not None
                         else definition.evaluate(np.asarray(x, dtype=float), parameters, component.metadata))
            result += evaluated if component.operator == "add" else -evaluated
            included.add(component.id)
        if included and any(
            c.enabled and c.operator not in {"add", "subtract"} for c in self.components
        ):
            evaluated = dict(evaluated_components)
            for component in self.components:
                if component.operator in {"add", "subtract"} and component.id not in included:
                    evaluated[component.id] = np.zeros_like(x, dtype=float)
            return self._evaluate_global(np.asarray(x, dtype=float), evaluated)
        return result

    def derived_quantities(
        self,
        *,
        curve_id: str | None = None,
        values: Mapping[str, float] | None = None,
        registry: FunctionRegistry | None = None,
    ) -> dict[str, dict[str, float | None]]:
        registry = registry or default_registry()
        prefix = curve_id or self.id
        if values is None:
            values = resolve_parameter_values(self.parameter_map(prefix))
        result: dict[str, dict[str, float | None]] = {}
        for component in self.components:
            definition = registry.get(component.function_id)
            local = {
                name: values.get(self.parameter_path(prefix, component.id, name), parameter.value)
                for name, parameter in component.parameters.items()
            }
            result[component.id] = definition.derived_values(local, component.metadata)
        return result

    def validate(self, registry: FunctionRegistry | None = None) -> None:
        registry = registry or default_registry()
        ids = [component.id for component in self.components]
        if len(ids) != len(set(ids)):
            raise DataValidationError(f"Model '{self.name}' contains duplicate component identifiers.")
        for component in self.components:
            definition = registry.get(component.function_id)
            expected = {spec.name for spec in definition.specs(component.metadata)}
            if set(component.parameters) != expected:
                raise DataValidationError(
                    f"Component '{component.name}' parameters do not match '{definition.display_name}'."
                )
            for parameter in component.parameters.values():
                parameter.validate()

    def clone(self) -> Model:
        return Model.from_dict(copy.deepcopy(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "components": [item.to_dict() for item in self.components],
                "display_order": list(self.display_order),
                "composition_mode": self.composition_mode, "operation_order": list(self.operation_order)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Model:
        return cls(
            id=str(value["id"]),
            name=str(value.get("name", "Model")),
            components=[Component.from_dict(item) for item in value.get("components", [])],
            display_order=[str(item) for item in value.get("display_order", [])],
            operation_order=[str(item) for item in value.get("operation_order", [])],
        )


def component_height(
    component: Component,
    *,
    registry: FunctionRegistry | None = None,
) -> float | None:
    definition = (registry or default_registry()).get(component.function_id)
    if definition.kind != "peak" or "center" not in component.parameters:
        return None
    center = component.parameters["center"].value
    values = {name: parameter.value for name, parameter in component.parameters.items()}
    return float(definition.evaluate(np.array([center]), values, component.metadata)[0])


def area_for_height(
    component: Component,
    height: float,
    *,
    registry: FunctionRegistry | None = None,
) -> float:
    if "area" not in component.parameters:
        raise DataValidationError(f"Component '{component.name}' has no area parameter.")
    definition = (registry or default_registry()).get(component.function_id)
    values = {name: parameter.value for name, parameter in component.parameters.items()}
    values["area"] = 1.0
    center = values.get("center", 0.0)
    unit_height = float(definition.evaluate(np.array([center]), values, component.metadata)[0])
    if not math.isfinite(unit_height) or unit_height == 0:
        raise DataValidationError(f"Cannot derive area from height for '{component.name}'.")
    return float(height) / unit_height
