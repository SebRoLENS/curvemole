# Changelog

All notable changes follow Keep a Changelog and Semantic Versioning.

## [Unreleased]

### Fixed

- Keep three autosave copies per project and remove them on Save or explicit Discard.
- Offer grouped recoverable sessions at desktop startup and from the File menu,
  with Recover, Decide later, and Delete recovery copies controls.
- Track autosave revisions per project identity, retain distinct same-second
  copies, and preserve recovery when an Open or Save dialog is cancelled.

### Added

- Laboratory notebook at the end of the toolbar: project notes and editable
  descriptions grouped by series, spectrum, and fit function. Descriptions remain
  available and marked as deleted when their original objects are removed.
- Add description in series, spectrum, and function context menus; notebook data
  is saved in .fitproj projects and exported directly or through Export analysis as TXT.
- One-click All series / Active series controls beside Display for Overlay and
  Waterfall, shared by rendering, masks, view ranges, and placement offsets.

### Fixed

- Remove selected now resolves spectra by ID instead of comparing NumPy arrays,
  so spectra with identical names can be removed and restored with Undo/Redo.

- Scale live fit progress to the configured evaluation budget, excluding numerical
  Jacobian probes; reach 100% at the exact limit, including non-multiples of 20.
- Aggregate sequential progress over all target budgets, credit early convergence
  in full, retain completed work on Continue, and avoid false completion on pause.
- Add a theme-adaptive Terminate sequential fit button beside Continue to discard
  a paused queue while retaining completed fits and manual model corrections.

- Keep a paused sequential queue available across manual Quick Fit and model edits;
  resume from the current corrected spectrum using the saved sequence settings.
- Resolve parameter edits and lock/unlock controls against the selected spectrum,
  rather than the first source sharing a sequentially propagated function ID.
- Keep Continue sequential fit visible throughout the pause, with a prominent
  theme-adaptive teal/mint button and correct enabled state after work and Undo/Redo.

- Open an explicit, prefilled name dialog from Rename series instead of starting
  an inline editor while the context menu still owns focus.

- Keep background workers alive until their thread exits, including when Abort
  cancels bootstrap uncertainty analysis. Retain the previous valid fit.
- Dispatch background progress, results, errors and cleanup through GUI-thread
  Qt slots, preventing crashes from wrapped callbacks updating widgets off-thread.

### Added

- Name the destination series in the import dialog, with numbered defaults shared
  with New series. Rename existing series by double-click, F2, or the context menu.

### Changed

- Adapt vector toolbar icons to the active palette, with brighter outlines and
  accents in dark mode, explicit disabled colours, and a grey active Mask state.
- Refresh screenshots as part of release preparation.

- Unify toolbar icons, add a dedicated Import data icon, and group Mask beside
  Fit and Quick Fit while keeping background controls together.
- Quick Fit now runs with default independent-fit settings on first use;
  subsequent runs reuse the last configured fit settings.

### Fixed

- Replace Mask/Unmask selectors with a graphical mode button, an Overlay/Waterfall
  scope prompt, right-drag masking and left-drag unmasking.
- Make completed and paused fits undoable/redoable; restore cancelled worker state.
  Keep at most 20 undo operations without duplicating experimental data arrays.
- Make the real desktop Quick Add Function action follow the adjacent full registry
  selector, including changes during placement, while preserving repeated peaks.

### Interface fixes awaiting release

- Allow any source functions to be excluded from sequential copying independently
  of pause monitoring. Preserve existing target functions during copying and keep
  target-local functions out of later propagation, including after resume.

- Require explicit Mask activation for all graphical masking and unmasking gestures.
- Keep Export analysis bundle in the File menu and remove its toolbar button.
- Add matching View all / View active toolbar icons and replace the system icons
  for visual background subtraction and background restoration.

### Fixed

- View all and initial plot bounds use full-resolution experimental data, not
  viewport-clipped render samples or extrapolated model functions.
- Added View active beside View all to frame unmasked experimental samples only.
- Unified plot context-menu, plot auto button, and View/Axes range commands.

### Documentation

- Aligned the README, Quick Start, plugin guide, changelog, and full user manual with
  the behavior available in CurveMole 0.17.0.
