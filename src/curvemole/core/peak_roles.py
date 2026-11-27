"""Explicit semantic roles for the parameters of user-defined peak functions.

A custom peak function may declare which parameter is its centre, height or
area, and which describes its width (FWHM, Gaussian sigma or HWHM). Automatic
peak suggestions and graphical placement then initialise it without guessing
from parameter names. The roles travel with the function definition
(``custom_metadata["peak_roles"]``) in function files, projects and workflows,
so the desktop application, the CLI, the Python API and YAML workflows all
initialise such functions identically.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

ROLE_CHOICES = (
    ("", "Not specified"),
    ("center", "Peak position / centre"),
    ("height", "Peak height"),
    ("area", "Peak area / integral"),
    ("fwhm", "FWHM (full width at half maximum)"),
    ("sigma", "Gaussian sigma (standard deviation)"),
    ("hwhm", "HWHM / gamma (half width at half maximum)"),
)
ALLOWED_ROLES = frozenset(identifier for identifier, _ in ROLE_CHOICES if identifier)
_FWHM_PER_SIGMA = 2.354820045


def sanitise_roles(value: Any, parameter_names: set[str] | None = None) -> dict[str, str]:
    """Keep only known roles for existing parameters."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for raw_name, raw_role in value.items():
        name, role = str(raw_name), str(raw_role)
        if role not in ALLOWED_ROLES:
            continue
        if parameter_names is not None and name not in parameter_names:
            continue
        result[name] = role
    return result


def attach_roles(definition: Any, roles: Any) -> Any:
    """Store sanitised roles on a peak definition (other kinds ignore them)."""
    if roles is None or getattr(definition, "kind", None) != "peak":
        return definition
    names = {spec.name for spec in definition.specs({})}
    definition.custom_metadata["peak_roles"] = sanitise_roles(roles, names)
    return definition


def has_roles(definition: Any) -> bool:
    return getattr(definition, "kind", None) == "peak" and "peak_roles" in definition.custom_metadata


def _set(component: Any, name: str | None, value: float) -> None:
    if name is None or name not in component.parameters:
        return
    parameter = component.parameters[name]
    parameter.value = min(max(float(value), parameter.minimum), parameter.maximum)


def initialise_from_roles(component: Any, suggestion: Any, definition: Any) -> Any:
    """Initialise a peak component from a suggestion using its declared roles."""
    roles = sanitise_roles(definition.custom_metadata.get("peak_roles"), set(component.parameters))
    by_role = {role: name for name, role in roles.items()}
    _set(component, by_role.get("center"), suggestion.x)
    _set(component, by_role.get("fwhm"), suggestion.fwhm)
    _set(component, by_role.get("sigma"), suggestion.fwhm / _FWHM_PER_SIGMA)
    _set(component, by_role.get("hwhm"), suggestion.fwhm / 2)
    height_name, area_name = by_role.get("height"), by_role.get("area")
    if height_name is not None:
        _set(component, height_name, suggestion.height)
    elif area_name is not None:
        area = component.parameters[area_name]
        unit_scale = min(max(1.0, area.minimum), area.maximum)
        area.value = unit_scale
        values = {name: parameter.value for name, parameter in component.parameters.items()}
        unit_height = float(
            definition.evaluate(np.asarray([suggestion.x], dtype=float), values, component.metadata)[0])
        if math.isfinite(unit_height) and unit_height != 0:
            _set(component, area_name, suggestion.height / unit_height * unit_scale)
    for parameter in component.parameters.values():
        parameter.validate()
    return component
