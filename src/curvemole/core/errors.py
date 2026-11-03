"""Typed errors used across every CurveMole access surface."""


class CurveMoleError(Exception):
    """Base class for actionable user-facing failures."""


class DataValidationError(CurveMoleError):
    """Input data or mapping is invalid."""


class ExpressionError(CurveMoleError):
    """A formula or parameter link is invalid or unsafe."""


class ConstraintError(CurveMoleError):
    """Parameter constraints are contradictory or cyclic."""


class FitError(CurveMoleError):
    """A fit cannot start or did not produce a valid result."""


class FitCancelled(FitError):
    """The caller explicitly cancelled a fit."""


class ProjectFormatError(CurveMoleError):
    """A project is malformed, corrupt, or unsupported."""


class ProjectResourceLimitError(ProjectFormatError):
    """Valid-sized archive structures need consent to exceed a load budget."""

    def __init__(self, required_limits: dict[str, int], current_limits: dict[str, int]):
        self.required_limits = required_limits
        self.current_limits = current_limits
        category = "array-size budget" if "array_bytes" in required_limits else "archive resource budget"
        super().__init__(
            f"Project exceeds the {category} (automatic loading thresholds): "
            + "; ".join(
                f"{name}: {value:,}; limit {current_limits[name]:,}"
                for name, value in required_limits.items()
            )
        )


class PluginTrustError(CurveMoleError):
    """Execution of an untrusted Python plugin was prevented."""
