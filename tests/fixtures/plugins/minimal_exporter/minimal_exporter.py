"""Test fixture: a minimal additive exporter owned by CurveMole's own test suite.

Source tests use this folder instead of a community plugin, so community
submissions never affect them and plugin-only pull requests can skip them.
"""
import numpy as np


def export_xy(context):
    curve = context.project.dataset.curve(context.active_curve_id)
    np.savetxt(context.path, np.column_stack([curve.x, curve.y]), delimiter="\t",
               header="x\ty", comments="")
    return f"Exported {curve.name}"


def register(api):
    api.add("exporters", "xy", "Minimal x/y export (test fixture)", export_xy)
