# CurveMole plugin API audit for AI-assisted plugin development

**Stable API baseline: CurveMole 1.4.2.**
**Plugin API version: `"1"`.**
**Audit date: 2026-11-26.**

Download this Markdown file and attach it directly to an AI conversation. It is
self-contained: the plugin contract, host behaviour, examples and test patterns
below were checked against the CurveMole 1.4.2 implementation
(`curvemole.core.plugins`, `curvemole.core.extensions`, `curvemole.gui.plugin_host`,
`curvemole.gui.plugin_services`, `curvemole.gui.plugin_plot`,
`curvemole.gui.folder_import` and `scripts/validate_community_plugins.py`).
The AI does not need the CurveMole source repository. This is an
implementation-checked capability audit, **not a security certification** and
not a review of any particular plugin. Do not silently apply it to a different
CurveMole release; ask for that release's matching audit.

When using this document to generate a plugin:

- Use only the registration calls, extension kinds, context fields and services
  documented here. If a requested feature is absent, say so and propose the
  nearest supported design. Do not monkey-patch CurveMole internals, access the
  main window, replace built-in functions/commands, or invent hooks, events,
  menu locations or service methods.
- Target Python 3.12+ and only CurveMole's bundled dependencies (NumPy, SciPy,
  pandas, PyYAML, Matplotlib, platformdirs, PySide6, pyqtgraph) unless the user
  explicitly accepts a Python (non-frozen) installation with extra packages.
- Ask for the scientific method, units, inputs, expected outputs, error/uncertainty
  treatment and where the feature should appear when these are not supplied.
  State assumptions explicitly.
- Deliver a complete plugin folder: manifest, module, `README.md`, `LICENSE`
  and a functional `test_plugin.py`, plus installation and test commands.
- Keep `register(api)` free of computation, file I/O, dialogs and network access.
- Never let ordinary user mistakes raise from a hosted callback: in CurveMole an
  exception from a plugin callback **disables the whole plugin** (Section 5).
- Plugins run with the user's permissions. Do not add network access, telemetry,
  process execution or writes outside user-chosen paths unless explicitly requested,
  and explain them in the README when present.

Suggested user prompt:

> Use only this attached CurveMole plugin audit to write a complete plugin.
> My installed CurveMole version is [for example 1.4.2], installed as [desktop build / Python
> package]. The plugin should [feature], appear as [exporter / analysis / panel /
> fit solver / model function / import processor ...], work on [active spectrum /
> selected spectra / all series], with inputs [...], units [...], and outputs
> [...]. Deliver manifest, module, README, LICENSE and functional pytest tests.
> List missing information and assumptions, cite the audit sections you used,
> and flag anything the plugin API cannot do.

## Contents

1. Choosing the right extension surface
2. Plugin folder and manifest
3. Discovery, trust, loading and lifecycle
4. Registration API
5. Error containment: what disables a plugin
6. The callback context and how edits are committed
7. Extension kinds, one by one
8. Panel and action services
9. Main-graph plot sessions
10. Core data model needed by plugins
11. Threading, performance and dependencies
12. Testing a plugin
13. Installing, sharing and updating
14. Security and trust
15. Checklist for generated plugins

## 1. Choosing the right extension surface

| Need | Use | Executes Python? |
| --- | --- | --- |
| A new model function expressible as a formula | Function Builder / custom-function JSON (`formula_definition`) | No (safe expression language) |
| A declarative import → preprocess → fit → export pipeline | YAML workflow (see the YAML automation audit) | No |
| Loops, conditionals, batch logic in your own script | Python script (see the Python automation audit) | Yes, your script only |
| New menu commands, exporters, importers, analyses, panels, plot overlays, fit algorithms, executable model functions, automatic per-acquisition processing inside the desktop | **Plugin (this audit)** | Yes, after explicit trust |

Prefer the safe formula mechanism for pure formulas: it needs no trust decision.
Write a plugin only when the feature needs Python, the desktop UI, or new
reusable desktop commands. YAML workflows can load trusted plugins (Section 13.4)
but loading a plugin never adds new YAML stages.

## 2. Plugin folder and manifest

### 2.1 Layout

One plugin = one folder containing exactly one manifest whose name ends in
`.curvemole-plugin.json`, its Python module and (for distribution) documentation
and tests:

```text
my_exporter/
├── my_exporter.curvemole-plugin.json
├── my_exporter.py          # defines register(api)
├── README.md               # shown in Help > Plugin help
├── LICENSE
└── test_plugin.py          # functional pytest tests
```

Help > Plugin help shows `README.md`, `manual.md`, `help.md` or Markdown files in
a `docs/` subfolder beside the manifest, in CurveMole's internal Markdown reader.

### 2.2 Manifest fields

The loader (`PluginMetadata.from_mapping`) requires `identifier`, `version`,
`api_compatibility`, `licence` and `capabilities` (a JSON list); `module` is
required for local plugins; `name` is optional and used as the display name.
The community validator (Section 12.3) is stricter and is the recommended
baseline for every plugin:

