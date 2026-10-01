"""Feasible fitting coordinates for parameter bounds that follow another value.

The solver sees box-bounded coordinates. Physical parameter values are rebuilt
in dependency order on every evaluation, so the model never sees a trial value
outside a relational bound. Static limits propagate backwards through direct
relationships before choosing the coordinate bounds.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np

from curvemole.core.errors import ConstraintError
from curvemole.core.expressions import SafeExpression
from curvemole.core.parameters import Parameter


class DynamicParameterCoordinates:
    """Map solver coordinates to a feasible physical parameter dependency DAG."""

    def __init__(self, parameters: Mapping[str, Parameter], free_paths: Sequence[str]) -> None:
        self.parameters = parameters
        self.free_paths = list(free_paths)
        self.free_index = {path: index for index, path in enumerate(self.free_paths)}
        self.expressions = {
            path: SafeExpression.compile(parameter.link)
            for path, parameter in parameters.items() if parameter.link
        }
        self.dynamic = {
            path for path, parameter in parameters.items()
            if parameter.link and parameter.link_relation != "equal"
        }
        self.sources = {
            path: self.expressions[path].references[0] for path in self.dynamic
        }
        self.order = self._dependency_order()
        self.domains = {
            path: ((parameter.value, parameter.value)
                   if parameter.fixed and not (parameter.link and parameter.link_relation == "equal")
                   else (parameter.minimum, parameter.maximum))
            for path, parameter in parameters.items()
        }
        self._propagate_domains()
        self.coordinate_kinds: dict[str, str] = {}
        lower, upper = [], []
        for path in self.free_paths:
            lo, hi = self.domains[path]
            if lo >= hi:
                raise ConstraintError(
                    f"Relational bounds leave no free range for '{path}'. "
                    "Adjust its limits or fix the parameter explicitly."
                )
            if path in self.dynamic:
                relation = self.parameters[path].link_relation
                # The source provides a finite lower/upper limit even when the
                # corresponding static parameter limit is unbounded.
                finite_lo = math.isfinite(lo) or relation in {"lower", "similar"}
                finite_hi = math.isfinite(hi) or relation in {"upper", "similar"}
                if finite_lo and finite_hi:
                    kind, bounds = "fraction", (0.0, 1.0)
                elif finite_lo:
                    kind, bounds = "lower_gap", (0.0, math.inf)
                else:
                    kind, bounds = "upper_gap", (0.0, math.inf)
            else:
                kind, bounds = "physical", (lo, hi)
            self.coordinate_kinds[path] = kind
            lower.append(bounds[0])
            upper.append(bounds[1])
        self.bounds = (np.asarray(lower, dtype=float), np.asarray(upper, dtype=float))

    def _dependency_order(self) -> list[str]:
        order: list[str] = []
        visiting: list[str] = []
        done: set[str] = set()

        def visit(path: str) -> None:
            if path in done:
                return
            if path not in self.parameters:
                raise ConstraintError(f"Linked parameter does not exist: {path}")
            if path in visiting:
                cycle = " -> ".join([*visiting[visiting.index(path):], path])
                raise ConstraintError(f"Parameter-link cycle detected: {cycle}")
            visiting.append(path)
            expression = self.expressions.get(path)
            if expression is not None:
                for source in expression.references:
                    visit(source)
            visiting.pop()
            done.add(path)
            order.append(path)

        for path in self.parameters:
            visit(path)
        return order

    def _propagate_domains(self) -> None:
        for path in reversed(self.order):
            if path not in self.dynamic:
                continue
            parameter = self.parameters[path]
            source = self.sources[path]
            lo, hi = self.domains[path]
            source_lo, source_hi = self.domains[source]
            if parameter.link_relation == "lower":
                source_hi = min(source_hi, hi)
            elif parameter.link_relation == "upper":
                source_lo = max(source_lo, lo)
            elif parameter.link_tolerance_mode == "absolute":
                required_lo = lo - parameter.link_tolerance
                required_hi = hi + parameter.link_tolerance
            else:
                ratio = parameter.link_tolerance / 100.0
                # lower(s)=s-r*abs(s), upper(s)=s+r*abs(s) are
                # monotonic for r<1; invert each branch around zero.
                required_lo = lo / (1 + ratio if lo >= 0 else 1 - ratio)
                required_hi = hi / (1 - ratio if hi >= 0 else 1 + ratio)
            if parameter.link_relation == "similar":
                def delta(value: float, tolerance=parameter.link_tolerance,
                          mode=parameter.link_tolerance_mode) -> float:
                    # Match Parameter.link_bounds's operation order exactly.
                    return tolerance if mode == "absolute" else tolerance * (abs(value) / 100.0)

                # An inverse endpoint can round one ULP outside the feasible
                # interval. Move it inward only when its forward image fails.
                while math.isfinite(required_lo) and required_lo + delta(required_lo) < lo:
                    required_lo = math.nextafter(required_lo, math.inf)
                while math.isfinite(required_hi) and required_hi - delta(required_hi) > hi:
                    required_hi = math.nextafter(required_hi, -math.inf)
                source_lo = max(source_lo, required_lo)
                source_hi = min(source_hi, required_hi)
            if source_lo > source_hi:
                raise ConstraintError(
                    f"The relational and static bounds for '{path}' and '{source}' "
                    "have no feasible intersection. Adjust those bounds."
                )
            self.domains[source] = (source_lo, source_hi)

        # Forward images identify rigid intervals caused by a fixed source
        # (not only by equal static limits), and tighten each dependent domain.
        for path in self.order:
            parameter = self.parameters[path]
            lo, hi = self.domains[path]
            if parameter.link and parameter.link_relation == "equal":
                expression = self.expressions[path]
                if all(self.domains[source][0] == self.domains[source][1]
                       for source in expression.references):
                    value = float(expression.evaluate(references={
                        source: self.domains[source][0] for source in expression.references
                    }))
                    lo, hi = max(lo, value), min(hi, value)
            elif path in self.dynamic:
                source_lo, source_hi = self.domains[self.sources[path]]
                if parameter.link_relation == "lower":
                    lo = max(lo, source_lo)
                elif parameter.link_relation == "upper":
                    hi = min(hi, source_hi)
                elif parameter.link_tolerance_mode == "absolute":
                    lo = max(lo, source_lo - parameter.link_tolerance)
                    hi = min(hi, source_hi + parameter.link_tolerance)
                else:
                    delta_lo = parameter.link_tolerance * (abs(source_lo) / 100.0)
                    delta_hi = parameter.link_tolerance * (abs(source_hi) / 100.0)
                    lo = max(lo, source_lo - delta_lo if math.isfinite(source_lo) else -math.inf)
                    hi = min(hi, source_hi + delta_hi if math.isfinite(source_hi) else math.inf)
            if lo > hi:
                raise ConstraintError(
                    f"The source and static bounds leave no feasible intersection for '{path}'."
                )
            self.domains[path] = (lo, hi)

    def _current_bounds(self, path: str, values: Mapping[str, float]) -> tuple[float, float]:
        lo, hi = self.domains[path]
        if path in self.dynamic:
            dynamic_lo, dynamic_hi = self.parameters[path].link_bounds(values[self.sources[path]])
            lo, hi = max(lo, dynamic_lo), min(hi, dynamic_hi)
        if lo > hi:
            raise ConstraintError(
                f"The current source value leaves no feasible bounds for '{path}'. "
                "A source controlled by an advanced equality expression must also "
                "respect the bounds required by its dependent parameters."
            )
        return lo, hi

    def initial(self) -> np.ndarray:
        """Encode starting values after projecting them into the feasible domains."""
        vector = np.zeros(len(self.free_paths), dtype=float)
        values: dict[str, float] = {}
        for path in self.order:
            parameter = self.parameters[path]
            if parameter.link and parameter.link_relation == "equal":
                expression = self.expressions[path]
                value = float(expression.evaluate(
                    references={source: values[source] for source in expression.references}
                ))
            else:
                lo, hi = self._current_bounds(path, values)
                value = float(parameter.value)
                if path in self.free_index:
                    value = min(max(value, lo), hi)
                    kind = self.coordinate_kinds[path]
                    if kind == "fraction":
                        coordinate = (value - lo) / (hi - lo) if hi > lo else 0.5
                    elif kind == "lower_gap":
                        coordinate = value - lo
                    elif kind == "upper_gap":
                        coordinate = hi - value
                    else:
                        coordinate = value
                    vector[self.free_index[path]] = coordinate
            self._check_value(path, value, values)
            values[path] = value
        return vector

    def decode(self, vector: np.ndarray) -> dict[str, float]:
        if len(vector) != len(self.free_paths):
            raise ConstraintError("The fitting coordinate vector has the wrong dimension.")
        values: dict[str, float] = {}
        for path in self.order:
            parameter = self.parameters[path]
            if parameter.link and parameter.link_relation == "equal":
                expression = self.expressions[path]
                value = float(expression.evaluate(
                    references={source: values[source] for source in expression.references}
                ))
            elif path in self.free_index:
                coordinate = float(vector[self.free_index[path]])
                index = self.free_index[path]
                if not self.bounds[0][index] <= coordinate <= self.bounds[1][index]:
                    raise ConstraintError(f"Fitting coordinate for '{path}' violates its bounds.")
                lo, hi = self._current_bounds(path, values)
                kind = self.coordinate_kinds[path]
                if kind == "fraction":
                    # Weighted endpoints preserve the exact upper/lower value
                    # at u=0/1 even when subtraction has roundoff error.
                    value = min(max((1 - coordinate) * lo + coordinate * hi, lo), hi)
                elif kind == "lower_gap":
                    value = lo + coordinate
                elif kind == "upper_gap":
                    value = hi - coordinate
                else:
                    value = coordinate
            else:
                value = float(parameter.value)
            self._check_value(path, value, values)
            values[path] = value
        return values

    def encode(self, physical_vector: np.ndarray) -> np.ndarray:
        """Encode explicitly supplied physical values, without projecting them."""
        if len(physical_vector) != len(self.free_paths):
            raise ConstraintError("The physical parameter vector has the wrong dimension.")
        vector = np.zeros(len(self.free_paths), dtype=float)
        values: dict[str, float] = {}
        for path in self.order:
            parameter = self.parameters[path]
            if parameter.link and parameter.link_relation == "equal":
                expression = self.expressions[path]
                value = float(expression.evaluate(
                    references={source: values[source] for source in expression.references}
                ))
            elif path in self.free_index:
                value = float(physical_vector[self.free_index[path]])
            else:
                value = float(parameter.value)
            self._check_value(path, value, values)
            if path in self.free_index:
                lo, hi = self._current_bounds(path, values)
                kind = self.coordinate_kinds[path]
                if kind == "fraction":
                    coordinate = (value - lo) / (hi - lo) if hi > lo else .5
                elif kind == "lower_gap":
                    coordinate = value - lo
                elif kind == "upper_gap":
                    coordinate = hi - value
                else:
                    coordinate = value
                vector[self.free_index[path]] = coordinate
            values[path] = value
        return vector

    def _check_value(self, path: str, value: float, values: Mapping[str, float]) -> None:
        if not math.isfinite(value):
            raise ConstraintError(f"Parameter '{path}' has a non-finite constrained value.")
        lo, hi = self._current_bounds(path, values)
        if not lo <= value <= hi:
            parameter = self.parameters[path]
            if (parameter.link and parameter.link_relation == "equal"
                    and self.domains[path] != (parameter.minimum, parameter.maximum)):
                raise ConstraintError(
                    f"The advanced equality expression for '{path}' returns {value}, "
                    f"outside the bounds [{lo}, {hi}] required by its dependent parameters. "
                    "Adjust the expression or the dependent static bounds."
                )
            raise ConstraintError(
                f"Parameter '{path}' value {value} violates its current bounds [{lo}, {hi}]."
            )

    def physical_bounds(self, path: str, values: Mapping[str, float]) -> tuple[float, float]:
        """Return effective physical limits at a particular solved parameter vector."""
        parameter = self.parameters[path]
        if parameter.fixed:
            if path in self.dynamic:
                return parameter.link_bounds(values[self.sources[path]])
            return parameter.minimum, parameter.maximum
        return self._current_bounds(path, values)
