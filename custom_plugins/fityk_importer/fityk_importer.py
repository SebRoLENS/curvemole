"""Read Fityk saved-state .fit files as data, without executing their commands."""

from __future__ import annotations

import ast
import math
import re
import shlex
from pathlib import Path

import numpy as np

from curvemole.core.data import Curve, Series
from curvemole.core.models import Component

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_POINT = re.compile(
    rf"X\[(\d+)\]\s*=\s*({_NUMBER})\s*,\s*Y\[\1\]\s*=\s*({_NUMBER})"
    rf"\s*,\s*S\[\1\]\s*=\s*({_NUMBER})\s*,\s*A\[\1\]\s*=\s*([01])\s*$",
    re.I,
)
_FUNC = re.compile(r"^%([\w]+)\s*=\s*([A-Za-z]\w*)\((.*)\)$")
_VAR = re.compile(r"^\$([\w]+)\s*=\s*(.+)$")
_MODEL = re.compile(r"^(?:@(\d+)\s*:\s*)?F\s*(\+?=)\s*(.*)$")
_TITLE = re.compile(r"^(?:@(\d+)\s*:\s*)?title\s*=\s*['\"](.*?)['\"]$")


def _split_arguments(value):
    parts, start, depth = [], 0, 0
    for index, char in enumerate(value):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    return parts


def _numeric(expr, variables, seen=frozenset()):
    """Evaluate only arithmetic and named numeric variables; never execute Python."""
    expr = expr.strip()
    expr = re.sub(r"\[\s*[^]]*\s*\]$", "", expr)  # Fityk free-variable domain
    expr = expr.strip("{}").lstrip("~").replace("^", "**")
    expr = re.sub(r"\$([A-Za-z_]\w*)", r"\1", expr)
    operators = {
        ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
        ast.Pow: lambda a, b: a ** b,
    }

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (float, int):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id == "pi":
                return math.pi
            if node.id == "ln2":
                return math.log(2)
            if node.id in seen or node.id not in variables:
                raise ValueError("Unresolved Fityk variable: " + node.id)
            return _numeric(variables[node.id], variables, seen | {node.id})
        if isinstance(node, ast.UnaryOp) and type(node.op) in (ast.UAdd, ast.USub):
            v = visit(node.operand)
            return v if isinstance(node.op, ast.UAdd) else -v
        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            return operators[type(node.op)](visit(node.left), visit(node.right))
        raise ValueError("Unsupported Fityk expression")

    result = float(visit(ast.parse(expr, mode="eval")))
    if not math.isfinite(result):
        raise ValueError("Nonfinite Fityk parameter")
    return result


