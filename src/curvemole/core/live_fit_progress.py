"""Fit defaults and deterministic live-progress notifications.

This compatibility layer keeps the public fitting engine stable while making
interactive fits easier to follow in the desktop client.
"""

from __future__ import annotations

import functools
import threading
from typing import Any

from curvemole.core import fitting

DEFAULT_MAX_EVALUATIONS = 1000
# A fit should not burn through the full budget once successive solver steps are
# numerically negligible. SciPy treats xtol convergence as a successful fit and
# still returns the final Jacobian/covariance inputs, unlike aborting residual()
# with a custom exception.
DEFAULT_XTOL = 1e-8
LIVE_REFRESH_EVERY = 20

_THREAD_STATE = threading.local()
_ORIGINAL_SETTINGS_INIT = fitting.FitSettings.__init__
_ORIGINAL_FITTER_FIT = fitting.Fitter.fit
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


@functools.wraps(_ORIGINAL_FITTER_FIT)
def _fitter_fit(
    self: fitting.Fitter,
    plan: fitting.FitPlan,
    curves: Any,
    models: Any,
    *,
    cancellation: fitting.CancellationToken | None = None,
    progress: fitting.ProgressCallback | None = None,
) -> fitting.FitResult:
    previous = getattr(_THREAD_STATE, "progress", None)
    _THREAD_STATE.progress = progress
    try:
        return _ORIGINAL_FITTER_FIT(
            self,
            plan,
            curves,
            models,
            cancellation=cancellation,
            progress=progress,
        )
    finally:
        _THREAD_STATE.progress = previous


def _problem_init(
    self: fitting._Problem,
    curves: Any,
    models: Any,
    plan: fitting.FitPlan,
    registry: Any,
    cancellation: fitting.CancellationToken,
    progress: fitting.ProgressCallback | None,
) -> None:
    # Independent/sequential fits deliberately pass progress=None to their
    # internal problem. Recover the outer callback from thread-local state so
    # they can still publish live fitting snapshots.
    callback = progress if progress is not None else getattr(_THREAD_STATE, "progress", None)
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


def _residual(self: fitting._Problem, vector: Any) -> Any:
    residual = _ORIGINAL_RESIDUAL(self, vector)
    callback = getattr(self, "_curvemole_live_progress", None)
    if callback is not None and self.evaluations % LIVE_REFRESH_EVERY == 0:
        maximum = max(1, self.plan.settings.max_nfev)
        callback(
            min(self.evaluations / maximum, 0.99),
            f"Evaluation {self.evaluations}",
        )
    return residual


def _install() -> None:
    if getattr(fitting, "_curvemole_live_fit_progress", False):
        return
    fitting.FitSettings.__init__ = _fit_settings_init
    fitting.FitSettings.__dataclass_fields__["max_nfev"].default = DEFAULT_MAX_EVALUATIONS
    fitting.FitSettings.__dataclass_fields__["xtol"].default = DEFAULT_XTOL
    fitting.Fitter.fit = _fitter_fit
    fitting._Problem.__init__ = _problem_init
    fitting._Problem.residual = _residual
    fitting._curvemole_live_fit_progress = True


_install()
