# Creating and managing CurveMole plugins

Plugins add features to CurveMole. They do not replace built-in commands, exporters,
solvers or functions through the supported API. Every contribution has a diamond
symbol (◆) in its menu or selector and identifies its providing plugin in the tooltip.
Executable Python plugins are different from safe custom-function/formula JSON files.

## Install, enable, disable and remove

1. Keep the plugin's `.curvemole-plugin.json` manifest and its Python module together
   in a permanent directory. Review the source and install any dependencies in the
   Python environment running CurveMole. The manager does not download dependencies.
2. Open **File > Plugin Manager**, **Choose folder**, then **Scan**.
3. Select the plugin and inspect its identifier, version, API, licence and source.
4. Choose **Review and trust selected plugin…** and approve execution. Contributions
   appear after closing the manager. Enabled plugins load automatically next time,
   independently of the project you open.
5. **Disable** unloads its registrations and keeps the installation for later use.
   **Remove** also forgets the installation and trust decision. Neither deletes your
   source files. Scanning that directory can still show the plugin as available.
   Choose the trust/load button to enable it again.

Before disabling a plugin whose functions are used in the current project, remove
those components or switch to an empty project. Existing plugin data in saved
projects is retained. Manager changes are unavailable while a fit/task is running.

The application configuration directory (reported by Python's
`platformdirs.user_config_path("CurveMole")`) contains `plugins/installed.json`.
This stores manifest paths and enabled state, not a copy of the module. Moving or
changing the local manifest/module requires review again. Keep helper files and
external dependencies under your own version control: the fingerprint checks the
manifest and primary module, not every imported dependency. Legacy Python package
entry points in `curvemole.functions` remain discoverable; their version is checked.

## Recovery and trust

A Python exception in a hosted callback disables its owner for future calls and
restarts, and identifies it in the error. Failed registration rolls back everything
registered by that plugin. `SystemExit` is also contained at these boundaries.
Fit cancellation is not treated as a broken plugin.

A session marker remains after a crash or forced termination. On the next launch,
CurveMole disables all persisted plugins before importing their code, displays a
recovery explanation and lets you review them in **File > Plugin Manager**. Re-enable
one at a time. A normal window close removes the marker. A still-running second
CurveMole process is not treated as a crashed session.

For a manual safe start, set `CURVEMOLE_DISABLE_PLUGINS=1` before launching CurveMole.
This skips automatic loading without deleting the installation list.

**This is failure recovery, not a Python sandbox.** Plugins run with your account's
permissions and can read/write files, import native libraries or deliberately bypass
APIs. Native crashes, infinite loops, callbacks connected directly by a custom Qt
panel, and process termination cannot all be caught in-process. The next-start
recovery prevents repeated automatic loading after such a crash. Only load trusted
code. Frozen desktop builds include CurveMole's dependencies; arbitrary third-party
packages are not installed by copying a plugin. Use a Python installation of
CurveMole when your plugin requires extra packages.

## Minimal plugin

Create two files in one directory:

`my_tools.curvemole-plugin.json`:

```json
{
  "identifier": "org.example.my-tools",
  "version": "1.0.0",
  "api_compatibility": "1",
  "licence": "MIT",
  "capabilities": ["exporters"],
  "module": "my_tools.py"
}
```

`my_tools.py`:

```python
import numpy as np


def export_csv(context):
    curve = context.project.dataset.curve(context.active_curve_id)
    np.savetxt(context.path, np.column_stack([curve.x, curve.y]),
               delimiter=",", header="x,y", comments="")
    return f"Exported {curve.name}"


def register(api):
    api.add("exporters", "csv", "My CSV export", export_csv,
            description="Active spectrum, comma-separated x/y with header")
```

This adds **File > ◆ Exporters > ◆ My CSV export**. CurveMole asks for a destination;
the built-in export commands remain available. The callback owns the external file
write; use a temporary file followed by atomic replacement if partial output would
be a problem. File writes cannot be undone by CurveMole's Undo.

## Registration API

`register(api)` runs once per load. Do registration here, not calculations or dialogs.
`api.version` is `"1"`; `api.identifier` is the manifest identifier.

`api.add(kind, local_id, label, callback, description="...")` returns an identifier
`<plugin identifier>:<local_id>`. Local IDs must be unique across a plugin's kinds.
Duplicate IDs are rejected. The manifest capabilities describe the extension; they
are not operating-system permissions. New optional extension kinds retain API 1
compatibility with existing function plugins.

