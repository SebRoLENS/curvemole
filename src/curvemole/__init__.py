"""Public CurveMole API.

The package root intentionally exposes only stable, GUI-independent objects.
"""

from importlib import import_module

from curvemole.version import __version__

# File managers can start one process per selected file. A forwarding process
# must reach the existing desktop without loading NumPy, solvers or GUI patches.
_PUBLIC_MODULES = {
    **dict.fromkeys(("Curve", "Dataset", "Mask", "Series", "Transformation"), "data"),
    **dict.fromkeys(("FitPlan", "FitResult", "FitSettings", "Fitter"), "fitting"),
    **dict.fromkeys(("Component", "Model"), "models"),
    "Parameter": "parameters",
    "Project": "project",
    "FunctionRegistry": "registry",
    "default_registry": "registry",
}


def __getattr__(name: str):
    if name == "core":
        value = import_module("curvemole.core")
    elif name in _PUBLIC_MODULES:
        value = getattr(import_module("curvemole.core." + _PUBLIC_MODULES[name]), name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))

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
