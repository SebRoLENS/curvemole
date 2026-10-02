# Changelog


All notable changes follow Keep a Changelog and Semantic Versioning.

## [Unreleased]

### Fixed

- Coordinate GitHub workflows through one change plan; validate the prepared release
  on all supported systems before publishing complete, checksum-verified downloads.
- Keep development documentation separate from tagged release manuals, preserve
  release identity across retries, and serialize repository writes without cancelling
  queued releases. Reuse generated files and avoid duplicate CI and plugin publication.
- Check custom-formula multicore fitting and bootstrap from frozen desktop builds;
  bound packaging smoke tests and make DOI discovery incremental.

## [0.35.4] - 2026-10-02

### Added

- Optional adaptive Monte Carlo and bootstrap replica counts: configurable initial
  successes, batch size, endpoint tolerance, consecutive stable checks and maximum
  attempts. Save convergence status, actual counts and checkpoint history with results.

### Fixed

- Restore parallel uncertainty analysis for custom formulas in selected/all fitted
  spectra by reconstructing declarative function definitions in spawned workers.
- Apply the same custom-formula support to multicore independent fitting, avoiding
  a silent fallback to serial execution for the entire spectrum batch.
- Honor the uncertainty worker count for a single spectrum or joint global analysis.
- Make spectrum uncertainty-completion tags follow the currently selected analysis
  method, updating immediately when switching methods without discarding saved reports.

## [0.35.3] - 2026-10-02

### Fixed

- Mute unchecked spectrum names immediately, adapting to light and dark themes.
- Skip unchecked spectra during Up/Down navigation in the spectrum tree and plot,
  preserving their position when navigating from a manually selected hidden spectrum.

## [0.35.2] - 2026-10-02

### Fixed

- Recognize typed function/parameter names in advanced links, with or without
  `${...}`, and bind them to stable parameter identities using the selected source
  spectrum. Preserve existing Add references and copy scopes, and report unknown
  or ambiguous names explicitly.
- Export function parameters, fit-result rows and component trace columns in the
  displayed function order, using the current names after Reorder. Preserve the
  mathematical composition, fitted values and uncertainties.

## [0.35.1] - 2026-10-01

### Fixed

- When deleting the first enabled model function, let its surviving successor
  start the model with Add if it previously used multiplication, division or
  convolution. Explain the adjustment before deletion and restore the original
  composition with Undo.
- Roll back function deletion if it would leave dangling parameter links. Keep
  measured data and independent model curves visible when another model has an
  invalid parameter link.

### Changed

- After **Copy fit to next** successfully copies to the next spectrum in the series,
  open that spectrum automatically in the plot and parameter panel.

## [0.35.0] - 2026-10-01

### Added

- Build advanced parameter links by selecting a source function and parameter and
  clicking **Add** to insert readable references at the expression cursor. Combine
  several references with typed arithmetic; selecting another source preserves
  references already inserted and their individual copy behavior.
- Add **At least source**, **At most source**, and **Similar to source** quick
  relationships. Their source-dependent hard bounds update throughout fitting,
  combine with static bounds, and keep the target parameter free. Similarity accepts
  a positive absolute tolerance or a percentage between 0 and 100, exclusive, of
  the source's absolute value. Reject cyclic or infeasible constraints explicitly;
  cross-spectrum relations require all referenced spectra in a global fit.

### Changed

- Rename the default spectrum source to **Same spectrum as this parameter**, and
  group fixed spectrum choices under series headings in project order, using the
  shared spectrum selector style.
- Show the target parameter and the full relation explicitly in **Set link…**;
  advanced expressions are editable and quick relationship expressions are read-only.
- Report physical parameter covariance and marginal confidence intervals for dynamic
  constraints, including uncertainty from a moving source. Export current effective
  bounds separately from global limits and use global limits in uncertainty diagnostics.

### Documentation

- Explain the expression builder, relative and fixed reference copying, quick
  source-dependent bounds, tolerance units, and fitting requirements in the manual,
  Quick Start, and README.