- Added a complete spline-background workflow covering visual-only stripping, real
  reversible subtraction, peak placement, fitting, and export.

## [0.17.0] - 2026-09-04

### Added

- Explicit semantic roles for custom peak parameters: centre, height or area, and
  FWHM, sigma, or HWHM.
- Role-aware graphical placement, automatic peak initialization, derived quantities,
  reusable function files, and project round trips.

### Changed

- Improved custom-peak amplitude initialization while retaining name-based
  compatibility for functions created before role metadata existed.

## [0.16.0] - 2026-09-04

### Added

- **Quick Add Function** selector containing every registered built-in, custom, and
  plugin function.
- Persistent `my_curvemole_functions` library loaded at startup, with one safe JSON
  definition per reusable formula.
- Function-aware automatic peak search with a selectable registered peak shape.

### Changed

- Quick Add remembers the last function and supports peaks, splines, backgrounds, and
  generic functions.

## [0.15.0] - 2026-09-04

### Changed

- Raised the default fit budget to 1,000 evaluations and enabled successful early
  convergence when parameter steps become negligible.
- Kept mouse-wheel zoom active throughout Quick Fit and graphical peak placement.

## [0.14.2] - 2026-09-04

### Fixed

- Restored the **Revert background** toolbar action and corrected its signal handling.

## [0.14.1] - 2026-09-04

### Fixed

- Made all per-spectrum export headers safe for whitespace-based parsers.

## [0.14.0] - 2026-09-04

### Added

- Live trial-model refresh every 20 evaluations while preserving the chosen viewport.
- One-file-per-spectrum numeric export for measured data, components, background,
  total fit, and residuals, with optional masking and background subtraction.

### Changed

- Kept wheel zoom interactive during Quick Fit and linked plot refreshes.

## [0.13.0] - 2026-09-04

### Added

- Content-aware import of valid numeric text tables regardless of file extension.
- Automatic detection and manual control of leading metadata rows to ignore.

### Changed

- Preserved decimal-comma, header, delimiter, drag-and-drop, and batch-import behavior
  for arbitrary text-file suffixes.

## [0.12.5] - 2026-09-03

### Fixed

- Completed Windows standalone self-replacement using PowerShell-compatible SHA-256
  verification, stale-file cleanup, restart, and failure logging.

## [0.12.4] - 2026-09-03

### Added

- Live previews and draggable controls for manual function placement.

### Fixed

- Clarified and corrected the parameter-copy workflow.
- Preserved Quick Fit zoom and sorted multi-file imports numerically.

## [0.12.3] - 2026-09-03

### Fixed

- Corrected finalization of Windows self-updates.

## [0.12.2] - 2026-09-03

### Fixed

- Made toolbar Undo visibly restore background-subtracted data even when the
  visual-only background preview remains enabled.

## [0.12.1] - 2026-09-03

### Fixed

- Corrected current/all-spectrum background subtraction, state restoration, and
  prevention of double-counted background functions.

## [0.12.0] - 2026-09-03

### Added

- Configurable sequential propagation of bounds, fixed state, links, background tags,
  enabled state, composition, and grouping.
- Per-function exclusions from the sequential parameter-jump pause trigger.
- Visual-only background-subtracted display and Up/Down spectrum navigation from the
  focused plot.

### Changed

- Displayed peak functions on top of their fitted background in normal view while
  keeping the background-subtracted view non-destructive.

## [0.11.2] - 2026-09-02

### Changed

- Replaced implicit parameter-copy targeting with an explicit source summary and
  project-wide destination checklist.

## [0.11.1] - 2026-09-02

### Fixed

- Added a persistent status-bar button for resuming a paused sequential fit.

## [0.11.0] - 2026-09-02

### Added

- Continuous Quick Peak placement and generalized click-drag initialization for
  registered peak functions.
- Project-wide model-function view with multi-selection and undoable batch actions.
- Undoable parameter copying across selected compatible functions.
- Propagating sequential fitting from an approved source spectrum, with residual and
  parameter-change safeguards and durable pause/resume.

## [0.10.2] - 2026-09-02

### Fixed

- Kept masked samples visible as lightweight grey traces without defeating adaptive
  rendering performance.

## [0.10.1] - 2026-09-02

### Fixed

