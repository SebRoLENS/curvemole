"""Composable function models independent of fitting and presentation."""

from __future__ import annotations

import copy
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.signal import fftconvolve

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
        meta = dict(metadata or {})
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
                return self.components.pop(index)
        raise KeyError(component_id)

    def duplicate(self, component_id: str) -> Component:
        source = self.component(component_id)
        duplicate = Component.from_dict(source.to_dict())
        duplicate.id = _identifier("component")
        duplicate.name = f"{source.name} copy"
        self.components.insert(self.components.index(source) + 1, duplicate)
        return duplicate

    def move(self, component_id: str, index: int) -> None:
        component = self.remove(component_id)
        self.components.insert(max(0, min(index, len(self.components))), component)

    def component(self, component_id: str) -> Component:
        for component in self.components:
            if component.id == component_id:
                return component
        raise KeyError(component_id)

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
        total: np.ndarray | None = None
        component_values: dict[str, np.ndarray] = {}
        for component in self.components:
            if not component.enabled:
                continue
            definition = registry.get(component.function_id)
            parameters = {
                name: float(values.get(self.parameter_path(prefix, component.id, name), parameter.value))
                for name, parameter in component.parameters.items()
            }
            evaluated = definition.evaluate(np.asarray(x, dtype=float), parameters, component.metadata)
            component_values[component.id] = evaluated
            if total is None:
                if component.operator == "subtract":
                    total = -evaluated
                elif component.operator in {"multiply", "divide", "convolve"}:
                    raise DataValidationError(
                        f"First enabled component '{component.name}' cannot use {component.operator}."
                    )
                else:
                    total = evaluated.copy()
                continue
            if component.operator == "add":
                total = total + evaluated
            elif component.operator == "subtract":
                total = total - evaluated
            elif component.operator == "multiply":
                total = total * evaluated
            elif component.operator == "divide":
                with np.errstate(divide="ignore", invalid="ignore"):
                    total = total / evaluated
            elif component.operator == "convolve":
                spacing = np.nanmedian(np.abs(np.diff(x))) if len(x) > 1 else 1.0
                total = fftconvolve(total, evaluated, mode="same") * spacing
            else:
                raise DataValidationError(f"Unknown component operator: {component.operator}")
        if total is None:
            total = np.zeros_like(x, dtype=float)
        return (total, component_values) if components else total

    def background(
        self,
        x: np.ndarray,
        *,
        curve_id: str | None = None,
        values: Mapping[str, float] | None = None,
        registry: FunctionRegistry | None = None,
    ) -> np.ndarray:
        registry = registry or default_registry()
        prefix = curve_id or self.id
        if values is None:
            values = resolve_parameter_values(self.parameter_map(prefix))
        result = np.zeros_like(x, dtype=float)
        for component in self.components:
            definition = registry.get(component.function_id)
            if not component.enabled or definition.kind != "background":
                continue
            parameters = {
                name: values.get(self.parameter_path(prefix, component.id, name), parameter.value)
                for name, parameter in component.parameters.items()
            }
            evaluated = definition.evaluate(x, parameters, component.metadata)
            result += evaluated if component.operator != "subtract" else -evaluated
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
        return {"id": self.id, "name": self.name, "components": [item.to_dict() for item in self.components]}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Model:
        return cls(
            id=str(value["id"]),
            name=str(value.get("name", "Model")),
            components=[Component.from_dict(item) for item in value.get("components", [])],
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