## [0.34.0] - 2026-10-01

### Added

- Choose **This spectrum (follows copies)** (default) or **Specific spectrum**
  in Set link, with a readable source preview and an explanation of copy behavior.
  Save the choice with each parameter, edit it with Undo/Redo, and respect it when
  copying models or parameters and propagating sequential models.

### Fixed

- Fix the v0.33.1 **Reorder** regression: store the sorted function list as display
  order, leaving mathematical evaluation order, parameters, links and fitted state
  unchanged. Multiplication, division and convolution retain their fitted curves.
  Save and copy display order and restore it with Undo/Redo.
- Map local links to destination component IDs when copying without replacing
  model structure, and preserve the source parameter when switching spectrum choices.
- Hide **Last pause reason** after a sequential fit completes or is terminated,
  while retaining it during manual corrections of a paused sequence.

### Documentation

- Explain local and fixed spectrum sources with the two-Gaussian copy example
  in the manual and Quick Start; update README feature descriptions.

## [0.33.1] - 2026-09-30

### Fixed

- Make **Reorder** sort the actual function list by ascending X position (or the
  configured parameter), across function types, as well as renumber automatic names.
  Sort custom-named functions without renaming them, keep unsortable functions in
  place, preserve equal-value order, and support order-only changes with Undo/Redo.
- Mark fits modified when changing enabled function order in a model with
  multiplication, division or convolution; preserve fitted state for additive models.

### Documentation

- Update the manual, README and Reorder tooltips to describe list sorting.

## [0.33.0] - 2026-09-30

### Added

- Add **Select all** and **Select all except backgrounds** to Model & Parameters,
  including project-wide selection in **Show all functions**. Selecting rows
  preserves each function's enabled state.
- Explain function enable/disable and spectrum visibility checkboxes on hover.

### Fixed

- Keep the selected function's ordinal position when switching spectra through
  the tree, plot or series navigation. Select the last available function when
  the target model is shorter and clear the parameter table for an empty model.
- Update function selection and its current row together to avoid a transient
  parameter lookup error when selecting a single function from another spectrum.

### Documentation

- Align the user manual and README with current model controls, data import,
  fit workflows, extensions, exports and desktop update behavior.
- Regenerate the versioned LaTeX/PDF manual and application screenshots.

## Earlier development notes (through 0.32.1)

### Named functions and uncertainty assessments

- Add undoable arbitrary function names, retained across reopen, labels and exports.
- Share named confidence-interval tables and deterministic, explained diagnostics
  across covariance, Monte Carlo, both bootstrap methods and profile likelihood.
- Add per-parameter absolute precision targets; never classify precision by dividing
  by a coordinate-dependent fitted value. Preserve reports and export assessments.
- Default to 200 resampling replicas, preserve fit evaluation defaults, and expose
  profile grid size, scan limits and analysis confidence level.

### Fit audit and advanced configuration

- Keep automatic local least squares and linear loss as defaults; expose solver-specific
  controls, robust loss scale and Reset default without changing curve/model selection.
- Export every recorded optimizer/loss setting as optional CSV and in full HTML/JSON.
- Exclude unused disabled parameters from fitting while retaining transitive link dependencies.
- Fix masked block bootstrap, transformed resampling uncertainties, linked uncertainties at
  upper bounds, one-parameter profiles and copying values together with new bounds.
- Speed up point-mask transfer and block-bootstrap construction.
- Align manual/Quick Start with current navigation, splines, solvers and plugin updates;
  regenerate PDF/LaTeX and support both PDF document-ID string representations.

### Added

- Add native desktop integration: `.fitproj` Open With registration, Linux AppImage
  launcher migration, a per-user Windows installer, Start/menu icons, and macOS
  Finder/Launchpad document declarations.
- Keep portable Windows updates supported through a compact ZIP while offering a
  one-time, settings-preserving migration to the installed application.
- Open native tools, the laboratory notebook and plugin panels in one shared, persistent tabbed workspace.
- Browse the validated online plugin catalog inside Plugin Manager and download
  selected plugins into a user-chosen persistent folder with checksum verification.
