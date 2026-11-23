"""Community example: an additive tab-separated spectrum exporter."""
import numpy as np


def export_tsv(context):
    curve = context.project.dataset.curve(context.active_curve_id)
    np.savetxt(context.path, np.column_stack([curve.x, curve.y]), delimiter="\t",
               header="x\ty", comments="")
    return f"Exported {curve.name} to {context.path}"


def register(api):
    api.add("exporters", "tsv", "TSV spectrum (community)", export_tsv)
