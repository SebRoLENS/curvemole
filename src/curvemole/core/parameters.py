"""Parameter values, bounds, fixed states, and expression links."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from curvemole.core.errors import ConstraintError, ExpressionError
from curvemole.core.expressions import SafeExpression


@dataclass(slots=True)
class Parameter:
    name: str
    value: float
    minimum: float = -math.inf
    maximum: float = math.inf
    fixed: bool = False
    link: str | None = None
    unit: str = ""
    standard_error: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None

    def __post_init__(self) -> None:
        self.value = float(self.value)
        self.minimum = float(self.minimum)
        self.maximum = float(self.maximum)
        self.validate()

    def validate(self) -> None:
        if math.isnan(self.value):
            raise ConstraintError(f"Parameter '{self.name}' has a NaN value.")
        if self.minimum > self.maximum:
            raise ConstraintError(
                f"Parameter '{self.name}' has minimum {self.minimum} above maximum {self.maximum}."
            )
        if not self.minimum <= self.value <= self.maximum:
            raise ConstraintError(
                f"Parameter '{self.name}' value {self.value} is outside "
                f"[{self.minimum}, {self.maximum}]."
            )
        if self.link:
            SafeExpression.compile(self.link)

    @property
    def status(self) -> str:
        if self.link:
            return "linked"
        if self.fixed:
            return "fixed"
        if math.isfinite(self.minimum) and math.isfinite(self.maximum):
            return "bounded"
        if math.isfinite(self.minimum):
            return "lower-bounded"
        if math.isfinite(self.maximum):
            return "upper-bounded"
        return "free"

    @property
    def is_free(self) -> bool:
        return not self.fixed and not self.link

    def set_bounds(self, minimum: float = -math.inf, maximum: float = math.inf) -> None:
        self.minimum = float(minimum)
        self.maximum = float(maximum)
        self.validate()

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "fixed": self.fixed,
            "link": self.link,
            "unit": self.unit,
            "standard_error": self.standard_error,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Parameter:
        return cls(
            name=str(value["name"]),
            value=float(value["value"]),
            minimum=float(value.get("minimum", -math.inf)),
            maximum=float(value.get("maximum", math.inf)),
            fixed=bool(value.get("fixed", False)),
            link=str(value["link"]) if value.get("link") else None,
            unit=str(value.get("unit", "")),
            standard_error=(
                float(value["standard_error"]) if value.get("standard_error") is not None else None
            ),
            ci_low=float(value["ci_low"]) if value.get("ci_low") is not None else None,
            ci_high=float(value["ci_high"]) if value.get("ci_high") is not None else None,
        )


def resolve_parameter_values(parameters: Mapping[str, Parameter]) -> dict[str, float]:
    """Resolve fixed/free values and linked expressions with cycle detection."""

    resolved: dict[str, float] = {}
    visiting: list[str] = []

    def resolve(path: str) -> float:
        if path in resolved:
            return resolved[path]
        if path not in parameters:
            raise ConstraintError(f"Linked parameter does not exist: {path}")
        if path in visiting:
            cycle = " -> ".join([*visiting[visiting.index(path) :], path])
            raise ConstraintError(f"Parameter-link cycle detected: {cycle}")
        parameter = parameters[path]
        if not parameter.link:
            resolved[path] = parameter.value
            return parameter.value
        visiting.append(path)
        expression = SafeExpression.compile(parameter.link)
        references: dict[str, float] = {}
        for dependency in expression.references:
            references[dependency] = resolve(dependency)
        try:
            value = float(expression.evaluate(references=references))
        except (ExpressionError, TypeError, ValueError) as exc:
            raise ConstraintError(f"Cannot resolve linked parameter '{path}': {exc}") from exc
        visiting.pop()
        if not parameter.minimum <= value <= parameter.maximum:
            raise ConstraintError(
                f"Linked value {value} for '{path}' violates "
                f"[{parameter.minimum}, {parameter.maximum}]."
            )
        resolved[path] = value
        return value

    for parameter_path in parameters:
        resolve(parameter_path)
    return resolved


def validate_parameter_graph(parameters: Mapping[str, Parameter]) -> None:
    resolve_parameter_values(parameters)


def copy_parameter_values(source: Iterable[Parameter], target: Iterable[Parameter]) -> None:
    source_by_name = {parameter.name: parameter for parameter in source}
    for parameter in target:
        if parameter.name in source_by_name:
            value = source_by_name[parameter.name].value
            parameter.value = min(max(value, parameter.minimum), parameter.maximum)