| Field | Requirement |
| --- | --- |
| `identifier` | Stable, unique, namespaced; validator regex `[a-zA-Z0-9][a-zA-Z0-9._-]+`, e.g. `org.yourlab.tsv-exporter`. Never change it between versions. |
| `name` | Nonempty human-readable name (menus, tooltips, Plugin help). |
| `description` | Nonempty one-sentence description. |
| `author` | Nonempty; for a new community submission, the GitHub username opening the PR. |
| `version` | `major.minor.patch` (`\d+\.\d+\.\d+`). Increase it on every change. |
| `api_compatibility` | The string `"1"`. Any other value is refused at load time. |
| `licence` | Licence identifier (British spelling of the key); full text in `LICENSE`. |
| `capabilities` | Nonempty list, no duplicates, exactly the kinds actually registered (Section 4.3). |
| `module` | Local filename such as `my_exporter.py` (validator regex `[a-zA-Z0-9_]+\.py`). |
| `test_file` | Local pytest filename such as `test_plugin.py`. |
| `files` | Optional list of extra resource paths inside the folder to include in the source fingerprint (data tables, calibration files). Must not escape the folder. |

Unknown extra fields are allowed (author metadata). Example:

```json
{
  "identifier": "org.yourlab.tsv-exporter",
  "name": "TSV spectrum exporter",
  "description": "Export the active spectrum as tab-separated x/y columns.",
  "author": "your-github-username",
  "version": "1.0.0",
  "api_compatibility": "1",
  "licence": "MIT",
  "capabilities": ["exporters"],
  "module": "tsv_exporter.py",
  "test_file": "test_plugin.py"
}
```

Allowed capabilities: `functions`, `importers`, `exporters`, `transformations`,
`analysis`, `actions`, `workflows`, `import_processors`, `panels`, `plot_layers`,
`hooks`, `fit_solvers`. Capabilities describe contributions; they are **not**
operating-system permissions.

### 2.3 Source fingerprint and re-trust

At trust time CurveMole stores a SHA-256 fingerprint of the plugin's owned files:
the manifest, the entry module, every `*.py` file in the folder tree (except
other manifests' entry modules in a shared flat folder), local modules imported
by the entry module, all files below the module's folder when the module lives
in a subfolder, and the manifest's `files` resources. `__pycache__`,
`.pytest_cache` and `.pyc` are ignored; **symlinks are rejected**. When any owned
file changes, automatic loading fails with "Plugin source changed; review and
trust it again." and the plugin is disabled until the user trusts it again.
Consequences for plugin code:

- Never write into the plugin's own folder at run time (caches, settings,
  results). Use `context.data` (project-scoped), user-chosen paths, or a
  `platformdirs` user data directory.
- Declare data files read by the plugin in `files` so tampering is detected.
- Tests must write only to pytest's `tmp_path` (the validator fails a plugin
  whose files change during validation).

### 2.4 Python entry points (legacy)

Installed Python packages can also expose `register` through the entry-point
group `curvemole.functions`. They are discovered with capability `functions`,
version from the distribution, and still require explicit trust. Prefer local
manifest plugins for new work.

## 3. Discovery, trust, loading and lifecycle

User flow in the desktop: **File > Plugin Manager > Choose folder… > Scan**,
select the plugin, inspect identifier/version/API/licence/source, then **Review
and trust selected plugin…**. Validated catalog plugins are installed through
**Browse validated plugins…**. Scanning is recursive: one folder can hold many
plugin subfolders.

Loading (`PluginManager.load(candidate, trust=..., expected_fingerprint=...)`):

1. `api_compatibility` must equal `"1"`, otherwise `CurveMoleError`.
2. Untrusted plugins raise `PluginTrustError`; nothing is imported.
3. A plugin already loaded must be disabled before reloading.
4. The fingerprint is computed and, if expected, compared.
5. The module is executed with a private module name
   (`curvemole_plugin_<identifier>`), so **sibling helper modules are not
   importable by plain `import helper`** unless the plugin folder is on
   `sys.path`. Keep a plugin in one module, or load helpers explicitly with
   `importlib.util.spec_from_file_location` relative to `__file__`.
