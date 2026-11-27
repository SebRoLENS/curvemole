"""Compatibility alias: Quick Fit view preservation lives in ``gui.fit_controller``."""
from curvemole.gui.fit_controller import (  # noqa: F401
    _ensure_wheel_filter,
    _prepare_interactive_quick_fit_view,
    _QuickFitWheelZoomFilter,
)
