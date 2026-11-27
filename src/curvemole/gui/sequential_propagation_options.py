"""Compatibility alias: the propagation options are built by ``gui.sequential_plan_controls``.

FitPlanDialog creates them itself; this module no longer patches the dialog.
"""
from curvemole.gui.sequential_plan_controls import (  # noqa: F401
    _ignored_component_ids,
    _refresh_ignored_functions,
    _save_settings,
)