- Removed a masked-data rendering performance regression.

## [0.10.0] - 2026-09-02

### Added

- Adaptive peak-preserving rendering and view clipping for dense Overlay and
  Waterfall plots without reducing data used for fitting or export.

## [0.9.4] - 2026-09-02

### Added

- Initial adaptive-rendering implementation; the feature release was republished with
  the intended minor version as 0.10.0.

## [0.9.3] - 2026-09-02

### Fixed

- Preserved the plot viewport across refreshes instead of resetting user zoom.

## [0.9.2] - 2026-09-02

### Fixed

- Restored the version badge as a permanent status-bar control.

## [0.9.1] - 2026-09-02

### Fixed

- Applied successful fit results reliably to the project and display.
- Improved version-badge visibility and string fit-mode compatibility.

## [0.9.0] - 2026-09-02

### Added

- Startup and hourly GitHub release checks with a semantic-version status badge and
  one notification per available release.
- In-app verified self-update for supported Linux AppImage and Windows standalone
  packages, including replacement and removal of older executables.

## [0.8.5] - 2026-08-27

### Added

- GitHub artifact attestation for Linux AppImage releases.

### Changed

- Improved download and platform-security guidance.

## [0.8.4] - 2026-08-27

### Fixed

- Bundled every toolbar icon in frozen desktop packages.

## [0.8.3] - 2026-08-27

### Added

- Reproducible application-generated README screenshots for normal, Overlay,
  Waterfall, and dark-mode views.

## [0.8.2] - 2026-08-27

### Changed

- Improved quick-toolbar icon legibility.

## [0.8.1] - 2026-08-27

### Changed

- Replaced quick-toolbar text labels with compact icons and tooltips.

## [0.8.0] - 2026-08-27

### Added

- Undoable creation, renaming, merging, movement, and stable reordering of series and
  spectra without invalidating fit results.

## [0.7.0] - 2026-08-27

### Added

- Per-spectrum colours and non-red series palettes persisted in projects.

### Fixed

- Applied and redrew completed fit parameters immediately; reserved red for the model
  sum.

## [0.6.0] - 2026-08-27

### Added

- Undoable removal of selected curves.
- Systematic component names and optional peak labels on the plot.

## [0.5.0] - 2026-08-27

### Added

- Selective analysis-bundle export with fit results as the only default output,
  optional reports/data/models, and collision-safe ownership tracking.
- Automated versioned Markdown-to-LaTeX/PDF manual generation and release attachment.

## [0.4.0] - 2026-08-27

### Changed

- Unified peaks, backgrounds, and generic formulas in one function registry.
- Made background a component property and improved spline placement/navigation.

## [0.3.0] - 2026-08-27

### Added

- Reversible subtraction of marked model backgrounds, including all-spectrum use.
- Point-by-point spline background controls and parameter lock/unlock actions.

## [0.2.4] - 2026-08-27

### Changed

- Improved bulk selection, graphical parameter linking, update checks, README
  discoverability, and repository metadata.

## [0.2.3] - 2026-08-27

### Fixed

- Corrected release metadata after the GUI action/workflow repair.

## [0.2.2] - 2026-08-27

### Fixed

- Repaired GUI actions, quick tools, and release-update checks.

## [0.2.1] - 2026-08-26

### Fixed

- Allowed additional startup time for frozen desktop smoke tests.

## [0.2.0] - 2026-08-26

### Added

- Click-drag placement of initial peak centre and FWHM.
- Point-by-point cubic-spline background placement with a live preview.
- Direct interval masking by right-dragging the graph.

### Fixed

- Recursive component-panel refresh that crashed when a model component was selected.
- Quick Start, update, and issue links launched from the Linux AppImage now use the
  host desktop libraries instead of the bundled Qt/C++ runtime.

## [0.1.1] - 2026-08-26

### Fixed

- Export-manifest path handling is portable between Windows, Linux, and macOS.
- Windows frozen-application smoke testing now waits for the GUI process correctly.

## [0.1.0] - 2026-08-26

### Added

- Initial scientific data, model, fitting, uncertainty, project, and export engine.
- Initial single-window Qt desktop application.
- Python API, command-line interface, YAML workflows, and extension registry.
- Cross-platform test and packaging workflows.
