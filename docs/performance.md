# Desktop performance

The `testing` startup now leaves scientific backends unloaded until the operation
that needs them. A fresh empty desktop does not import SciPy, pandas, matplotlib
or YAML. Fitting, peak detection, convolution, spline interpolation, special
functions, asymmetric errors and automation load their dependencies at first use.
The fit solvers, tolerances, numerical data and project format are unchanged.

## Plugin startup

The desktop paints its window before loading enabled plugins, then loads one
plugin per Qt event turn. Registration and widget creation stay on the GUI thread.
The status bar shows progress; project operations wait until registration is
complete. Native close controls remain available. Files supplied by the launcher
or operating system wait for the plugin registry before opening.

Automatic plugin docks are created before restoring the saved dock hierarchy.
Closing during startup cancels the remaining queue without overwriting that saved
layout or disabling plugins that have not loaded yet. Existing clients constructing
`MainWindow` directly retain synchronous initialization; `create_main_window`
uses deferred loading for empty projects. Projects supplied by an integration
with existing curves initialize synchronously so their functions are available
before the first evaluation.

Disabled plugins are not imported or fingerprinted. Each enabled plugin is
fingerprinted once per load, against its saved trust decision. Changed sources
still require renewed approval; crash recovery still quarantines plugins.
Unchanged installed-plugin records are no longer rewritten at every launch.
The log records each plugin's registration time. Plugin manual discovery waits
until its Help menu opens. Automatic app/plugin update checks wait two/three
seconds after startup is complete; the manual check remains available.

The maintained cosmic-ray removal, ruby fluorescence and Fityk importer plugins
also defer their scientific imports until analysis/import is requested. Their
patch versions were incremented. Existing externally installed copies need a
plugin update to receive those changes; the application does not edit them or
change their enabled setting.

A plugin that performs expensive work inside its own `register()` can still block
that individual event turn. Such work belongs in its operation callback or an
appropriate worker, rather than creating Qt widgets on a background thread.

## Plot redraws

Data, model sums, components and residuals reuse their scene items across redraws.
Data and styles are updated every time, and items for removed spectra/components
are removed. Transient handles, labels, masks and plugin overlays retain their
normal refresh lifecycle. Click handlers are connected once, so repeated redraws
do not accumulate callbacks. Display sampling does not alter scientific arrays.

## Measurements

Measured on Linux, AMD Ryzen 9 9900X, Python 3.14.8, NumPy 2.5.3, SciPy 1.18.1,
PySide6 6.11.2 and pyqtgraph 0.14.0, against testing commit `b3f5e05`.
Startup figures are medians of seven alternating fresh-process runs, using Qt's
offscreen platform and isolated profiles. Memory is Linux peak resident memory,
not installed package size. Python interpreter startup and AppImage mounting are
outside this measurement. Real desktop/font/cache conditions affect timings.

| Scenario | Before | After |
| --- | ---: | ---: |
| Empty window: first paint | 571 ms | 290 ms |
| Empty window: memory at first paint | 244 MiB | 154 MiB |
| Five maintained plugins enabled: first paint | 597 ms | 284 ms |
| Five maintained plugins: registration/panels/layout complete | 571 ms | 335 ms |
| Five maintained plugins: memory after startup | 255 MiB | 162 MiB |
| Imported SciPy submodules at empty startup | 533 | 0 |

Redraw measurements used 50 spectra of 20,000 points, one Gaussian component per
spectrum, a visible offscreen window and five repeated full refreshes, including
event processing, without cProfile instrumentation:

| View | Before | After |
| --- | ---: | ---: |
| Single | 29 ms | 27 ms |
| Overlay | 279 ms | 158 ms |
| Waterfall | 261 ms | 157 ms |

Residual diagnostics were also profiled. Their timings depend strongly on BLAS
thread scheduling; the established autocorrelation calculation was retained.
Normal quantiles use `scipy.special.ndtri` directly, avoiding a full stats import,
and the Durbin–Watson difference array is allocated once. No general fitting or
diagnostic speedup is claimed. Scientific modules consume their normal memory
once those features are used.

Reproduce startup measurements from the repository root:

```sh
uv run python scripts/benchmark_startup.py --runs 7
uv run python scripts/benchmark_startup.py --runs 7 --plugins custom_plugins/by_main_developer
```

The optional `--plugins` directory is executed as trusted code in a disposable
profile. `--source /path/to/old/src` measures another checkout with the same probe
and Python environment. JSON output contains individual samples and medians.
For import attribution, use `python -X importtime -c 'import curvemole.gui.app'`.
For workload attribution use cProfile separately from timing measurements.

Regression coverage checks first paint before plugin execution, intervening Qt
events, thread affinity, source-change quarantine, cancellation, persistence
errors, file-open ordering, dock restoration, item reuse/removal, style changes,
single click delivery and diagnostic equivalence. Wall-clock timing thresholds
are deliberately excluded from the functional test suite.

## October beta audit workloads

`PYTHONPATH=src python scripts/benchmark_audit.py` measures synthetic baseline
extraction, convolved overlays, bounded job submission, worker serialization and
background-history replay in a disposable profile. It does not assert timing
thresholds. Baseline extraction uses only the selected block: it never expands a
batch's block-diagonal covariance or correlation into a full dense matrix.
Fits and uncertainty jobs share a bounded queue, with at most twice the effective
worker count pending; their solver and replica-timeout policies remain distinct.

See `audit-2026-10-27-implementation.md` and the accompanying JSON for the measured
workloads and limits. These are local samples with Python allocation tracing,
not package-size, resident-memory or cross-platform performance guarantees.
