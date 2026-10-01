"""Parameter values, bounds, fixed states, and expression links."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from curvemole.core.errors import ConstraintError, ExpressionError
from curvemole.core.expressions import SafeExpression

_LINK_REFERENCE = re.compile(r"\$\{([^{}]+)\}")


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
    link_scope: str = "relative"
    link_reference_scopes: list[str] = field(default_factory=list)
    link_relation: str = "equal"
    link_tolerance: float = 0.0
    link_tolerance_mode: str = "absolute"

    def __post_init__(self) -> None:
        self.value = float(self.value)
        self.minimum = float(self.minimum)
        self.maximum = float(self.maximum)
        self.link_tolerance = float(self.link_tolerance)
        self.validate()

    def validate(self) -> None:
        if self.link_scope not in {"relative", "absolute"}:
            raise ConstraintError(f"Unknown parameter link scope: {self.link_scope}")
        if any(scope not in {"relative", "absolute"} for scope in self.link_reference_scopes):
            raise ConstraintError("Parameter reference scopes must be relative or absolute.")
        if self.link_relation not in {"equal", "lower", "upper", "similar"}:
            raise ConstraintError(f"Unknown parameter link relation: {self.link_relation}")
        if self.link_tolerance_mode not in {"absolute", "percent"}:
            raise ConstraintError(f"Unknown parameter link tolerance mode: {self.link_tolerance_mode}")
        if not math.isfinite(self.link_tolerance) or self.link_tolerance < 0:
            raise ConstraintError("Parameter link tolerance must be finite and nonnegative.")
        if self.link_tolerance_mode == "percent" and self.link_tolerance >= 100:
            raise ConstraintError("Percentage parameter link tolerance must be less than 100%.")
        if self.link_relation == "similar" and self.link_tolerance <= 0:
            raise ConstraintError("Similar parameter links require a positive tolerance.")
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
            expression = SafeExpression.compile(self.link)
            if self.link_reference_scopes and len(self.link_reference_scopes) != len(expression.references):
                raise ConstraintError("Parameter reference scopes must match the expression references.")
            if self.link_relation != "equal" and (
                len(expression.references) != 1 or _LINK_REFERENCE.fullmatch(self.link.strip()) is None
            ):
                raise ConstraintError("A parameter bound link must reference one source parameter directly.")

    @property
    def status(self) -> str:
        if self.link:
            return "linked" if self.link_relation == "equal" else f"{self.link_relation}-linked"
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
        return not self.fixed and (not self.link or self.link_relation != "equal")

    def link_bounds(self, source_value: float) -> tuple[float, float]:
        """Intersect static bounds with the current source parameter relation."""
        self.validate()
        if not self.link:
            return self.minimum, self.maximum
        source_value = float(source_value)
        if not math.isfinite(source_value):
            raise ConstraintError(f"Parameter '{self.name}' link source must be finite.")
        lower, upper = self.minimum, self.maximum
        if self.link_relation == "lower":
            lower = max(lower, source_value)
        elif self.link_relation == "upper":
            upper = min(upper, source_value)
        elif self.link_relation == "similar":
            tolerance = self.link_tolerance
            if self.link_tolerance_mode == "percent":
                tolerance *= abs(source_value) / 100.0
            lower = max(lower, source_value - tolerance)
            upper = min(upper, source_value + tolerance)
        else:
            lower = max(lower, source_value)
            upper = min(upper, source_value)
        if lower > upper:
            raise ConstraintError(
                f"Parameter '{self.name}' static bounds and source relation have an empty intersection "
                f"[{lower}, {upper}]."
            )
        return lower, upper

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
            "link_scope": self.link_scope,
            "link_reference_scopes": list(self.link_reference_scopes),
            "link_relation": self.link_relation,
            "link_tolerance": self.link_tolerance,
            "link_tolerance_mode": self.link_tolerance_mode,
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
            link_scope=str(value.get("link_scope", "relative")),
            link_reference_scopes=list(value.get("link_reference_scopes", [])),
            link_relation=str(value.get("link_relation", "equal")),
            link_tolerance=float(value.get("link_tolerance", 0.0)),
            link_tolerance_mode=str(value.get("link_tolerance_mode", "absolute")),
            unit=str(value.get("unit", "")),
            standard_error=(
                float(value["standard_error"]) if value.get("standard_error") is not None else None
            ),
            ci_low=float(value["ci_low"]) if value.get("ci_low") is not None else None,
            ci_high=float(value["ci_high"]) if value.get("ci_high") is not None else None,
        )

    def effective_link_reference_scopes(self) -> list[str]:
        """Return each reference's copy behavior, including inherited legacy scope."""
        self.validate()
        if not self.link:
            return []
        if self.link_reference_scopes:
            return list(self.link_reference_scopes)
        return [self.link_scope] * len(SafeExpression.compile(self.link).references)

    def copied_link(
        self, source_curve_id: str, target_curve_id: str,
        component_ids: Mapping[str, str] | None = None,
    ) -> str | None:
        """Retarget each local relative occurrence; retain fixed references."""
        if not self.link:
            return self.link
        scopes = iter(self.effective_link_reference_scopes())
        if source_curve_id == target_curve_id:
            return self.link

        def replace(match: re.Match[str]) -> str:
            scope = next(scopes)
            reference = match.group(1).strip()
            parts = reference.split(".", 2)
            if scope == "absolute" or len(parts) != 3 or parts[0] != source_curve_id:
                return match.group(0)
            component_id = parts[1]
            if component_ids is not None:
                if component_id not in component_ids:
                    raise ConstraintError(
                        "Cannot copy a This spectrum link: its source function is missing "
                        "from the destination spectrum. Copy the required functions too."
                    )
                component_id = component_ids[component_id]
            target = f"{target_curve_id}.{component_id}.{parts[2]}"
            return f"${{{target}}}"

        return _LINK_REFERENCE.sub(replace, self.link)


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
        parameter.validate()
        visiting.append(path)
        expression = SafeExpression.compile(parameter.link)
        references: dict[str, float] = {}
        for dependency in expression.references:
            references[dependency] = resolve(dependency)
        try:
            source_value = float(expression.evaluate(references=references))
        except (ExpressionError, TypeError, ValueError) as exc:
            raise ConstraintError(f"Cannot resolve linked parameter '{path}': {exc}") from exc
        visiting.pop()
        if parameter.link_relation != "equal":
            lower, upper = parameter.link_bounds(source_value)
            value = parameter.value
            if not lower <= value <= upper:
                raise ConstraintError(
                    f"Parameter '{path}' value {value} violates its dynamic source bounds "
                    f"[{lower}, {upper}]."
                )
            resolved[path] = value
            return value
        value = source_value
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