| Kind | Visible location | Callback contract |
| --- | --- | --- |
| `exporters` | File / plugin Exporters | `callback(context)`; `context.path` is the chosen destination |
| `importers` | File / plugin Importers | `callback(context)`; chosen input in `context.path`; add curves/series to snapshot |
| `transformations` | Data / plugin Transformations | `callback(context)`; edit the snapshot |
| `analysis` | Tools / plugin Analysis | `callback(context)`; return text for a result window |
| `actions` | Tools / plugin Actions | `callback(context)`; edit the snapshot |
| `workflows` | Tools / plugin Workflows | `callback(context)`; perform multiple changes on the snapshot |
| `panels` | View / plugin Panels | `callback(context)` returns a new `PySide6.QtWidgets.QWidget` |
| `plot_layers` | View / plugin Plot Layers | `callback(context)` returns a list of `{x, y, colour}` lines |
| `fit_solvers` | Fit dialog / Solver | `callback(request)` returns a solver result described below |
| `hooks` | No command; notification only | `callback(event, context)` |

Menus with no contributions are hidden. Plot lines must have finite, matching 1D
arrays. They are excluded from automatic view bounds, and cleared on the next plot
refresh; invoke the command again to redraw. Panel widgets are hosted in independent
windows and closed when their plugin is removed. Panel snapshots do not track later
project changes; reconnecting arbitrary internal Qt methods is outside this API.

### Project context and safe edits

Callbacks receive a detached deep copy of the current project, not the main window.

- `context.project`: a `curvemole.core.project.Project` snapshot.
- `context.active_curve_id`: active spectrum ID, or `None` in an empty project.
- `context.selected_curve_ids`: tuple of selected spectrum IDs.
- `context.path`: import/export path, otherwise `None`.
- `context.owner`: providing plugin identifier.
- `context.data`: JSON-compatible dictionary owned by this plugin, stored inside
  the project's `ui_state["plugin_data"]`. It survives saving, reopening and removal
  of the plugin; other plugins' keys should not be touched.

Importers, transformations, actions and workflows commit their snapshot on successful
return as one Undo step. Exceptions discard the snapshot. Read-only projects cannot
run these commands. Changed data should invalidate associated fit results; the host
conservatively invalidates all curves for these general commands. Returning from an
analysis, exporter, panel, plot layer or hook does **not** commit snapshot changes.
Persist annotations/settings from a mutating command, using `context.data`.

Check for empty projects and selections before accessing a curve. Use standard
`Project.add_curve`, `add_series` and model APIs; do not change raw data into an
invalid shape. Host callbacks run on the GUI thread except fit solvers: keep menu
callbacks short. Long computations should currently be implemented as fit solvers
when appropriate; there is no general background-job API in this version.

### Adding a fitting algorithm

```python
from scipy.optimize import least_squares


def solve(request):
    request.cancellation.raise_if_cancelled()
    return least_squares(
        request.residual, request.initial,
        jac=request.jacobian, bounds=request.bounds,
        max_nfev=request.settings.max_nfev,
        loss=request.settings.loss,
    )


def register(api):
    api.add("fit_solvers", "my_solver", "My solver", solve)
```

The request provides `initial` (free-parameter vector), `bounds` (lower/upper arrays),
`residual(vector)`, `jacobian(vector)`, a copied `FitSettings`, and `cancellation`.
Use the supplied residual to retain masks, weights and linked/fixed parameters,
and to report progress and check cancellation. Check `raise_if_cancelled()` in any
long loop that does not call the residual. GUI widgets must not be accessed here.

Return an object with `x`, `success`, `status`, `message`, and non-negative integer
`nfev`. A SciPy `OptimizeResult` supplies these. The host validates the vector and
bounds and recomputes residual/Jacobian, covariance and standard fit statistics.
It does not run the built-in optimizer after your solver. The algorithm must respect
the requested evaluation budget and document any settings it cannot honour.
The same solver is usable in independent, sequential and global fits.

### Adding model functions

Existing `register(registry)` function plugins can keep using
`registry.register(FunctionDefinition(...))`: the argument is now an additive facade.
Reading or replacing the global registry is not part of this contract.

```python
from curvemole.core.functions import formula_definition


def register(api):
    api.register(formula_definition(
        "org.example.my-tools.line", "Laboratory line", "slope*x + offset",
        defaults={"slope": 1.0, "offset": 0.0},
    ))
```

Use a namespaced function identifier. Functions receive the diamond symbol in their
display names. Registering an existing identifier or passing `replace=True` fails,
with no changes to built-ins. Custom function JSON import/export remains separate.

### Hooks and project data

Hooks receive `startup`, `project_refreshed`, and `shutdown`. Refresh notifications
can be frequent. They are observations on snapshots: no implicit mutation of normal
application operations. A failing hook is quarantined and logged. For example,
register `api.add("hooks", "events", "Project events", on_event)` with
`def on_event(event, context): ...`.

## Runnable examples and testing

The repository's `examples/plugins/lab_tools.py` and adjacent manifest demonstrate
all extension kinds without additional dependencies. Copy both to a permanent
folder and install through the manager. For a packaged/offline installation, the
minimal examples above can also be copied directly from this guide.