def _model_component(name, definition, variables):
    kind, arguments = definition
    names = {
        "Gaussian": ("height", "center", "hwhm"),
        "Lorentzian": ("height", "center", "hwhm"),
        "PseudoVoigt": ("height", "center", "hwhm", "shape"),
        "Constant": ("height",),
        "Linear": ("intercept", "slope"),
    }.get(kind)
    if names is None:
        raise ValueError("Unsupported function " + kind)
    args = _split_arguments(arguments)
    supplied = {}
    aliases = {"a": "height", "a0": "intercept", "a1": "slope"}
    for index, arg in enumerate(args):
        if "=" in arg:
            key, expr = arg.split("=", 1)
            supplied[aliases.get(key.strip(), key.strip())] = expr.strip()
        elif index < len(names):
            supplied[names[index]] = arg
    if kind == "PseudoVoigt":
        supplied.setdefault("shape", "0.5")
    values = {key: _numeric(supplied[key], variables) for key in names}
    h = values.get("height", 0.0)
    width = values.get("hwhm", 0.0)
    if kind in ("Gaussian", "Lorentzian", "PseudoVoigt") and width <= 0:
        raise ValueError("Peak width must be positive")
    if kind == "Gaussian":
        fid = "gaussian"
        initial = {"area": h * width * math.sqrt(math.pi / math.log(2)),
                   "center": values["center"], "sigma": width / math.sqrt(2 * math.log(2))}
    elif kind == "Lorentzian":
        fid = "lorentzian"
        initial = {"area": h * math.pi * width, "center": values["center"], "gamma": width}
    elif kind == "PseudoVoigt":
        shape = values["shape"]
        if not 0 <= shape <= 1:
            raise ValueError("PseudoVoigt shape must be within [0, 1]")
        ga = (1 - shape) * math.sqrt(math.pi / math.log(2))
        lo = shape * math.pi
        fid = "pseudo_voigt"
        initial = {"area": h * width * (ga + lo), "center": values["center"],
                   "fwhm": 2 * width, "eta": lo / (ga + lo)}
    elif kind == "Constant":
        fid, initial = "constant", {"offset": h}
    else:
        fid, initial = "linear", values
    component = Component.create(fid, name=name, initial=initial)
    component.metadata["fityk"] = {"function": kind, "arguments": arguments}
    # A literal number is fixed in Fityk; ~number is adjustable. A reference
    # to a shared/derived variable is retained as provenance, not a live link.
    if kind == "Constant":
        source = {"offset": supplied["height"]}
    elif kind == "Linear":
        source = {"intercept": supplied["intercept"], "slope": supplied["slope"]}
    else:
        source = {"center": supplied["center"]}
        source[{"Gaussian": "sigma", "Lorentzian": "gamma",
                "PseudoVoigt": "fwhm"}[kind]] = supplied["hwhm"]
    for target, expr in source.items():
        if re.fullmatch(_NUMBER, expr.strip()):
            component.parameters[target].fixed = True
        elif expr.startswith("$"):
            variable = variables.get(expr[1:])
            if variable is not None and not variable.strip().startswith("~"):
                component.parameters[target].fixed = True
        variable = variables.get(expr.strip().lstrip("$")) if expr.strip().startswith("$") else expr
        domain = re.search(r"\[\s*([^]:]*)\s*:\s*([^]]*)\s*\]$", variable or "")
        if domain and target in ("center", "sigma", "gamma", "fwhm"):
            factor = (1 / math.sqrt(2 * math.log(2)) if target == "sigma" else
                      2 if target == "fwhm" else 1)
            lower = _numeric(domain[1], variables) * factor if domain[1].strip() else -math.inf
            upper = _numeric(domain[2], variables) * factor if domain[2].strip() else math.inf
            parameter = component.parameters[target]
            parameter.minimum = max(parameter.minimum, lower)
            parameter.maximum = min(parameter.maximum, upper)
            parameter.validate()
    if kind in ("Gaussian", "Lorentzian", "PseudoVoigt"):
        height_expr = supplied["height"].strip()
        width_expr = supplied["hwhm"].strip()
        def fixed(expr):
            if expr.startswith("$"):
                expr = variables.get(expr[1:], "").strip()
            return bool(expr) and not expr.startswith("~")
        component.parameters["area"].fixed = fixed(height_expr) and fixed(width_expr)
        if kind == "PseudoVoigt":
            component.parameters["eta"].fixed = fixed(supplied["shape"])
    return component


def _load_external(spec, directory):
    """Simple text X/Y(/sigma) references; complex xylib formats need Fityk."""
    words = shlex.split(spec)
    if not words:
        raise ValueError("Missing data path")
    fields = words[0].split(":")
    file_name = fields[0].replace("_SCRIPT_DIR_", str(directory))
    source = Path(file_name)
    if not source.is_absolute():
        source = directory / source
    xcol = int(fields[1]) if len(fields) > 1 and fields[1] else 1
    ycol = int(fields[2]) if len(fields) > 2 and fields[2] else 2
    scol = int(fields[3]) if len(fields) > 3 and fields[3] else None
    if any(v < 0 for v in (xcol, ycol, scol or 0)):
        raise ValueError("Negative data column")
    data = np.loadtxt(source, delimiter="," if source.suffix.lower() == ".csv" else None,
                      comments="#", ndmin=2)
    if data.shape[0] < 2:
        raise ValueError("At least two points are required")
    def col(n):
        return np.arange(len(data), dtype=float) if n == 0 else data[:, n - 1]
    return col(xcol), col(ycol), None if scol is None else col(scol)