- Add the `cosmic_ray_removal` community plugin with review-first modified-Z and
  repeated-spectrum detection, manual candidates, per-correction acceptance and
  an original/cleaned overlay.
- Let nonmodal plugin panels commit a validated, undoable full-spectrum Y
  replacement without exposing the main window.
- Check loaded plugins for validated community updates at startup and hourly, show
  version-aware status, and stage selected updates for the next application start.
- Give each plugin a persistent, distinct symbol and show its name when hovering over
  contributed menus, functions, solvers, workflows and plugin-manager entries.

### Fixed

- Ruby monitor 0.4.0 defaults to 296 K without confirmation, reports pressure with
  propagated 1σ fit uncertainty, and leaves its inverted band mask active for
  manual masking/unmasking. Fit the line outside the bands before inversion.
- Host plugin panels as dock widgets with an optional generic auto-show flag.
- Provide direct latest-validated plugin ZIP links in READMEs, backed by a separate
  rolling download release gated by the three-platform community checks.


### Added

- Add a nonmodal ruby monitor panel with a prominent sample-temperature field,
  Start/Stop, live pressure and runtime follow-newest control for manual editing.
- Recalculate ruby reports/CSV from the current manual fit, withholding pressure
  until refitting after mask/model edits; retain per-acquisition temperature.
- Add scoped plugin panel services for monitoring and undoable settings changes
  that preserve fitted states and spectrum selection.


### Fixed

- Preserve spectrum multi-selection, selected-only overlay/waterfall views and tree
  expansion/scroll position across masks, edits and undo/redo; suppress intermediate
  selection signals while rebuilding the spectrum tree.

- Clarify Advanced Calculator destinations versus formula inputs, require an explicit
  Insert click, show a live destination/expression summary, and label spectrum scope clearly.

### Added

- Opt-in File menu folder import with stable-file polling, filename substring
  filtering, asynchronous plugin processing, newest-spectrum display and undo.
- Calibrated one-dimensional WinSpec SPE 2.x import and headless import processor API.

- Advanced column formulas with named column insertion/destination dropdowns, retained
  import columns in projects, saved expressions and reversible transformation replay.
- Grouped multi-spectrum selection for every calculator operation, with atomic batches.
- Asynchronous spectrum preview inside the multi-file chooser, editable X/Y columns
  and transfer of per-file choices to the mapping dialog.
- Community plugin submission folder, TSV exporter example and cross-platform manifest,
  load/unload and functional validation, with a success-gated catalog artifact.

- Run existing YAML automations from a separate bottom toolbar, remember the file,
  and execute in an isolated process with completion/error reporting and stop control.
- Full-spectrum live import preview with cached parsing and shared adaptive rendering.

- Additive plugin API for exporters, importers, fit solvers, data commands, analyses,
  workflows, panels, plot layers and notification hooks, with marked contributions.
- File Plugin Manager with persistent installations, disable/remove controls,
  transactional loading and safe startup after abnormal termination.
- Plugin author manual, contracts and runnable examples.

### Improved

- Add Copy fit to next with the successor in the same series preselected.
- Default copy and fit target selectors to the active series, with one-click All
  series scope and theme-aware colored group headings. Sequential source choices
  follow the scope; hidden targets are excluded.
- Group all model functions by series and spectrum while preserving multi-selection.
- Guard note click handling during widget destruction.


### Fixed

- Keep three autosave copies per project and remove them on Save or explicit Discard.
- Offer grouped recoverable sessions only after abnormal exits or from the File menu,
  with Recover, Decide later, and Delete recovery copies controls.
- Track autosave revisions per project identity, retain distinct same-second
  copies, and preserve recovery when an Open or Save dialog is cancelled.

### Added

- Selected display scope with stable Shift-click ranges and Ctrl-click selections.
- Theme-aware colored series headers and clickable description icons; empty notes are removed.
- File > Recent projects, with up to ten recent files and a clear-list action.

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
