# Architecture

Dependency direction is strict:

```text
GUI / CLI / Python API / YAML workflow
                 ↓
      core project and services
                 ↓
data · parameters · models · fitting · uncertainty
                 ↓
     NumPy · SciPy · pandas
```

`curvemole.core` does not import Qt. Optimisers and functions are registries. Project,
fit-model, workflow, and export formats are schema-versioned and use the same domain
objects. This keeps scripting and reproducibility structural rather than additions to
the GUI.

## Fit, rendering and state transactions

`FitLifecycleController` owns the explicit begin, complete, abort and done hooks
for fit Undo. Completion is recorded after sequential/resume handlers have
finished, independently of bootstrap import order. `RenderController` sequences
view preservation, display preparation, background evaluation, the scene, masked
samples and adaptive rendering. Evaluation failures are exposed per curve and
logged once until recovery, with a rate limit when an error message changes.

`core.state` shares immutable completed results and their numerical arrays while
detaching result-map containers, including per-method uncertainty maps. Per-spectrum
fit baselines share the batch result's arrays, which are marked read-only. Its model
restore helper preserves live component and parameter identities for fit Undo;
ordinary edit commands still restore models from their dictionaries. Fit Undo
restores only the per-curve results of the curves the fit changed, and the GUI
refuses edits while a fit or analysis task is running. `Project` validates group removals before mutation and expands fit
invalidation through parameter links and recorded global-fit groups.

Historical update helpers are isolated in `gui.legacy_updates` and re-exported at
their original import paths for external integrations. Current update policy remains
in `UpdateController`.

## Window controllers

`MainWindow` is a composition root. Behaviour that used to be installed on it at
import time now lives in controllers that the window owns, with thin delegating
methods kept at the historical names:

| Attribute | Class | Responsibility |
|---|---|---|
| `session` | `ProjectSession` | new/open/save, autosave, recovery, recent projects, file locks |
| `undo_service` | `UndoService` | the only path to the `QUndoStack`; clean state follows `project.revision` |
| `task_runner` | `TaskRunner` | worker threads, busy state, cancellation |
| `fit_controller` / `uncertainty_controller` | `FitController` / `UncertaintyController` | fits, sequential plans, quick fit, uncertainty analyses |
| `background_controller` | `BackgroundController` | background subtraction, revert, visual-only display |
| `model_edit` | `ModelEditController` | duplicate/delete/move/enable/background/lock/link edits, single or multi-selection, and parameter copy |
| `plot_workspace.placement` / `.scene` / `.view_state` | `PlacementController` / `SceneRenderer` / `ViewState` | plot interaction, drawing and view ranges |

`ModelPanel` is a view: function multi-selection (also across spectra) is native,
and it reports edits through signals. A batch request uses the `_BATCH` marker from
`gui.model_selection`. Menu, toolbar and signal additions from optional modules go
through `gui.window_extensions` stages instead of wrapping `_build_*` methods.
Controllers and other building blocks (`plot*`, `panels`, `dialogs`,
`model_selection`, …) must not import `gui.main_window`.

## GUI extensions and guardrails

`curvemole.gui` imports its extension modules in an explicit, documented order
(several wrap a method installed by an earlier one) and finally `gui.app`, so every
`MainWindow` behaves like the desktop application. Extensions may extend GUI
classes but never replace `curvemole.core` functions: behaviour needed by the CLI,
the Python API or workflows belongs in the core (for example custom peak roles in
`core.peak_roles`). `tests/test_gui_composition.py` enforces this, checks that the
core and CLI load neither Qt nor the GUI, and caps the number of `MainWindow`
methods installed by other modules; lower the cap as extensions become methods or
controllers, never raise it.

Fit and analysis workers receive their own function-registry snapshot, and worker
processes start with single-threaded BLAS/OpenMP so parallel replicas do not
oversubscribe the CPU.