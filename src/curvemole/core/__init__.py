"""GUI-independent scientific engine."""

from curvemole.core.data import Curve, Dataset, Mask, Series, Transformation
from curvemole.core.fitting import FitPlan, FitResult, FitSettings, Fitter
from curvemole.core.models import Component, Model
from curvemole.core.parameters import Parameter
from curvemole.core.project import Project
from curvemole.core.sequential_fit import SequentialFitPlan

# Keep the standard fit budget modest and emit deterministic progress snapshots
# every 20 model evaluations for interactive clients.
from curvemole.core import live_fit_progress as _live_fit_progress  # noqa: F401,E402

__all__ = [
    "Component",
    "Curve",
    "Dataset",
    "FitPlan",
    "FitResult",
    "FitSettings",
    "Fitter",
    "Mask",
    "Model",
    "Parameter",
    "Project",
    "SequentialFitPlan",
    "Series",
    "Transformation",
]
