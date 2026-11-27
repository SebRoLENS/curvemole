"""Public fit progress cadence and defaults (implemented directly by the fitter)."""

DEFAULT_MAX_EVALUATIONS = 1000
DEFAULT_XTOL = 1e-8
LIVE_REFRESH_EVERY = 20
# Minimum wall-clock interval between live plot previews in the GUI. Each
# preview redraws the plot on the GUI thread and competes with the fit for the GIL.
LIVE_PREVIEW_SECONDS = 0.15