6. `register(api)` is called once. If the module itself is callable or defines
   `register`, that is used; otherwise loading fails ("Plugin must define
   register(api).").
7. Any exception during import or registration rolls back **all** contributions
   from that plugin and disables it with "Loading failed".
8. On success the installation record (manifest path, fingerprint, enabled
   state, symbol) is saved in `<user config>/CurveMole/plugins/installed.json`.

Lifecycle facts:

- Enabled plugins autoload at every start, independently of the open project,
  one per Qt event turn; disabled plugins are never imported.
- Each plugin gets a unique symbol (◆, ●, ▲, ...). It is prefixed to every menu
  label and function display name; tooltips name the providing plugin.
- **Disable** unregisters all contributions and keeps the installation.
  **Remove** also forgets the installation and trust; source files are kept.
  Panels of a disabled plugin are closed; its plot layers are removed.
- After a crash or forced termination, the next start disables **all**
  persisted plugins before importing them and shows a recovery notice; the user
  re-enables them one by one. `CURVEMOLE_DISABLE_PLUGINS=1` skips autoload.
- Projects survive plugin removal: `context.data` stays in the project file.
  A project using a plugin's model functions needs that plugin to evaluate them.

## 4. Registration API

```python
def register(api):
    api.version      # "1"
    api.identifier   # the manifest identifier
    key = api.add(kind, local_id, label, callback, *, description="", auto_show=False)
    api.register(function_definition)   # executable model function
```

### 4.1 `api.add`

- `kind` must be one of the eleven extension kinds of Section 7 (everything in
  the capability list except `functions`); `local_id` must be nonempty;
  `callback` must be callable. Otherwise `CurveMoleError`.
- Returns `"<plugin identifier>:<local_id>"`. The key must be unique across all
  kinds of that plugin; duplicates raise `CurveMoleError`.
- The displayed label becomes `"<symbol> <label>"`. `description` is shown in
  tooltips/status tips. `auto_show=True` is meaningful only for `panels`.
- The stored callback is wrapped: calls go through the plugin manager's guard
  (Section 5); `fit_solvers` results are additionally validated.

### 4.2 `api.register(FunctionDefinition)`

- Adds a model function to the registry. `replace=True` raises; an identifier
  already registered (built-in or other plugin) raises. Use a namespaced
  identifier such as `org.yourlab.tools.lorentz_asym`.
- The display name receives the plugin symbol; metadata records the owner,
  source fingerprint and plugin name. The evaluator is wrapped by the guard.
- Legacy `register(registry)` plugins calling `registry.register(definition)`
  receive the same facade and keep working.

### 4.3 Capabilities must match registrations

The validator loads the plugin in a fresh process and compares the set of kinds
actually registered (plus `functions` if `api.register` was used) with the
manifest `capabilities`. Any difference fails validation. Register every
contribution unconditionally in `register(api)`; do not register depending on
files, settings or environment.

## 5. Error containment: what disables a plugin

Every hosted callback (menu commands, exporters, importers, analyses, panels'
creation callback, plot layers, hooks, fit solvers, import processors and model
function evaluators) runs through `PluginManager.invoke`. **Any exception other
than fit cancellation marks the plugin as failed, disables it persistently
(`installed.json`), removes its menus and panels, and shows "Plugin disabled".**
The user must re-enable it in Plugin Manager. `FitCancelled` (raised by
`cancellation.raise_if_cancelled()`) is propagated without disabling.

Design rules that follow:

- Treat "no active spectrum", "nothing selected", "wrong data type" as normal
  outcomes. In `analysis` and `exporters`, return an explanatory string instead
  of raising (exporters: check before writing). In mutating commands, return
  early without edits (an unchanged snapshot is committed) and, if feedback is
  needed, use a panel or `analysis` command instead.
- Model function evaluators must not raise for ordinary parameter values during
  fitting; return finite values where defined and `nan`/`inf` elsewhere rather
  than throwing.
- Import processors that cannot analyse a file should keep the raw curves and
  record diagnostic metadata instead of raising.
- Qt slots connected inside your own panel widget are **not** guarded by the
  host: an exception there is not contained by CurveMole. Wrap button handlers
  in `try/except` and show the message in the widget or a `QMessageBox`.
- Do not catch `BaseException` broadly around `raise_if_cancelled()`; let
  cancellation propagate.

## 6. The callback context and how edits are committed

### 6.1 `PluginContext` fields

Desktop callbacks (except `fit_solvers`, which receive a solver request, and
`hooks`, which receive `(event, context)`) receive one `context`:

| Field | Meaning |
| --- | --- |
| `context.project` | Detached copy of the current `Project` (expanded lazily on first access). Never the live project. |
| `context.project_id` | Project ID without expanding the snapshot. |
| `context.active_curve_id` | Active spectrum ID, or `None` in an empty project. |
| `context.selected_curve_ids` | Tuple of selected spectrum IDs (may be empty). |
| `context.path` | Chosen file for `importers`/`exporters` (and source file for import processors); otherwise `None`. |
| `context.owner` | The plugin identifier. |
| `context.data` | JSON-compatible dict owned by this plugin, stored in `project.ui_state["plugin_data"][owner]`; saved with the project. Never touch other plugins' keys. |
| `context.services` | `PluginServices` for `panels` and `actions` only (Section 8); otherwise `None`. |
| `context.cancellation` | Cancellation token for import processors; otherwise `None`. |
| `context.settings_only` | Set to `True` in an `action` to commit only `context.data` (Section 6.3). |

The main window, Qt widgets of the application and the live project are never
passed to plugins.

### 6.2 Commit rules by kind

| Kind | Snapshot edits committed? | Return value |
| --- | --- | --- |
| `importers`, `transformations`, `actions`, `workflows` | Yes, on normal return, as one Undo step labelled with the menu label | Ignored |
| `exporters`, `analysis` | No | Non-`None` result shown as text in a read-only result window |
| `plot_layers` | No | List of line dicts drawn on the main graph |
| `panels` | No | A new `QWidget`, hosted in a dock |
| `hooks` | No | Ignored |
| `import_processors` | Acquisition merged by the host (Section 7.10) | Optional string shown in the import log |

Before a mutating commit the host validates the snapshot: `plugin_data` must be
JSON-serialisable without NaN/Infinity, curve/series IDs must be unique, every
curve is revalidated (arrays, masks, transformation replay) and all parameter
links must resolve. Any failure is an exception → plugin disabled, live project
unchanged. After commit every `Fitted` curve becomes `Modified` (fits are
conservatively invalidated). While a fit or other task is running, every
command except opening a panel is refused, and mutating commands also require an
editable (not read-only) project; in both cases the host shows a message and the
callback is not called.

### 6.3 Settings-only actions

An `actions` callback that only changes plugin settings should set
`context.settings_only = True` and edit `context.data`; the host then saves only
`context.data` through `services.save_settings`, preserving fitted states.

### 6.4 Safe editing patterns

```python
def normalise_selected(context):
    from curvemole.core.calculator import apply_scalar
    ids = context.selected_curve_ids or ((context.active_curve_id,) if context.active_curve_id else ())
    for curve_id in ids:
        apply_scalar(context.project.dataset.curve(curve_id), "normalize_max")
    context.data["last_normalised"] = list(ids)
```

- Change data only through `Curve` methods/transformations and `Project`
  methods (Section 10). Never assign to `curve.x`/`curve.y` (read-only views)
  and never edit lists of series/curves directly when dependency checks matter.
- Store durable per-spectrum results in `curve.metadata[...]` (JSON-compatible)
  and plugin settings in `context.data`.

## 7. Extension kinds, one by one

Menu locations (submenus are hidden when empty):

| Kind | Location |
| --- | --- |
| `importers`, `exporters` | File > Plugins: Importers / Exporters |
| `transformations` | Data > Plugins: Transformations |
| `analysis`, `actions`, `workflows` | Tools > Plugins: Analysis / Actions / Workflows |
| `panels`, `plot_layers` | View > Plugins: Panels / Plot Layers |
| `fit_solvers` | Solver selector of the Fit settings dialog |
| `import_processors` | "Automatic workflow" selector in File > Automatic folder import… |
| `hooks` | No menu entry |
| `functions` (via `api.register`) | Function selectors, with the plugin symbol |

### 7.1 `exporters`

`callback(context)`; the host asks for the destination with a Save dialog and
passes it as `context.path` (a string). The plugin writes the file itself; this
is not undoable. Write to a temporary file in the same directory and
`os.replace` it when partial output would be harmful.

```python
import numpy as np

def export_tsv(context):
    if context.active_curve_id is None:
        return "No active spectrum to export."
    curve = context.project.dataset.curve(context.active_curve_id)
    np.savetxt(context.path, np.column_stack([curve.x, curve.y]),
               delimiter="\t", header="x\ty", comments="")
    return f"Exported {curve.name} to {context.path}"

def register(api):
    api.add("exporters", "tsv", "TSV spectrum", export_tsv,
            description="Active spectrum, tab-separated x/y with header")
```

### 7.2 `importers`

`callback(context)`; the host asks for an input file (`context.path`). Add
curves to the snapshot; they are committed as one Undo step.

```python
from pathlib import Path
import numpy as np
from curvemole import Curve, Series

def import_lab(context):
    values = np.loadtxt(context.path, delimiter=",", skiprows=1, ndmin=2)
    series = Series(Path(context.path).stem)
    context.project.add_series(series)
    for column in range(1, values.shape[1]):
        context.project.add_curve(
            Curve(f"{Path(context.path).stem} c{column + 1}", values[:, 0], values[:, column],
                  source=str(context.path), x_unit="nm", y_unit="counts"),
            series)
```

A `Curve` needs at least two matching rows; store provenance in `source` and
`metadata`.

### 7.3 `transformations`, `actions`, `workflows`

All three are `callback(context)` editing the snapshot and committed as one Undo
step; they differ only in menu placement and intent (single data operation /
command / multi-step procedure). Only `actions` (and `panels`) receive
`context.services`.

### 7.4 `analysis`

`callback(context)` → text. Read-only: snapshot edits are discarded.

```python
def summary(context):
    if context.active_curve_id is None:
        return "Select a spectrum first."
    curve = context.project.dataset.curve(context.active_curve_id)
    return f"{curve.name}\nPoints: {len(curve)}\nMean y: {float(np.mean(curve.y)):.8g}"
```

### 7.5 `plot_layers`

`callback(context)` → list of `{"x": array, "y": array, "colour": "#RRGGBB"}`
(`colour` optional, default `#cc79a7`). Arrays must be finite, one-dimensional and
of equal shape, otherwise the plugin is disabled. Lines are drawn in data
coordinates, excluded from autoscaling, replaced when the command is run again,
and removed on the next native plot refresh. For interactive, persistent
overlays tied to a spectrum use `plot_session` (Section 9).

### 7.6 `panels`

`callback(context)` → **a new** `PySide6.QtWidgets.QWidget`. The host wraps it
in a scrollable `QDockWidget` (object name `plugin_panel_<key>`) that joins the
native tool tab group; users can move, detach, close and reopen it. Selecting
the menu entry again re-activates the existing dock instead of calling the
callback. `auto_show=True` opens the panel once when the plugin is enabled,
including at application start.

The `context` is a snapshot taken when the panel is created and does not follow
later changes. Keep only `context.services` (and `context.owner`) in the widget
and fetch fresh data through services (`settings()`, `active_spectrum_state()`,
`spectrum_snapshot()`). Poll with a child `QTimer` and pause it while the panel
is hidden. Parent all Qt objects to the panel so they are destroyed with it.

```python
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

def create_panel(context):
    services = context.services
    widget = QWidget()
    label = QLabel("No spectrum", widget)
    button = QPushButton("Store mean in spectrum metadata", widget)
    layout = QVBoxLayout(widget)
    layout.addWidget(label)
    layout.addWidget(button)
    state = {"last": None}

    def refresh():
        try:
            current = services.active_spectrum_state()   # (project_id, curve_id, hash, name)
        except ValueError:
            timer.stop()                                  # plugin disabled/unloaded
            return
        if current != state["last"]:
            state["last"] = current
            label.setText(current[3] or "No spectrum")

    def store():
        try:
            snap = services.spectrum_snapshot()
            if snap.active_curve_id is None:
                label.setText("Select a spectrum first.")
                return
            curve = snap.project.dataset.curve(snap.active_curve_id)
            services.save_settings(services.settings(), metadata_key="org.yourlab.mean",
                                   curve_metadata={curve.id: {"mean_y": float(curve.y.mean())}})
        except ValueError as exc:          # read-only project, running fit, stale ID ...
            label.setText(str(exc))

    button.clicked.connect(store)
    timer = QTimer(widget)
    timer.setInterval(500)
    timer.timeout.connect(refresh)
    timer.start()
    return widget

def register(api):
    api.add("panels", "mean", "Mean monitor", create_panel, auto_show=False)
```

### 7.7 `hooks`

`callback(event, context)` with `event` in `"startup"`, `"project_refreshed"`,
`"shutdown"`. Observation only: snapshot edits are discarded. `project_refreshed`
can be very frequent; keep hooks fast and avoid dialogs and file writes. An
exception disables the plugin (and is logged).

### 7.8 `fit_solvers`

`callback(request)` runs on the fit worker thread (no Qt access). The request
(`types.SimpleNamespace`) provides:

| Field | Meaning |
| --- | --- |
| `initial` | Free-parameter start vector (copy; internal scaled coordinates) |
| `bounds` | `(lower, upper)` arrays (copies; may contain ±inf) |
| `residual(vector)` | Weighted residual vector; applies masks, fit ranges, weights, fixed and linked parameters, reports progress and checks cancellation |
| `jacobian(vector)` | Dense Jacobian of the residual |
| `settings` | Deep copy of `FitSettings` (`max_nfev`, `ftol`, `xtol`, `gtol`, `loss`, `f_scale`, `x_scale`, `seed`, `workers`, ...) |
| `cancellation` | Token: `raise_if_cancelled()`, `cancelled` |

Return an object with `x`, `success`, `status`, `message` and a non-negative
integer `nfev` (a SciPy `OptimizeResult` qualifies). `x` must have the shape of
`initial`, be finite and inside the bounds, else the plugin is disabled. The host
then recomputes residuals, Jacobian, covariance and statistics through its
standard problem; it does not run the built-in optimiser afterwards. The same
solver works for independent, sequential and global fits. Selecting it in a
script: `FitSettings(solver="<plugin identifier>:<local_id>")` after loading the
plugin. Respect `settings.max_nfev` and document settings you cannot honour.

```python
from scipy.optimize import least_squares

def solve(request):
    request.cancellation.raise_if_cancelled()
    s = request.settings
    return least_squares(request.residual, request.initial, jac=request.jacobian,
                         bounds=request.bounds, max_nfev=s.max_nfev, ftol=s.ftol,
                         xtol=s.xtol, gtol=s.gtol, loss=s.loss, f_scale=s.f_scale,
                         x_scale=s.x_scale)

def register(api):
    api.add("fit_solvers", "lab_lsq", "Laboratory least squares", solve)
```

Fit provenance records the solver's key, owner and source fingerprint; replaying
a recorded fit fails if the solver plugin changed or is missing.

### 7.9 `functions` (executable model functions)

```python
import numpy as np
from curvemole.core.functions import FunctionDefinition, ParameterSpec, formula_definition

def _asym_lorentz(x, p, metadata):
    width = p["width"] * (1 + p["asym"] * np.sign(x - p["center"]))
    return p["amplitude"] / (1 + ((x - p["center"]) / width) ** 2)

def register(api):
    api.register(formula_definition(
        "org.yourlab.tools.line", "Laboratory line", "slope*x + offset",
        defaults={"slope": 1.0, "offset": 0.0}))
    api.register(FunctionDefinition(
        "org.yourlab.tools.asym_lorentz", "Asymmetric Lorentzian", "peak", _asym_lorentz,
        parameter_specs=(ParameterSpec("amplitude", 1.0), ParameterSpec("center", 0.0),
                         ParameterSpec("width", 1.0, minimum=1e-12),
                         ParameterSpec("asym", 0.0, minimum=-0.99, maximum=0.99)),
        description="Lorentzian with different left/right widths"))
```

`FunctionDefinition(identifier, display_name, kind, evaluator, parameter_specs=(),
parameter_factory=None, derived={}, description="", custom_metadata={},
configuration_specs=(), point_initializer=None, minimum_points=None)`;
evaluator protocol `(x_array, values_mapping, metadata_mapping) -> array shaped
like x`. `ParameterSpec(name, default, minimum=-inf, maximum=inf, unit="")`.
`formula_definition(identifier, display_name, formula, *, kind="generic",
defaults=None, bounds=None, derived_formulas=None)`. Evaluators are called very
often during fits: vectorise with NumPy, avoid Python loops and I/O, and never
raise for ordinary parameter values (Section 5). If a formula suffices, a safe
custom-function JSON is preferable to a plugin.

### 7.10 `import_processors`

Registered with `api.add("import_processors", id, label, callback)`. Selectable
in **File > Automatic folder import…** (or started by the same plugin's panel,
Section 8); loading a plugin never starts monitoring. For each newly settled
file the host imports the acquisition into a **fresh, detached Project** and
calls `callback(context)` **on a background worker thread** with an
`ImportProcessorContext`:

- `project`: only this acquisition; `active_curve_id`: its last curve;
  `selected_curve_ids`: all its curves; `path`: source file; `owner`;
- `data`: a copy of the owner's current settings (`context.data`), read-only in
  effect — acquisition `ui_state` and notebook changes are not merged back;
- `cancellation`: pass it to fits (`Fitter.fit(..., cancellation=context.cancellation)`)
  and call `raise_if_cancelled()` in long loops;
- `set_series_destination(series_id, *, name, key="default")`: route a series
  of this acquisition to a persistent destination series. Same `key` appends
  later acquisitions to the same series; distinct keys give separate series.
  Keys are scoped to the processor and project; the host resolves name clashes
  and keeps user renames. Undeclared series are added individually.

Rules: no Qt, no dialogs, no access to the window or shared objects. Store
results and the settings used in each curve's `metadata` and models/fit results
in the acquisition project. The host validates (unique IDs, curves, links,
JSON plugin data) and merges series, models and results as one undoable
addition, only if the original project is still current and writable and the
plugin still enabled. The returned string is appended to the import log.
Feature-detect `set_series_destination` with `hasattr` for older hosts.

```python
def process(context):
    context.cancellation.raise_if_cancelled()
    for series in context.project.dataset.series:
        context.set_series_destination(series.id, name="Beamline scans", key="scans")
    curve = context.project.dataset.curve(context.active_curve_id)
    curve.metadata["org.yourlab.processor"] = {"settings": dict(context.data)}
    return f"Processed {curve.name}"
```

## 8. Panel and action services

`context.services` (panels and actions only). Every call raises `ValueError` if
the plugin is disabled/unloaded; writes raise `ValueError` while a fit runs or
for read-only projects. Feature-detect newer methods with `hasattr` to support
older hosts.

| Method | Behaviour |
| --- | --- |
| `snapshot()` | Full detached `PluginContext` of the current project (with services). Expensive on large projects. |
| `settings()` | Deep copy of this plugin's `plugin_data` only. |
| `active_spectrum_state()` | `(project_id, curve_id, content_hash, curve_name)` without copying arrays; ideal for polling. |
| `spectrum_snapshot(*, include_selected=False, include_models=False, include_settings=False)` | Lightweight context with the active (and optionally selected) spectra; models (all, so links resolve) and this plugin's settings on request; no fit results/history. |
| `active_model_snapshot()` | `spectrum_snapshot(include_models=True, include_settings=True)`. |
| `save_settings(data, *, metadata_key=None, curve_metadata=None)` | Undoable write of this plugin's settings and, optionally, `curve.metadata[metadata_key]` for `{curve_id: value}`; JSON-only; does not invalidate fits. |
| `apply_y_replacement(curve_id, values, *, description=..., metadata_key=None, metadata=None)` | Undoable full-length finite Y replacement as a `replace_y` transformation; keeps x grid; invalidates stale fits. Use after explicit user confirmation. |
| `edit_data_points(curve_id, *, axes="xy")` | Opens the native point editor (`"x"`, `"y"`, `"xy"`) for the active, visible spectrum. Gestures are undoable native edits. |
| `plot_session(curve_id)` | Owner-scoped preview/picking session on the main graph (Section 9). |
| `select_masks({curve_id: mask_name})` | Selects existing masks and activates the masking tool (undoable, no data change). |
| `start_monitor(folder, contains, *, include_existing=False, follow=True)` | Starts automatic folder import with this plugin's **single** import processor. |
| `stop_monitor()`, `monitor_status()`, `set_follow(bool)` | Control/inspect that session; status dict has `running`, `busy`, `other_running`, `follow`, `folder`, `contains`. |

## 9. Main-graph plot sessions

```python
session = context.services.plot_session(curve.id)     # active, visible spectrum only
session.set_preview(
    segments=[{"indices": [10, 11, 12], "y": [4.0, 4.5, 5.0], "colour": "#008080"}],
    markers=[{"index": 11, "colour": "#ff9900", "symbol": "o", "selected": True}],
    selected_interval=(10, 12),
)
session.sampleClicked.connect(on_sample)   # int: current row index
session.markerClicked.connect(on_marker)   # int: position in the markers list
session.pickingChanged.connect(on_picking) # bool
session.invalidated.connect(on_invalid)    # session expired
session.set_picking(True, instruction="Click a measured sample. Esc finishes.")
```

Indices are current row indices of the spectrum; Y values must be finite and
match the indices. Marker symbols: `o`, `x`, `+`, `s`, `d`, `t`. Previews follow
log axes, background subtraction, waterfall offsets and masks; they never change
data, fits, Undo history or the view range. `set_preview()` without arguments
clears; `set_picking(False)` stops picking; `close()` removes the session. The
session expires (emits `invalidated`, `closed=True`) on data, project, active
spectrum, visibility or plugin-availability changes; create a new one afterwards.
Close the session when the panel is hidden.

## 10. Core data model needed by plugins

Public imports: `from curvemole import Curve, Series, Dataset, Mask, Transformation,
Project, Component, Model, Parameter, FitSettings, FitPlan, FitResult, Fitter,
FunctionRegistry, default_registry`. For the complete scripting API (models,
parameters, links, fitting, uncertainty, export) attach the **Python automation
audit** as well.

- `Curve(name, original_x, original_y, *, sigma_x=None, sigma_y=None,
  weights=None, x_label="x", y_label="y", x_unit="", y_unit="", source=None,
  metadata={}, ...)`; at least two matching rows. Current values: `x`, `y`
  (read-only views), `len(curve)`, `id`, `name`, `metadata`, `masks`,
  `active_mask`, `effective_mask` (`True` = excluded), `fit_ranges`,
  `content_hash`. Edits: `mask_interval`, `mask_point`, `add_mask`,
  `move_points`, `delete_points`, `apply_transformation`,
  `undo_transformation`, `restore_original`.
- `curvemole.core.calculator`: `apply_scalar(curve, op, value=None)` with
  `y_add`, `y_subtract`, `y_multiply`, `y_divide`, `x_add`, `x_multiply`,
  `normalize_max`, `normalize_area`; `apply_custom_formula(curve, axis, formula)`;
  `apply_column_formula(curve, target, formula)`;
  `apply_curve_operation(target, operand, operation, *, interpolation="linear",
  extrapolate=False)`; `apply_background_subtraction(curve, background, *,
  method, description, parameters=None)`. They propagate uncertainties and keep
  replayable history.
- `Series(name, curves=[], id=..., metadata={})`; `Dataset` offers `curves`,
  `series`, `curve(id)`, `series_for(id)`.
- `Project`: `dataset`, `curves`, `models`, `results`, `ui_state`,
  `add_series(series)` (add before using it in `add_curve`),
  `add_curve(curve, series=None)`, `remove_curves(ids)` (checks links),
  `model_for(curve_id)`, `add_component(curve_id, component)`,
  `invalidate_fits(ids)`, `resolved_parameter_values()`.
- Models: `Component.create(function_id, registry=..., initial=..., metadata=...)`;
  fitting: `Fitter(registry).fit(...)` / `fit_single(curve, model, settings,
  cancellation=...)` — see the Python audit for exact contracts.

## 11. Threading, performance and dependencies

- Menu callbacks, panels, hooks and services run on the **GUI thread**: keep
  them short (well under a second). There is no general background-job API for
  menu commands in API 1. Long numerical work belongs in a `fit_solvers`
  callback or an `import_processors` callback (both run on worker threads).
- Worker callbacks must not touch Qt or GUI objects. GUI callbacks must not
  start their own threads that touch the project or Qt.
- `context.project` expands a full copy on first access: on large projects
  prefer `services.active_spectrum_state()` / `spectrum_snapshot()` in panels.
- Frozen desktop builds contain only CurveMole's dependencies (Python 3.12+,
  NumPy, SciPy, pandas, PyYAML, Matplotlib, platformdirs, PySide6, pyqtgraph).
  Copying a plugin does not install packages; extra packages require a Python
  installation of CurveMole, and community submissions must not need them.
