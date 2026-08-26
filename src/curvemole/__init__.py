"""Public CurveMole API.

The package root intentionally exposes only stable, GUI-independent objects.
"""

from curvemole.core.data import Curve, Dataset, Mask, Series, Transformation
from curvemole.core.fitting import FitPlan, FitResult, FitSettings, Fitter
from curvemole.core.models import Component, Model
from curvemole.core.parameters import Parameter
from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry, default_registry
from curvemole.version import __version__

__all__ = [
    "Component",
    "Curve",
    "Dataset",
    "FitPlan",
    "FitResult",
    "FitSettings",
    "Fitter",
    "FunctionRegistry",
    "Mask",
    "Model",
    "Parameter",
    "Project",
    "Series",
    "Transformation",
    "__version__",
    "default_registry",
]
