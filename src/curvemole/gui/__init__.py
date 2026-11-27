"""Qt desktop client for the CurveMole scientific engine.

The modules below extend MainWindow, PlotWorkspace and the panels when they are
imported. Their ORDER IS SIGNIFICANT: several wrap a method that an earlier one
installed (for example sequential_propagation_options wraps a FitPlanDialog
method added by sequential_fit_ui). The list is therefore kept in this explicit
order rather than sorted automatically; append new extensions at the end and
see tests/test_gui_composition.py.
"""
# isort: skip_file

# Apply Autoscale after mouse-driven data navigation once Qt has finished the
# current selection/current-item event sequence.
from curvemole.gui import (
    autoscale_mouse_navigation as _autoscale_mouse_navigation,  # noqa: F401,E402
)


# Add plot-focused spectrum keyboard navigation plus background-aware rendering.
from curvemole.gui import background_navigation as _background_navigation  # noqa: F401,E402

# Add explicit generic-data renaming and safe, undoable series deletion without
# assuming that imported one-dimensional data are spectra.
from curvemole.gui import data_series_management as _data_series_management  # noqa: F401,E402

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

# Keep an already-open laboratory notebook synchronised when descriptions are
# added or edited from the main data/model context menus.
from curvemole.gui import notebook_live_refresh as _notebook_live_refresh  # noqa: F401,E402

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

# Make the compact plot-style selector control imported data and keep offsets /
# residual visibility grouped with the display controls requested by the user.
from curvemole.gui import plot_controls_fix as _plot_controls_fix  # noqa: F401,E402

# Keep mouse-wheel zoom selected by the user while Quick Fit runs and completes.
from curvemole.gui import quick_fit_zoom_fix as _quick_fit_zoom_fix  # noqa: F401,E402

# Unify Quick Add, automatic peak detection, and Function Builder around the shared
# function registry, with a persistent user-selected function-library directory.
from curvemole.gui import quick_function_library as _quick_function_library  # noqa: F401,E402


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

# Provide scope-aware, non-mutating spectrum display options after toolbar setup.
from curvemole.gui import view_options as _view_options  # noqa: F401,E402

# Harden the frozen Windows self-updater. PyInstaller onefile keeps a bootloader
# process alive briefly after the Python process exits, so replacement must wait
# for the executable itself to be fully released before moving/removing files.
from curvemole.gui import updates_windows as _updates_windows  # noqa: F401,E402

# Keep the Windows updater compatible with Windows PowerShell installations where
# the Get-FileHash cmdlet is unavailable by using .NET SHA-256 primitives instead.
from curvemole.gui import (  # noqa: F401,E402
    windows_update_powershell_compat as _windows_update_powershell_compat,
)

# The application module installs further PlotWorkspace behaviour (view-preserving
# refresh, continuous peak placement, manual points). Import it here so every
# MainWindow, including those built by tests and plugins, has the same behaviour
# as the desktop application, whether or not gui.app was imported explicitly.
from curvemole.gui import app as _app  # noqa: F401,E402