- Plot layers and previews require finite arrays; check inputs.

## 12. Testing a plugin

### 12.1 Test pattern

```python
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from curvemole import Curve
from curvemole.core.extensions import extensions
from curvemole.core.plugins import PluginManager
from curvemole.core.project import Project
from curvemole.gui.plugin_host import PluginContext

def _load():
    manager = PluginManager()
    candidate = manager.discover_local(Path(__file__).parent)[0]
    manager.load(candidate, trust=True)
    return manager, candidate.metadata.identifier

def test_exported_values_and_header(tmp_path):
    manager, owner = _load()
    try:
        project = Project()
        curve = Curve("Measurement", [1, 2, 3], [7, 8, 9])
        project.add_curve(curve)
        path = tmp_path / "result.tsv"
        context = SimpleNamespace(project=project, active_curve_id=curve.id, path=str(path))
        extensions.entries[owner + ":tsv"].callback(context)
        assert path.read_text().splitlines()[0] == "x\ty"
        np.testing.assert_allclose(np.loadtxt(path, skiprows=1), [[1, 7], [2, 8], [3, 9]])
    finally:
        manager.disable(owner)          # always unregister: the registry is process-global

def test_settings_survive_in_project_data():
    manager, owner = _load()
    try:
        project = Project()
        project.add_curve(Curve("a", [0, 1], [1, 2]))
        context = PluginContext(project, project.curves[0].id, (), owner)
        context.data["k"] = 1           # stored in project.ui_state["plugin_data"][owner]
        assert project.ui_state["plugin_data"][owner] == {"k": 1}
    finally:
        manager.disable(owner)
```

