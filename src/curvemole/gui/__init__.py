"""Qt desktop client for the CurveMole scientific engine."""

# Install lightweight masked-data rendering before the main window imports PlotWorkspace.
from curvemole.gui import mask_display as _mask_display  # noqa: F401,E402

# Install model-panel multi-selection and project-wide function browsing before
# the desktop entry point constructs its MainWindow instance.
from curvemole.gui import model_multiselect as _model_multiselect  # noqa: F401,E402

# Extend the multi-selection model panel with source-to-many parameter copying.
from curvemole.gui import parameter_copy as _parameter_copy  # noqa: F401,E402

# Add propagating sequential-fit controls plus pause/resume state that survives
# manual intervention on a suspicious spectrum.
from curvemole.gui import sequential_fit_ui as _sequential_fit_ui  # noqa: F401,E402

# Keep a persistent, directly visible Continue button in the status bar while a
# sequential fit is paused for manual intervention.
from curvemole.gui import sequential_resume_button as _sequential_resume_button  # noqa: F401,E402
