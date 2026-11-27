"""Named keys and a typed view of ``Project.results``.

``Project.results`` stays a plain mapping, because that is its on-disk format
(project archives store it as JSON plus arrays). Code should not spell its keys
as string literals: use the :class:`ResultKey` constants, or the typed accessors
of :class:`ResultsStore` (``project.results_store``).

Per-curve maps (``RESULT_MAPS``) are ``{curve_id: value}``; the uncertainty
maps are ``{curve_id: {method: value}}``.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


class ResultKey:
    LAST_FIT = "last_fit"
    LAST_ATTEMPT = "last_attempt"
    FIT_BY_CURVE = "fit_by_curve"
    GLOBAL_FIT_BASELINES = "global_fit_baselines"
    UNCERTAINTY_BY_CURVE = "uncertainty_by_curve"
    UNCERTAINTY_REPORTS_BY_CURVE = "uncertainty_reports_by_curve"
    UNCERTAINTY_FAILURES_BY_CURVE = "uncertainty_failures_by_curve"
    UNCERTAINTY_DISPLAY_METHOD = "uncertainty_display_method"
    LAST_SEQUENTIAL_PAUSE_MESSAGE = "last_sequential_pause_message"
    # Project-wide maps from before per-curve reports; still written for older readers.
    LEGACY_UNCERTAINTY_REPORTS = "uncertainty_reports"
    LEGACY_UNCERTAINTY = "uncertainty"
    LEGACY_UNCERTAINTY_DISPLAY_METHOD_BY_CURVE = "uncertainty_display_method_by_curve"


RESULT_MAPS = frozenset({
    ResultKey.FIT_BY_CURVE,
    ResultKey.UNCERTAINTY_BY_CURVE,
    ResultKey.UNCERTAINTY_REPORTS_BY_CURVE,
    ResultKey.GLOBAL_FIT_BASELINES,
    ResultKey.UNCERTAINTY_FAILURES_BY_CURVE,
})
METHOD_MAPS = frozenset({
    ResultKey.UNCERTAINTY_BY_CURVE,
    ResultKey.UNCERTAINTY_REPORTS_BY_CURVE,
    ResultKey.UNCERTAINTY_FAILURES_BY_CURVE,
})


class ResultsStore:
    """Typed accessors over a project's ``results`` mapping (no copy is made)."""

    __slots__ = ("results",)

    def __init__(self, results: MutableMapping[str, Any]) -> None:
        self.results = results

    def _map(self, key: str) -> dict[str, Any]:
        value = self.results.get(key)
        if not isinstance(value, dict):
            value = self.results[key] = {}
        return value

    @property
    def last_fit(self) -> Any:
        return self.results.get(ResultKey.LAST_FIT)

    @last_fit.setter
    def last_fit(self, value: Any) -> None:
        self.results[ResultKey.LAST_FIT] = value

    @property
    def fit_by_curve(self) -> dict[str, Any]:
        return self._map(ResultKey.FIT_BY_CURVE)

    @property
    def global_fit_baselines(self) -> dict[str, Any]:
        return self._map(ResultKey.GLOBAL_FIT_BASELINES)

    @property
    def uncertainty_by_curve(self) -> dict[str, dict[str, Any]]:
        return self._map(ResultKey.UNCERTAINTY_BY_CURVE)

    @property
    def uncertainty_reports_by_curve(self) -> dict[str, dict[str, Any]]:
        return self._map(ResultKey.UNCERTAINTY_REPORTS_BY_CURVE)

    @property
    def uncertainty_failures_by_curve(self) -> dict[str, dict[str, Any]]:
        return self._map(ResultKey.UNCERTAINTY_FAILURES_BY_CURVE)

    @property
    def uncertainty_display_method(self) -> str | None:
        return self.results.get(ResultKey.UNCERTAINTY_DISPLAY_METHOD)

    @uncertainty_display_method.setter
    def uncertainty_display_method(self, value: str | None) -> None:
        self.results[ResultKey.UNCERTAINTY_DISPLAY_METHOD] = value

    def uncertainty_report(self, curve_id: str, method: str) -> Any:
        return self.results.get(ResultKey.UNCERTAINTY_REPORTS_BY_CURVE, {}).get(curve_id, {}).get(method)
