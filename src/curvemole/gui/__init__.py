"""Qt desktop client for the CurveMole scientific engine."""

# Install lightweight masked-data rendering before the main window imports PlotWorkspace.
from curvemole.gui import mask_display as _mask_display  # noqa: F401,E402
