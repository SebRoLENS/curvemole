"""Qt desktop client for the CurveMole scientific engine."""

# Preserve the established BackgroundComponentsDialog injection point used by
# tests/plugins while loading the corrected background-control semantics.
from curvemole.gui import (
    background_controls_compat as _background_controls_compat,  # noqa: F401,E402
)
from curvemole.gui import background_controls_fix as _background_controls_fix  # noqa: F401,E402

# Add plot-focused spectrum keyboard navigation plus background-aware rendering.
from curvemole.gui import background_navigation as _background_navigation  # noqa: F401,E402

# Let import validity follow file contents rather than the filename suffix and
# expose configurable leading-row skipping in the mapping preview.
from curvemole.gui import import_flexibility as _import_flexibility  # noqa: F401,E402

# Ensure multi-file imports follow human/numeric filename order rather than the
# lexical order returned by the platform file dialog.
from curvemole.gui import import_sort_fix as _import_sort_fix  # noqa: F401,E402

# Refresh the plotted model every 20 fit evaluations while preserving the user's
# current zoom/range.
from curvemole.gui import live_fit_refresh as _live_fit_refresh  # noqa: F401,E402

# Wrap manual-point installation so point-created functions update live while
# placing nodes and expose their original points as draggable controls afterwards.
from curvemole.gui import manual_points_live as _manual_points_live  # noqa: F401,E402

# Keep the lightweight masked-data renderer available as the canonical module alias.
from curvemole.gui import mask_display as _mask_display  # noqa: F401,E402

# Install model-panel multi-selection and project-wide function browsing before
# the desktop entry point constructs its MainWindow instance.
from curvemole.gui import model_multiselect as _model_multiselect  # noqa: F401,E402

# Extend the multi-selection model panel with source-to-many parameter copying.
from curvemole.gui import parameter_copy as _parameter_copy  # noqa: F401,E402

# Present parameter copying as a source-first action with an explicit project-wide
# target picker, without changing the established copy/undo engine.
from curvemole.gui import parameter_copy_redesign as _parameter_copy_redesign  # noqa: F401,E402

# Let Function Builder peak parameters carry explicit semantic roles (centre,
# height/area, FWHM/sigma/HWHM) instead of relying on parameter-name guesses.
from curvemole.gui import peak_parameter_roles as _peak_parameter_roles  # noqa: F401,E402

# Keep the pyqtgraph wheel handler enabled while a peak/function is being placed;
# placement itself still owns left-click and left-drag events.
from curvemole.gui import peak_placement_zoom_fix as _peak_placement_zoom_fix  # noqa: F401,E402

# Keep mouse-wheel zoom selected by the user while Quick Fit runs and completes.
from curvemole.gui import quick_fit_zoom_fix as _quick_fit_zoom_fix  # noqa: F401,E402

# Unify Quick Add, automatic peak detection, and Function Builder around the shared
# function registry, with a persistent user-selected function-library directory.
from curvemole.gui import quick_function_library as _quick_function_library  # noqa: F401,E402

# QAction.triggered emits a checked boolean. The Revert background method also has
# an optional curve-id argument, so discard the signal payload explicitly.
from curvemole.gui import (
    revert_background_action_fix as _revert_background_action_fix,  # noqa: F401,E402
)

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

# Add per-spectrum numeric export for data, fitted components, total fit, background,
# and residuals while preserving the original source extension.
from curvemole.gui import spectrum_export_ui as _spectrum_export_ui  # noqa: F401,E402

# Replace the implicit QUndoStack action with an explicit, directly tested action
# and make background Undo visibly restore the original spectrum even if the
# visual-only background preview was left enabled.
from curvemole.gui import undo_action_fix as _undo_action_fix  # noqa: F401,E402

# Harden the frozen Windows self-updater. PyInstaller onefile keeps a bootloader
# process alive briefly after the Python process exits, so replacement must wait
# for the executable itself to be fully released before moving/removing files.
from curvemole.gui import windows_update_fix as _windows_update_fix  # noqa: F401,E402

# Keep the Windows updater compatible with Windows PowerShell installations where
# the Get-FileHash cmdlet is unavailable by using .NET SHA-256 primitives instead.
from curvemole.gui import (  # noqa: F401,E402
    windows_update_powershell_compat as _windows_update_powershell_compat,
)