- Call contributions through `extensions.entries["<identifier>:<local_id>"].callback`
  (the guarded callback) or test the plain module functions directly.
- `PluginContext(project, active_curve_id, selected_curve_ids, owner, path=None,
  cancellation=None, services=None)` can be built with a real `Project`.
- Functions: after loading, `manager.registry.get("<function id>")` and evaluate
  with known parameters; solvers: fit a synthetic curve with known parameters
  using `FitSettings(solver="<identifier>:<local_id>")`.
- Panels: create `QApplication.instance() or QApplication([])` with
  `QT_QPA_PLATFORM=offscreen`, pass a fake `services` object
  (`types.SimpleNamespace` with the methods the panel uses), and check widget
  behaviour and the values passed to `save_settings` / `apply_y_replacement`.
- Import processors: build an acquisition `Project`, wrap it in
  `ImportProcessorContext(project, curve_id, ids, owner, path, cancellation=CancellationToken())`
  (`CancellationToken` from `curvemole.core.fitting`) and assert the processed
  metadata/series destinations.

### 12.2 What to test

Functional results (not just "it imports"); empty project and no selection;
several series; masked spectra; deterministic outputs (fixed seeds); a
deliberate failure path that is reported without raising; Undo/Redo and
save/reopen of `context.data`; solver cancellation, bounds and fixed/linked
parameters. Tests must be offline, non-interactive (no blocking dialogs), and
write only under `tmp_path`.

