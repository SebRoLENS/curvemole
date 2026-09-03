"""Qt desktop client for the CurveMole scientific engine."""

# Preserve the established BackgroundComponentsDialog injection point used by
# tests/plugins while loading the corrected background-control semantics.
from curvemole.gui import (
    background_controls_compat as _background_controls_compat,  # noqa: F401,E402
)
from curvemole.gui import background_controls_fix as _background_controls_fix  # noqa: F401,E402

# Add plot-focused spectrum keyboard navigation plus background-aware rendering.
from curvemole.gui import background_navigation as _background_navigation  # noqa: F401,E402

# Keep the lightweight masked-data renderer available as the canonical module alias.
from curvemole.gui import mask_display as _mask_display  # noqa: F401,E402

# Install model-panel multi-selection and project-wide function browsing before
# the desktop entry point constructs its MainWindow instance.
from curvemole.gui import model_multiselect as _model_multiselect  # noqa: F401,E402

# Extend the multi-selection model panel with source-to-many parameter copying.
from curvemole.gui import parameter_copy as _parameter_copy  # noqa: F401,E402

# Add propagating sequential-fit controls plus pause/resume state that survives
# manual intervention on a suspicious spectrum.
from curvemole.gui import sequential_fit_ui as _sequential_fit_ui  # noqa: F401,E402

# Add configurable source-model propagation and allow selected functions to be
# ignored by the parameter-change pause trigger.
from curvemole.gui import (
    sequential_propagation_options as _sequential_propagation_options,  # noqa: F401,E402
)

# Keep a persistent, directly visible Continue button in the status bar while a
# sequential fit is paused for manual intervention.
from curvemole.gui import sequential_resume_button as _sequential_resume_button  # noqa: F401,E402
