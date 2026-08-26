"""Restricted mathematical expressions for formulas and parameter links.

Expressions are interpreted from an AST. They are never passed to ``eval`` or
``exec``. Parameter links may use ``${curve.component.parameter}`` references.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import special

from curvemole.core.errors import ExpressionError

_REFERENCE = re.compile(r"\$\{([^{}]+)\}")

_FUNCTIONS = {
    "abs": np.abs,
    "sqrt": np.sqrt,
    "exp": np.exp,
    "log": np.log,
    "log10": np.log10,
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "arcsin": np.arcsin,
    "arccos": np.arccos,
    "arctan": np.arctan,
    "sinh": np.sinh,
    "cosh": np.cosh,
    "tanh": np.tanh,
    "erf": special.erf,
    "erfc": special.erfc,
    "minimum": np.minimum,
    "maximum": np.maximum,
    "clip": np.clip,
    "where": np.where,
    "heaviside": np.heaviside,
}

_CONSTANTS = {"pi": math.pi, "e": math.e, "inf": math.inf}
_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: np.logical_not}
_CMPOPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


@dataclass(frozen=True, slots=True)
class SafeExpression:
    """A validated expression and its explicit parameter references."""

    source: str
    _tree: ast.Expression
    _references: tuple[tuple[str, str], ...]

    @classmethod
    def compile(cls, source: str) -> SafeExpression:
        if not source or not source.strip():
            raise ExpressionError("Expression is empty.")
        references: list[tuple[str, str]] = []

        def replace(match: re.Match[str]) -> str:
            name = f"__ref_{len(references)}"
            path = match.group(1).strip()
            if not path:
                raise ExpressionError("An empty ${...} parameter reference was found.")
            references.append((name, path))
            return name

        rewritten = _REFERENCE.sub(replace, source)
        try:
            tree = ast.parse(rewritten, mode="eval")
        except SyntaxError as exc:
            raise ExpressionError(f"Invalid expression at column {exc.offset}: {exc.msg}") from exc
        _Validator().visit(tree)
        return cls(source=source, _tree=tree, _references=tuple(references))

    @property
    def references(self) -> tuple[str, ...]:
        return tuple(path for _, path in self._references)

    @property
    def variables(self) -> tuple[str, ...]:
        names = {
            node.id
            for node in ast.walk(self._tree)
            if isinstance(node, ast.Name)
            and node.id not in _FUNCTIONS
            and node.id not in _CONSTANTS
            and not node.id.startswith("__ref_")
        }
        return tuple(sorted(names))

    def evaluate(
        self,
        variables: Mapping[str, Any] | None = None,
        references: Mapping[str, Any] | None = None,
    ) -> Any:
        environment: dict[str, Any] = dict(_CONSTANTS)
        environment.update(variables or {})
        reference_values = references or {}
        for internal, path in self._references:
            if path not in reference_values:
                raise ExpressionError(f"Unknown parameter reference: {path}")
            environment[internal] = reference_values[path]
        try:
            return _Interpreter(environment).visit(self._tree.body)
        except ExpressionError:
            raise
        except Exception as exc:
            raise ExpressionError(f"Expression failed: {exc}") from exc


class _Validator(ast.NodeVisitor):
    _allowed = (
        ast.Expression,
        ast.Constant,
        ast.Name,
        ast.Load,
        ast.BinOp,
        ast.UnaryOp,
        ast.Call,
        ast.IfExp,
        ast.Compare,
        ast.BoolOp,
        *tuple(_BINOPS),
        *tuple(_UNARYOPS),
        *tuple(_CMPOPS),
        ast.And,
        ast.Or,
    )

    def generic_visit(self, node: ast.AST) -> None:
        if not isinstance(node, self._allowed):
            raise ExpressionError(f"Unsupported or unsafe syntax: {type(node).__name__}")
        super().generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise ExpressionError("Only documented mathematical functions may be called.")
        if node.keywords:
            raise ExpressionError("Keyword arguments are not supported in formulas.")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, (int, float, bool)):
            raise ExpressionError("Only numeric and boolean constants are allowed.")


class _Interpreter(ast.NodeVisitor):
    def __init__(self, environment: Mapping[str, Any]) -> None:
        self.environment = environment

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id in self.environment:
            return self.environment[node.id]
        if node.id in _FUNCTIONS:
            return _FUNCTIONS[node.id]
        raise ExpressionError(f"Unknown symbol: {node.id}")

    def visit_Constant(self, node: ast.Constant) -> Any:
        return node.value

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        operation = _BINOPS.get(type(node.op))
        if operation is None:
            raise ExpressionError(f"Unsupported operator: {type(node.op).__name__}")
        return operation(self.visit(node.left), self.visit(node.right))

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operation = _UNARYOPS.get(type(node.op))
        if operation is None:
            raise ExpressionError(f"Unsupported unary operator: {type(node.op).__name__}")
        return operation(self.visit(node.operand))

    def visit_Call(self, node: ast.Call) -> Any:
        function = _FUNCTIONS[node.func.id]
        return function(*(self.visit(argument) for argument in node.args))

    def visit_Compare(self, node: ast.Compare) -> Any:
        left = self.visit(node.left)
        result: Any = True
        for operation_node, comparator in zip(node.ops, node.comparators, strict=True):
            operation = _CMPOPS[type(operation_node)]
            right = self.visit(comparator)
            result = np.logical_and(result, operation(left, right))
            left = right
        return result

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        operation = np.logical_and if isinstance(node.op, ast.And) else np.logical_or
        values = [self.visit(value) for value in node.values]
        result = values[0]
        for value in values[1:]:
            result = operation(result, value)
        return result

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        condition = self.visit(node.test)
        if np.ndim(condition):
            return np.where(condition, self.visit(node.body), self.visit(node.orelse))
        return self.visit(node.body) if bool(condition) else self.visit(node.orelse)

    def generic_visit(self, node: ast.AST) -> Any:
        raise ExpressionError(f"Unsupported expression node: {type(node).__name__}")


def expression_parameters(source: str, *, independent: str = "x") -> tuple[str, ...]:
    """Return formula parameter names, excluding x, functions, and constants."""

    expression = SafeExpression.compile(source)
    return tuple(name for name in expression.variables if name != independent)