### 12.3 The validator (community plugins)

From the CurveMole repository root:

```bash
python scripts/validate_community_plugins.py
```

It requires the plugin under `custom_plugins/by_main_developer/` or
`custom_plugins/by_community/`, one folder per plugin with exactly one manifest,
all fields of Section 2.2, nonempty `README.md` and `LICENSE`, valid Python syntax
in every `.py`, no symlinks and unique identifiers. For each plugin, in a child
process with `QT_QPA_PLATFORM=offscreen`: load with trust, compare registered
kinds with `capabilities`, disable and verify all contributions are gone
(60 s limit); then run `pytest` on `test_file` (120 s limit). The folder
fingerprint must be identical before and after. GitHub runs this on Linux,
Windows and macOS.

## 13. Installing, sharing and updating

### 13.1 Private/local use

Keep the folder in a permanent location, then **File > Plugin Manager > Choose
folder… > Scan**, review and trust. Editing the source later requires trusting
it again (fingerprint).

### 13.2 Community submission

Fork the repository, add `custom_plugins/by_community/<folder>/` (copying the
TSV exporter is the reference template), run the validator, and open a pull
request to branch **`testing`**. `author` must be the GitHub username opening a
new submission. A maintainer reviews code and tests. Only a successful run on
`main` publishes the validated catalog and per-plugin ZIP files
(`community-plugins-latest` release), installable from **Browse validated
plugins…**.