Before distributing your plugin, test:

1. An empty project, one spectrum, several series, and masked spectra.
2. Loading twice, disabling, enabling, removing, and restarting.
3. A deliberate exception during registration and during an action: no partial
   registration or project edit should remain.
4. A controlled forced termination in a disposable session, then a safe restart.
5. Undo/Redo and project save/reopen, including reopening without the plugin.
6. Solver cancellation, fixed/linked parameters, bounds, early convergence, and
   sequential/global fitting when providing an algorithm.
7. Light/dark themes, clear labels, and no modification of built-in entries.

This is an extensible additive interface, not a promise that arbitrary internal
methods are stable. If a feature needs a new supported contract, extend this API
rather than monkey-patching CurveMole internals.

## Contributing a community plugin

**Where to send it:** create `custom_plugins/your_plugin/` in your GitHub fork,
then open a pull request to `SebRoLENS/curvemole:main`. For browser upload steps,
see [Submit a plugin](../custom_plugins/README.md#submit-a-plugin).
Inside CurveMole, **File > Plugin manager > Share my plugin on GitHub...** opens
these instructions. **Choose plugin folder...** installs locally and never uploads
anything to the public repository.

Follow [custom_plugins/README.md](../custom_plugins/README.md). A submission needs
its own folder, clear manifest, README, licence and functional pytest tests.
The TSV exporter there is a complete minimal example. Run
`python scripts/validate_community_plugins.py` before opening a PR.
GitHub runs validation on Linux, Windows and macOS. A successful main run publishes
a downloadable validated catalog bundle; failed checks cannot publish it.
See the contribution guide for installation, manifest fields, review requirements,
required branch rules and the precise limits of these checks.

## Automatic import processors

`api.add("import_processors", "id", "Label", callback)` registers an optional,
headless workflow selectable in **File > Automatic folder import…**. It is never
started by plugin loading or application startup. Configure plugin options using
a normal action before starting the session.

The callback receives a `PluginContext` containing only the newly imported
acquisition (a fresh, detached `Project`), its active/selected IDs, source `path`,
a copy of the owner's current `context.data` settings, and a `cancellation` token.
It executes in a background thread: do not call Qt, show dialogs, access the main
window or mutate shared objects. Pass `context.cancellation` to fitting operations.

The host commits the returned acquisition's series, models and results as one
undoable addition, only if the original project is still current and writable and
the processor remains enabled. Store durable output and the settings used in each
curve's `metadata`. Acquisition `ui_state` and notebook changes are not merged into
the live project. A returned string is shown in the import log. Existing project
curves and settings are not exposed to the worker. Exceptions do not commit a
partial acquisition; processors may explicitly retain raw curves with diagnostic
metadata when scientific analysis is inconclusive.

The dialog exposes a case-insensitive filename substring, X/Y column indices,
file stability delay, optional inclusion of pre-existing files, and optional
re-import of modified files as new spectra. Only files directly in the folder are
scanned. Symlinks and temporary files are ignored. Identical content for the same
path is not re-imported within the session. Failed files are retried after changes
or via **Retry failed files**. Closing the panel keeps the session running;
**Stop automatic import** ends it. Switching projects stops the session.

Calibrated 1D WinSpec SPE 2.x acquisitions are supported alongside text inputs;
SPE 3.x, uncalibrated axes and image/multiple-ROI acquisitions require export to
calibrated X/Y text first. SPE columns are wavelength in nm followed by one intensity
column per frame; select the desired frame using the Y-column control.

### Nonmodal monitor panels

GUI `panels` and `actions` receive optional `context.services`. Worker processors
and read-only hooks/analysis do not. A service returns detached `snapshot()` values,
provides undoable JSON `save_settings(data, metadata_key=..., curve_metadata=...)`
without invalidating fits, and controls only the owner's single import processor
through `start_monitor`, `stop_monitor`, `monitor_status` and `set_follow`.
Services reject disabled plugins; settings writes reject read-only projects and
running fits. A settings-only action sets `context.settings_only = True` so the
host commits only its owner-scoped `context.data`, preserving fitted states.
Panel callbacks may use a child QTimer to refresh from snapshots. Reopening a
panel reuses its window; unloading a plugin closes its panels. Closing a monitor
panel does not stop automatic import. `Follow newest spectrum` can be toggled
while import runs to preserve manual editing focus.

Panel contributions can pass `auto_show=True` to `api.add("panels", ...)` to open
once when enabled (including application startup), without starting acquisition.
All plugin panels are hosted in generic, scrollable QDockWidgets in the main
window. Users can close, reopen or reposition them. No ruby-specific code is
needed in the host. `context.services.select_masks({curve_id: existing_mask_name})`
selects editable masks and activates the masking tool without altering fit data.
