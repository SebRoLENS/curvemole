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


class PluginTrustError(CurveMoleError):
    """Execution of an untrusted Python plugin was prevented."""