### 13.3 Updates

Increase `version` (`major.minor.patch`) for every change; the catalog refuses
downgrades and CurveMole offers updates only for loaded plugins, verified
against the catalog SHA-256 and API compatibility. Updates activate after
restart. Keep the identifier unchanged.

### 13.4 Plugins in YAML workflows and scripts

YAML: list manifest paths under `plugins:` and trust identifiers on the CLI
(`curvemole run workflow.yml --trust-plugin <identifier> --json`); the desktop
runner requires the plugin to be enabled in Plugin Manager. Python scripts:

```python
from curvemole import FunctionRegistry, Fitter
from curvemole.core.functions import builtin_definitions
from curvemole.core.plugins import PluginManager

registry = FunctionRegistry()
registry.extend(builtin_definitions())
manager = PluginManager(registry)
candidate = next(c for c in manager.discover_local("plugins")
                 if c.metadata.identifier == "org.yourlab.tools")
manager.load(candidate, trust=True)       # only after reviewing the source
fitter = Fitter(registry)
```

## 14. Security and trust

- Plugins are ordinary Python with the user's permissions; CurveMole's guard is
  failure recovery, **not a sandbox**. Native crashes, infinite loops and
  process termination cannot be contained in-process (the next start disables
  all plugins for review).
- Validation proves tested behaviour, not absence of bugs or malicious code.
- Generated plugins must avoid `eval`/`exec` of user text, shell commands,
  network access and writes outside user-chosen locations unless the user asked
  for them; when present, document them in the README.
- Use CurveMole's safe expression language (`formula_definition`) when users
  must type formulas.

## 15. Checklist for generated plugins

- [ ] Manifest has every field of Section 2.2; `api_compatibility` `"1"`;
      capabilities exactly match registrations.
- [ ] `register(api)` only registers; no work at import time.
- [ ] Namespaced identifiers; unique local IDs; clear labels and descriptions.
- [ ] No exception for ordinary user situations (Section 5); panel slots wrapped.
- [ ] Mutating commands edit only the snapshot through supported methods;
      results in `curve.metadata`, settings in `context.data` (JSON only).
- [ ] No Qt in worker callbacks; GUI callbacks short; cancellation honoured.
- [ ] No writes inside the plugin folder; extra data files listed in `files`.
- [ ] Only bundled dependencies (or explicitly agreed extra packages).
- [ ] README explains purpose, menu location, scientific method and limits,
      inputs/outputs, how to cite the plugin; LICENSE included.
- [ ] Functional, deterministic, offline pytest tests that disable the plugin
      in `finally`; validator passes.
- [ ] Version bumped for every change; identifier never changed.
