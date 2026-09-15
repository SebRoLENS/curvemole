"""Restricted formulas over retained numerical columns (one-based c1, c2, …)."""
from __future__ import annotations

import re

import numpy as np

from curvemole.core.errors import DataValidationError
from curvemole.core.expressions import SafeExpression


def compile_column_formula(formula: str, target: str) -> SafeExpression:
    source = "".join(part if part.startswith("${") else part.replace("^", "**")
                     for part in re.split(r"(\$\{[^{}]+\})", str(formula).strip()))
    assignment = re.match(r"^([A-Za-z][A-Za-z0-9_]*)\s*=(?!=)(.*)$", source, re.S)
    if assignment:
        if assignment[1].lower() != target.lower():
            raise DataValidationError(f"Formula assignment must target {target}.")
        source = assignment[2].strip()
    return SafeExpression.compile(source)


def evaluate_columns(formula, target, x, y, columns, labels, axes):
    destination = axes.get(target, target)
    if target not in {"x", "y"} and destination not in columns:
        raise DataValidationError(f"Column {target!r} is unavailable in this spectrum.")
    expression = compile_column_formula(formula, target)
    environment = dict(columns, x=x, y=y)
    references = {label: columns[key] for key, label in labels.items() if key in columns}
    missing = set(expression.variables) - environment.keys()
    missing |= set(expression.references) - references.keys()
    if missing:
        raise DataValidationError(f"Unavailable column(s): {', '.join(sorted(missing))}.")
    with np.errstate(all="ignore"):
        result = np.asarray(expression.evaluate(environment, references), dtype=np.float64)
    if result.ndim == 0:
        result = np.full(len(x), float(result))
    if result.shape != x.shape or not np.all(np.isfinite(result)):
        raise DataValidationError("Column formula must return one finite value per row.")
    if destination in columns:
        columns[destination] = result.copy()
    if target == "x" or destination == axes.get("x"):
        x = result.copy()
    if target == "y" or destination == axes.get("y"):
        y = result.copy()
    return x, y
