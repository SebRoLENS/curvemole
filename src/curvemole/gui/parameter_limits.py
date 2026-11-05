"""Readable presentation of built-in peak-width positivity bounds."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt

POSITIVE_BOUND_ROLE = int(Qt.ItemDataRole.UserRole) + 1
_NUMERICAL_FLOORS = {sys.float_info.min, sys.float_info.epsilon}
_WIDTH_PARAMETERS = {
    "gaussian": {"sigma"},
    "lorentzian": {"gamma"},
    "voigt": {"sigma", "gamma"},
    "pseudo_voigt": {"fwhm"},
}


def positive_width_bound(registry, component, parameter) -> tuple[float | None, bool]:
    """Recognise only built-in numerical floors, never round arbitrary bounds.

    Older projects used the smallest normal float; current definitions use
    machine epsilon. Both mean 'strictly positive' in the parameter table.
    Return the existing floor for an unchanged edit, without migrating projects.
    """
    if parameter.name not in _WIDTH_PARAMETERS.get(component.function_id, ()):
        return None, False
    if component.function_id not in registry.identifiers():
        return None, False
    definition = registry.get(component.function_id)
    spec = next((spec for spec in definition.specs(component.metadata)
                 if spec.name == parameter.name), None)
    if spec is None or spec.minimum not in _NUMERICAL_FLOORS:
        return None, False
    show_zero = parameter.minimum in _NUMERICAL_FLOORS
    floor = parameter.minimum if show_zero else spec.minimum
    return floor, show_zero