def parse_project(path):
    path = Path(path)
    if path.suffix.lower() not in (".fit", ".gz"):
        raise ValueError("Choose a Fityk .fit project")
    if path.suffix.lower() == ".gz":
        import gzip
        with gzip.open(path, "rt", encoding="utf-8-sig") as stream:
            source = stream.read()
    else:
        source = path.read_text(encoding="utf-8-sig")
    if not re.match(r"\s*#\s*Fityk\b", source, re.I):
        raise ValueError("This is not a Fityk project (.fit saved state or script)")
    datasets = {}
    definitions, variables, models, warnings = {}, {}, {}, []
    current = 0
    datasets[0] = {"points": {}, "title": "Dataset 0", "external": None}
    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Strip inline comments outside quoted strings (Fityk state output).
        line = line.split("#", 1)[0].strip()
        if line.startswith("@+ ="):
            current = max(datasets) + 1
            datasets[current] = {"points": {}, "title": f"Dataset {current}", "external": None}
            continue
        use = re.fullmatch(r"use\s+@(\d+)", line)
        if use:
            current = int(use[1])
            datasets.setdefault(current, {"points": {}, "title": f"Dataset {current}", "external": None})
            continue
        title = _TITLE.fullmatch(line)
        if title:
            idx = int(title[1]) if title[1] else current
            datasets.setdefault(idx, {"points": {}, "title": f"Dataset {idx}", "external": None})["title"] = title[2]
            continue
        point = _POINT.fullmatch(line)
        if point:
            datasets[current]["points"][int(point[1])] = (
                float(point[2]), float(point[3]), float(point[4]), point[5] == "1")
            continue
        external = re.match(r"^@(\d+)\s*<\s*(.*)$", line)
        if external:
            idx = int(external[1])
            datasets.setdefault(idx, {"points": {}, "title": f"Dataset {idx}", "external": None})["external"] = external[2]
            continue
        variable = _VAR.fullmatch(line)
        if variable:
            variables[variable[1]] = variable[2]
            continue
        function = _FUNC.fullmatch(line)
        if function:
            definitions[function[1]] = (function[2], function[3])
            continue
        model = _MODEL.fullmatch(line)
        if model:
            idx = int(model[1]) if model[1] else current
            names = re.findall(r"%([A-Za-z_]\w*)", model[3])
            if not names and model[3].strip() not in ("0", ""):
                warnings.append(f"@{idx}: inline model functions were not imported")
            models[idx] = models.get(idx, []) + names if model[2] == "+=" else names
            continue
        if re.fullmatch(r"X\s*=\s*" + _NUMBER, line):
            continue  # saved-state sorting hint, not an axis transformation
        if re.match(r"^(?:@\d+\s*:\s*)?(?:[XYASZ]\s*=|Z\s*\+?=)", line):
            warnings.append(f"Transformation or zero-shift was not applied: {line[:70]}")
    prepared = []
    for idx, data in sorted(datasets.items()):
        points = data["points"]
        if points:
            if list(sorted(points)) != list(range(len(points))):
                raise ValueError(f"Dataset @{idx} has missing point indices")
            array = np.asarray([points[i][:3] for i in sorted(points)], dtype=float)
            x, y, sigma = array.T
            active = np.asarray([points[i][3] for i in sorted(points)], dtype=bool)
            sigma = sigma if np.all(np.isfinite(sigma) & (sigma > 0)) else None
        elif data["external"]:
            try:
                x, y, sigma = _load_external(data["external"], path.parent)
            except (OSError, ValueError, IndexError) as exc:
                warnings.append(f"@{idx}: data file unavailable or unsupported ({exc})")
                continue
            active = np.ones(len(x), dtype=bool)
        else:
            continue
        if len(x) < 2:
            warnings.append(f"@{idx}: fewer than two points")
            continue
        curve = Curve(data["title"], x, y, sigma_y=sigma, source=str(path),
                      metadata={"fityk_dataset": idx})
        curve.masks[curve.active_mask].excluded[:] = ~active
        components = []
        for name in models.get(idx, []):
            try:
                components.append(_model_component(name, definitions[name], variables))
            except (KeyError, ValueError, ArithmeticError, SyntaxError) as exc:
                warnings.append(f"@{idx} %{name}: {exc}")
        prepared.append((curve, components))
    if not prepared:
        raise ValueError("No readable Fityk spectra found. " + "; ".join(warnings[:3]))
    return prepared, warnings


def import_fityk(context):
    prepared, warnings = parse_project(context.path)
    series = Series(f"Fityk: {Path(context.path).stem}")
    context.project.add_series(series)
    for curve, components in prepared:
        context.project.add_curve(curve, series)
        for component in components:
            context.project.add_component(curve.id, component)
    context.data["last_import"] = {
        "path": str(context.path), "spectra": len(prepared),
        "components": sum(len(parts) for _, parts in prepared), "warnings": warnings,
    }
    return (f"Imported {len(prepared)} Fityk spectra; "
            f"{sum(len(parts) for _, parts in prepared)} components. "
            + ("Skipped: " + "; ".join(warnings[:12]) if warnings else ""))


def register(api):
    api.add("importers", "fityk", "Fityk project (.fit)", import_fityk,
            description="Spectra, active masks and supported peak/background models")
