"""Portable, versioned calculator equations shared across projects."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from curvemole.core.columns import compile_column_formula
from curvemole.core.errors import CurveMoleError, DataValidationError

EQUATION_SUFFIX = ".curvemole-equation.json"


def normalize_equation(value: dict[str, Any]) -> dict[str, str]:
    """Convert both historical calculator modes to the column-capable format.

    Keep axis destinations symbolic until a spectrum's column mapping is known.
    Existing transformation histories are deliberately left untouched.
    """
    if not isinstance(value, dict):
        raise DataValidationError("A calculator equation must be an object.")
    name = str(value.get("name", "")).strip()
    source = str(value.get("formula", "")).strip()
    mode = value.get("mode", "custom_formula")
    if mode not in {"custom_formula", "column_formula"}:
        raise DataValidationError("Unknown calculator equation mode.")
    target = str(value.get("axis", "x") if mode == "custom_formula"
                 else value.get("target", "y")).strip().lower()
    if not name or not source:
        raise DataValidationError("Enter a name and formula first.")
    if not re.fullmatch(r"x|y|c[1-9][0-9]*", target):
        raise DataValidationError("Choose a valid destination column.")
    # Store expressions without their optional assignment. This also allows an
    # old 'Y = ...' equation to be recalled as a physical column destination.
    expression = compile_column_formula(source, target)
    unknown = [name for name in expression.variables
               if not re.fullmatch(r"x|y|c[1-9][0-9]*", name)]
    if unknown:
        raise DataValidationError(f"Unknown column symbol(s): {', '.join(unknown)}.")
    assignment = re.match(r"^[A-Za-z][A-Za-z0-9_]*\s*=(?!=)(.*)$", source, re.S)
    if assignment:
        source = assignment[1].strip()
    return {"name": name, "formula": source, "mode": "column_formula",
            "target": target, "axis": target if target in {"x", "y"} else "y"}


def save_equation(directory: Path, value: dict[str, Any]) -> Path:
    equation = normalize_equation(value)
    slug = re.sub(r"[^a-z0-9_-]+", "_", equation["name"].lower()).strip("_")[:64]
    digest = hashlib.sha256(equation["name"].encode("utf-8")).hexdigest()[:16]
    destination = directory / f"{slug or 'equation'}-{digest}{EQUATION_SUFFIX}"
    payload = {"format": "CurveMole calculator equation", "schema_version": 1,
               "equation": equation}
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".equation-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return destination


def load_equations(directory: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Keep valid entries available when another library file is damaged."""
    equations, failures = [], []
    try:
        sources = sorted(directory.glob(f"*{EQUATION_SUFFIX}"))
    except OSError as exc:
        return [], [f"{directory}: {exc}"]
    for source in sources:
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
            if (not isinstance(payload, dict)
                    or payload.get("format") != "CurveMole calculator equation"
                    or payload.get("schema_version") != 1):
                raise DataValidationError("Unsupported calculator equation file.")
            equations.append(normalize_equation(payload["equation"]))
        except (OSError, ValueError, KeyError, TypeError, CurveMoleError) as exc:
            failures.append(f"{source.name}: {exc}")
    return equations, failures
