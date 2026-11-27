"""Compatibility alias: sequential controls live in ``gui.sequential_plan_controls``
(Fit dialog) and ``gui.fit_controller`` (pause/resume); nothing is patched here."""
from curvemole.gui.fit_controller import resume_sequence  # noqa: F401
from curvemole.gui.sequential_plan_controls import _checked_curve_ids  # noqa: F401
