"""Public fit progress cadence (implemented directly by the fitter)."""

LIVE_REFRESH_EVERY = 20
# Minimum wall-clock interval between live plot previews in the GUI. Each
# preview redraws the plot on the GUI thread and competes with the fit for the GIL.
LIVE_PREVIEW_SECONDS = 0.15
