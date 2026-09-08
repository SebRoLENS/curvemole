"""Fit defaults and deterministic live-progress notifications.

This compatibility layer keeps the public fitting engine stable while making
interactive fits easier to follow in the desktop client.
"""

from __future__ import annotations

import functools
from typing import Any

from curvemole.core import fitting

DEFAULT_MAX_EVALUATIONS = 1000
# A fit should not burn through the full budget once successive solver steps are
# numerically negligible. SciPy treats xtol convergence as a successful fit and
# still returns the final Jacobian/covariance inputs, unlike aborting residual()
# with a custom exception.
DEFAULT_XTOL = 1e-8
LIVE_REFRESH_EVERY = 20

_ORIGINAL_SETTINGS_INIT = fitting.FitSettings.__init__
_ORIGINAL_PROBLEM_INIT = fitting._Problem.__init__
_ORIGINAL_RESIDUAL = fitting._Problem.residual


@functools.wraps(_ORIGINAL_SETTINGS_INIT)
def _fit_settings_init(self: fitting.FitSettings, *args: Any, **kwargs: Any) -> None:
    # max_nfev is the fifth dataclass field and xtol is the seventh. Preserve
    # explicit positional or keyword choices while changing only new-plan defaults.
    if len(args) < 5 and "max_nfev" not in kwargs:
        kwargs["max_nfev"] = DEFAULT_MAX_EVALUATIONS
    if len(args) < 7 and "xtol" not in kwargs:
        kwargs["xtol"] = DEFAULT_XTOL
    _ORIGINAL_SETTINGS_INIT(self, *args, **kwargs)


def _problem_init(
    self: fitting._Problem,
    curves: Any,
    models: Any,
    plan: fitting.FitPlan,
    registry: Any,
    cancellation: fitting.CancellationToken,
    progress: fitting.ProgressCallback | None,
) -> None:
    # Batch workflows supply a callback scaled to their total budget. Never
    # recover an unscaled outer callback for an internal problem.
    callback = progress
    _ORIGINAL_PROBLEM_INIT(
        self,
        curves,
        models,
        plan,
        registry,
        cancellation,
        None,
    )
    self._curvemole_live_progress = callback


def _residual(self: fitting._Problem, vector: Any, *, report: bool = True) -> Any:
    residual = _ORIGINAL_RESIDUAL(self, vector, report=report)
    callback = getattr(self, "_curvemole_live_progress", None)
    if report and callback is not None and (
        self.evaluations % LIVE_REFRESH_EVERY == 0
        or self.evaluations == self.plan.settings.max_nfev
    ):
        maximum = max(1, self.plan.settings.max_nfev)
        callback(
            min(self.evaluations / maximum, 1.0),
            f"Evaluation {self.evaluations}",
        )
    return residual


def _install() -> None:
    if getattr(fitting, "_curvemole_live_fit_progress", False):
        return
    fitting.FitSettings.__init__ = _fit_settings_init
    fitting.FitSettings.__dataclass_fields__["max_nfev"].default = DEFAULT_MAX_EVALUATIONS
    fitting.FitSettings.__dataclass_fields__["xtol"].default = DEFAULT_XTOL
    fitting._Problem.__init__ = _problem_init
    fitting._Problem.residual = _residual
    fitting._curvemole_live_fit_progress = True


_install()
